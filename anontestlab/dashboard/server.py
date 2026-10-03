"""FastAPI backend for the local AnonTestLab dashboard.

Runs experiments exactly the way the CLI does: same ExperimentConfig, same
run_experiment, same writers for sweeps, paired runs and comparisons, just
over HTTP. `run_experiment` is synchronous (it calls asyncio.run
internally via the emulator orchestrator), so every job is dispatched to a
worker thread rather than awaited directly, which would fail: asyncio.run()
cannot be called from inside the event loop uvicorn is already running.

Jobs (run, sweep, paired, fidelity) start as a background task and return
immediately; the frontend polls /api/status for live progress. One job at
a time, tracked by a single JobTracker rather than per-job IDs: this is a
local single-user tool, and relays share the host, so two concurrent jobs
would add scheduling noise to each other's timing.

Everything a job produces lands under results/ in the same layout the CLI
uses, and the read-only /api/outputs endpoints are built from that
directory (see store.py), so terminal and browser runs show up alike.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import re
import signal
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Optional

import yaml
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..adversary import ADVERSARIES
from ..adversary.features import FEATURE_EXTRACTORS
from ..crypto import ALGORITHMS as CRYPTO_ALGORITHMS
from ..emulator.crypto_layer import KEYEXCHANGES
from ..emulator.mixing import STRATEGIES as MIX_STRATEGIES
from ..emulator.splitting import POLICIES as SPLIT_POLICIES
from ..experiment import ExperimentConfig, run_experiment
from ..experiment.compare import ComparisonResult, write_comparison
from ..experiment.config import PathSpec
from ..experiment.paired import PairedResult, write_paired
from ..experiment.sweep import SweepResult, write_sweep
from ..metrics.stats import paired_bootstrap_delta
from ..routing import STRATEGIES as ROUTING_STRATEGIES
from ..traffic import GENERATORS as TRAFFIC_GENERATORS
from . import store
from .spec import config_from_flat, load_spec_text, spec_yaml, validated

STATIC_DIR = Path(__file__).parent / "static"
EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples"
RESULTS_ROOT = Path("results")
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MAX_EVENTS = 5000

app = FastAPI(title="AnonTestLab Dashboard")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class Source(BaseModel):
    """Where a job's config comes from: a YAML spec (the builder draft or a
    pasted file) or an existing run's stored configuration."""
    # Optional rather than `str | None`: pydantic evaluates these annotations
    # at runtime, and the union operator needs Python 3.10.
    yaml_text: Optional[str] = None  # noqa: UP045
    run_id: Optional[str] = None  # noqa: UP045


class RunRequest(BaseModel):
    yaml_text: str
    out_dir: Optional[str] = None  # noqa: UP045


class SpecRequest(BaseModel):
    config: dict[str, Any]


class SweepRequest(BaseModel):
    source: Source
    param: str
    values: list[Any]
    out_dir: Optional[str] = None  # noqa: UP045


class PairedRequest(BaseModel):
    reference: Source
    treatment: Source
    seeds: list[int]
    metric: str = "tpr_at_fpr_0.001"
    margin: float = 0.05
    out_dir: Optional[str] = None  # noqa: UP045


class CompareRunRequest(BaseModel):
    a: Source
    b: Source
    # Where the diff (comparison.csv/.md) goes; each run still gets its
    # own default results/<name>/, never this path.
    out_dir: Optional[str] = None  # noqa: UP045


class FidelityRequest(BaseModel):
    source: Source
    limit_fraction: float = 0.1


class JobStopped(Exception):
    """Raised inside a job's work() to unwind a multi-run loop (sweep,
    paired) early after a stop request, instead of starting further runs.
    Caught specially in _start_job so it finishes the tracker as a clean
    stop rather than a reported error."""


class JobTracker:
    """State for the one job allowed to run at a time. add_event is called
    from the job's worker thread, snapshot from the main event loop's
    /api/status handler, so every access goes through the lock."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active = False
        self._kind: str | None = None
        self._label: str | None = None
        self._out_id: str | None = None
        self._out_dir: str | None = None
        self._browsable = True  # whether out_dir is under results/, where the Outputs/Results browser can see it
        self._started: float | None = None
        self._finished: float | None = None
        self._step = 0
        self._steps = 1
        self._step_label: str | None = None
        self._events: list[dict[str, Any]] = []
        self._events_dropped = 0
        self._result: dict[str, Any] | None = None
        self._error: str | None = None
        self._stop_requested = False
        self._stopped = False
        self._relay_pids: list[int] = []
        self._extra: dict[str, Any] = {}

    def start(self, kind: str = "run", label: str | None = None, steps: int = 1, out_id: str | None = None,
              out_dir: str | None = None, browsable: bool = True, extra: dict[str, Any] | None = None) -> bool:
        """Claims the tracker; False if a job is already active. Check and
        claim happen under one lock so two requests can't both start. extra
        is job-kind-specific routing metadata known before the job runs
        (e.g. a compare-run job's two component run ids), carried through
        even if the job is stopped or fails before its own result payload
        would otherwise report them."""
        with self._lock:
            if self._active:
                return False
            self._active = True
            self._kind, self._label, self._out_id = kind, label, out_id
            self._out_dir, self._browsable = out_dir, browsable
            self._started, self._finished = time.time(), None
            self._step, self._steps, self._step_label = 0, max(steps, 1), None
            self._events, self._events_dropped = [], 0
            self._result = None
            self._error = None
            self._stop_requested = False
            self._stopped = False
            self._relay_pids = []
            self._extra = extra or {}
            return True

    def set_step(self, step: int, label: str | None = None) -> None:
        with self._lock:
            self._step, self._step_label = step, label

    def add_event(self, event: dict[str, Any]) -> None:
        with self._lock:
            self._events.append({**event, "step": self._step, "t": time.time()})
            if len(self._events) > _MAX_EVENTS:
                del self._events[0]
                self._events_dropped += 1
            if event.get("type") == "relays_ready" and event.get("pids"):
                # The current run's relay processes. Overwritten each time a
                # multi-run job (sweep, paired) spawns a fresh set, so a stop
                # request always signals the live ones, never a prior point's
                # already-exited pids.
                self._relay_pids = list(event["pids"])

    def finish(self, result: dict[str, Any] | None = None, error: str | None = None) -> None:
        with self._lock:
            self._active = False
            self._finished = time.time()
            self._result = result
            self._error = error

    def request_stop(self) -> tuple[list[int], float | None]:
        """Marks the job stopped and returns (relay pids known right now,
        this job's started_at). Does not itself end the job: that happens
        once the worker thread's run_experiment() call unwinds, which
        killing those relays triggers (see /api/stop). started_at lets the
        caller's retry watcher confirm, each time it wakes up, that it is
        still signalling this same job rather than one that started later:
        /api/stop's background escalation sleeps between attempts, so by
        the time it wakes the job it was asked to stop may have already
        finished and a new, unrelated one started in its place."""
        with self._lock:
            if not self._active:
                return [], None
            self._stop_requested = True
            self._stopped = True
            return list(self._relay_pids), self._started

    def pids_for_job(self, job_epoch: float) -> list[int]:
        """Relay pids for the active job, or [] if it has finished or a
        different job (by started_at) is active now."""
        with self._lock:
            if not self._active or self._started != job_epoch:
                return []
            return list(self._relay_pids)

    def is_stopped(self) -> bool:
        with self._lock:
            return self._stop_requested

    def snapshot(self, since: int = 0) -> dict[str, Any]:
        """`since` is a count of events already seen, across the whole job;
        events dropped from the front of the buffer still count toward it."""
        with self._lock:
            start = max(since - self._events_dropped, 0)
            return {
                "active": self._active,
                "kind": self._kind,
                "label": self._label,
                "out_id": self._out_id,
                "out_dir": self._out_dir,
                "browsable": self._browsable,
                "extra": dict(self._extra),
                "started_at": self._started,
                "finished_at": self._finished,
                "step": self._step,
                "steps": self._steps,
                "step_label": self._step_label,
                "events": list(self._events[start:]),
                "events_total": self._events_dropped + len(self._events),
                "result": self._result,
                "error": self._error,
                "stopped": self._stopped,
            }


tracker = JobTracker()
_background_task: asyncio.Task | None = None  # keeps the running job's
# task referenced so asyncio can't garbage-collect it mid-run; only one job
# is ever in flight (tracker enforces that), so a single slot is enough.
_stop_task: asyncio.Task | None = None  # same reason, for /api/stop's
# retry-and-escalate task; a new stop request's task simply replaces it.


def _bad_request(message: str) -> HTTPException:
    return HTTPException(status_code=400, detail=message)


def _check_name(name: str, what: str = "experiment.name") -> None:
    if not _SAFE_NAME.match(name):
        raise _bad_request(
            f"{what} {name!r} isn't safe to use as a results directory name "
            "(it becomes results/<name>/ on disk). Use letters, digits, '.', '_', '-' only."
        )


def _load_source(src: Source) -> ExperimentConfig:
    # Untrusted user YAML or an on-disk file: any parse/validation failure
    # must become a clean 400, not an unhandled 500.
    try:
        if src.yaml_text is not None:
            return load_spec_text(src.yaml_text)
        if src.run_id is not None:
            detail = store.output_detail(RESULTS_ROOT, src.run_id)
            if detail["kind"] != "run":
                raise ValueError(f"{src.run_id!r} is not an experiment run")
            config = config_from_flat(detail["config"])
            config.validate()
            return config
    except (ValueError, FileNotFoundError, TypeError, yaml.YAMLError) as e:
        raise _bad_request(f"Invalid experiment: {e}") from e
    raise _bad_request("Give either yaml_text or run_id")


def _pick_out_dir(custom: str | None, default_name: str, what: str) -> Path:
    """A custom output directory (the dashboard's equivalent of the CLI's
    --out) if given, otherwise the default results/<name> convention. A
    custom path is the user's own explicit choice, same trust level as the
    CLI's --out (which has no safety check either), so the results-
    directory-name restriction (_check_name) only applies to the default,
    never to a custom path."""
    if custom:
        return Path(custom)
    _check_name(default_name, what)
    return RESULTS_ROOT / default_name


def _start_job(kind: str, label: str, steps: int, out_dir: Path, work: Callable[[], dict[str, Any]],
                extra: dict[str, Any] | None = None) -> dict[str, Any]:
    out_id, browsable = _out_id_and_browsable(out_dir)
    if not tracker.start(kind, label, steps, out_id, out_dir=str(out_dir), browsable=browsable, extra=extra):
        raise HTTPException(status_code=409, detail="A job is already running. Wait for it to finish.")

    async def run_in_background() -> None:
        try:
            payload = store.clean(await asyncio.to_thread(work))
        except JobStopped as e:
            payload = {"out_id": out_id, "stopped": True, "message": str(e)}
        # A failure anywhere in a real subprocess-based experiment run must
        # reach the tracker as a reported error, not crash this background
        # task silently, so this really does need to be Exception. The one
        # exception (so to speak): a single run or fidelity probe has no
        # loop to raise JobStopped from, so killing its relays for a stop
        # request surfaces as whatever exception that leaves mid-flight
        # (a broken pipe, a short read, ...) rather than one of the few
        # types the emulator's own session-level handling already turns
        # into a clean session_failed event. Report that as a stop too,
        # not as an error the user needs to puzzle over, PROVIDED a stop
        # was actually requested; otherwise this is a genuine failure.
        except Exception as e:  # noqa: BLE001
            if not tracker.snapshot()["stopped"]:
                tracker.finish(error=str(e))
                return
            payload = {"out_id": out_id, "stopped": True, "message": str(e)}
        if tracker.snapshot()["stopped"] and "has_output" not in payload:
            # A stop can also unwind through the plain success path above
            # (killing relays just makes every session fail cleanly, and
            # run_experiment() returns normally), which doesn't know to
            # report this. Whether there is anything to open depends on how
            # far the job got: sweep/paired write each point/seed's
            # evidence before a cooperative JobStopped unwinds the loop,
            # but a single run or fidelity probe only writes anything right
            # at the end, so killing its relays mid-flight usually leaves
            # out_dir empty or missing. Checked on disk, since that is the
            # one thing actually true either way.
            payload = {**payload, "has_output": out_dir.is_dir() and any(out_dir.iterdir())}
        tracker.finish(result=payload)

    global _background_task
    _background_task = asyncio.create_task(run_in_background())
    return {"started": True, "name": label, "kind": kind, "out_id": out_id}


def _out_id_and_browsable(out_dir: Path) -> tuple[str, bool]:
    """store.resolve()/the Outputs API address a run by its path relative
    to RESULTS_ROOT (e.g. "custom-subdir/nested"), not just out_dir.name:
    a custom --out-equivalent path can be a browsable multi-segment path
    under results/ (not just the results/<name> convention), and using
    only its last segment as the id would resolve to the wrong directory,
    or to nothing, whenever it differs from the full relative path."""
    try:
        rel = out_dir.resolve().relative_to(RESULTS_ROOT.resolve())
        return rel.as_posix(), True
    except (OSError, ValueError):
        return out_dir.name, False


def _result_payload(config_name: str, out_dir: Path, result) -> dict[str, Any]:
    out_id, _ = _out_id_and_browsable(out_dir)
    payload: dict[str, Any] = {
        "name": config_name,
        "metrics": store.clean(result.metrics),
        "out_dir": str(out_dir),
        "out_id": out_id,
    }
    if result.baseline_result is not None:
        payload["baseline"] = {
            "name": result.baseline_result.config.name,
            "metrics": store.clean(result.baseline_result.metrics),
        }
    return payload


def _run_one(config: ExperimentConfig, out_dir: Path):
    result = run_experiment(config, out_dir, tracker.add_event)
    # configuration.yaml is the flat dataclass dict, which from_yaml can't
    # read; experiment.yaml next to it is the runnable spec for `atl run`.
    (out_dir / "experiment.yaml").write_text(spec_yaml(config))
    return result


# ---------------------------------------------------------------- pages


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


# ------------------------------------------------------------- metadata


def _templates() -> dict[str, dict[str, Any]]:
    tor = ExperimentConfig.tor_like("tor-like-baseline", seed=20260903, duration_s=8.0, num_sessions=8)
    split = ExperimentConfig(
        name="path-splitting", seed=20260903, duration_s=8.0, num_nodes=12, num_sessions=8,
        extra_paths=[PathSpec("random", 3)], split_strategy="iid",
        adversaries=["global_observer", "correlation_suite"], observed_path_count=1,
    )
    blank = ExperimentConfig(name="new-experiment")
    out = {"tor_like": tor.to_dict(), "path_splitting": split.to_dict(), "blank": blank.to_dict()}
    if EXAMPLES_DIR.is_dir():
        for f in sorted(EXAMPLES_DIR.glob("*.yaml")):
            try:
                out[f"example:{f.stem}"] = ExperimentConfig.from_yaml(f).to_dict()
            except (ValueError, OSError, yaml.YAMLError):
                continue
    return out


@app.get("/api/meta")
async def api_meta() -> dict[str, Any]:
    sweepable = [
        f.name for f in dataclasses.fields(ExperimentConfig)
        if f.type in ("int", "float", "str", "bool", "int | None", "float | None")
        and f.name not in ("name", "baseline")
    ]
    return store.clean({
        "options": {
            "routing_strategy": sorted(ROUTING_STRATEGIES),
            "split_strategy": list(SPLIT_POLICIES),
            "mix_strategy": list(MIX_STRATEGIES),
            "crypto_algorithm": sorted(CRYPTO_ALGORITHMS),
            "crypto_keyexchange": sorted(KEYEXCHANGES),
            "traffic_distribution": sorted(TRAFFIC_GENERATORS),
            "adversaries": sorted(ADVERSARIES),
            "merge": ["disjoint", "common_exit"],
            "cover_drop_mode": ["per_hop", "random_hop"],
            "traffic_mode": ["variable", "fixed_rate"],
            "egress_observation": ["per_path", "merged"],
            "observer_classifier": sorted(FEATURE_EXTRACTORS),
        },
        "defaults": ExperimentConfig(name="new-experiment").to_dict(),
        "templates": _templates(),
        "sweepable": sweepable,
        "results_root": str(RESULTS_ROOT.resolve()),
    })


@app.post("/api/spec")
async def api_spec(req: SpecRequest) -> dict[str, Any]:
    """Flat config (the builder's form state) -> runnable YAML spec, plus
    every validation error and warning, without running anything."""
    try:
        config = config_from_flat(req.config)
        text = spec_yaml(config)
    except (ValueError, TypeError) as e:
        raise _bad_request(f"Invalid config: {e}") from e
    errors, warns = validated(config)
    exists = _SAFE_NAME.match(config.name) is not None and (RESULTS_ROOT / config.name).is_dir()
    return store.clean({"yaml": text, "errors": errors, "warnings": warns, "config": config.to_dict(),
                        "results_exist": exists})


@app.post("/api/parse")
async def api_parse(req: RunRequest) -> dict[str, Any]:
    """YAML spec -> flat config, for importing a file into the builder."""
    config = _load_source(Source(yaml_text=req.yaml_text))
    errors, warns = validated(config)
    return store.clean({"config": config.to_dict(), "errors": errors, "warnings": warns})


# ----------------------------------------------------------------- jobs


@app.post("/api/run")
async def api_run(req: RunRequest) -> dict[str, Any]:
    if tracker.snapshot()["active"]:
        raise HTTPException(status_code=409, detail="An experiment is already running. Wait for it to finish.")
    config = _load_source(Source(yaml_text=req.yaml_text))
    out_dir = _pick_out_dir(req.out_dir, config.name, "experiment.name")

    def work() -> dict[str, Any]:
        result = _run_one(config, out_dir)
        return _result_payload(config.name, out_dir, result)

    return _start_job("run", config.name, 1, out_dir, work)


@app.post("/api/compare_run")
async def api_compare_run(req: CompareRunRequest) -> dict[str, Any]:
    """Runs two fresh, possibly never-executed configs and diffs them in
    one action, unlike the read-only /api/compare (which only diffs two
    runs that already exist). Unlike `atl compare`, which never persists
    either component run (only the diff), both A and B are written to
    their own normal results/<name>/ here, same as a plain run, so they
    stay around as real evidence, not just the comparison summary.
    """
    config_a = _load_source(req.a)
    config_b = _load_source(req.b)
    if config_a.name == config_b.name:
        raise _bad_request(
            "A and B need different experiment.name values: each is written to its own "
            f"results/<name>/, and both resolve to {config_a.name!r}."
        )
    out_dir_a = _pick_out_dir(None, config_a.name, "experiment.name (A)")
    out_dir_b = _pick_out_dir(None, config_b.name, "experiment.name (B)")
    diff_name = f"{config_a.name}_vs_{config_b.name}"
    diff_dir = _pick_out_dir(req.out_dir, diff_name, "comparison output name")
    a_out_id, _ = _out_id_and_browsable(out_dir_a)
    b_out_id, _ = _out_id_and_browsable(out_dir_b)

    def work() -> dict[str, Any]:
        tracker.set_step(0, f"A: {config_a.name}")
        result_a = _run_one(config_a, out_dir_a)
        if tracker.is_stopped():
            raise JobStopped(f"stopped after A ({config_a.name}); B did not run")
        tracker.set_step(1, f"B: {config_b.name}")
        result_b = _run_one(config_b, out_dir_b)
        comparison = ComparisonResult(config_a, config_b, result_a.metrics, result_b.metrics)
        write_comparison(comparison, diff_dir)
        return {"out_id": diff_name, "a_out_id": a_out_id, "b_out_id": b_out_id}

    return _start_job("compare", diff_name, 2, diff_dir, work, extra={"a_out_id": a_out_id, "b_out_id": b_out_id})


@app.post("/api/sweep")
async def api_sweep(req: SweepRequest) -> dict[str, Any]:
    base = _load_source(req.source)
    if not hasattr(base, req.param) or req.param in ("name", "baseline", "extra_paths"):
        raise _bad_request(f"unknown sweep parameter {req.param!r}")
    if not req.values:
        raise _bad_request("give at least one sweep value")
    configs = []
    for value in req.values:
        config = dataclasses.replace(base, **{req.param: value})
        errors, _ = validated(config)
        if errors:
            raise _bad_request(f"{req.param}={value!r}: " + "; ".join(errors))
        configs.append(config)
    out_name = f"{base.name}_sweep_{req.param}"
    out_dir = _pick_out_dir(req.out_dir, out_name, "sweep output name")

    def work() -> dict[str, Any]:
        # The same loop as experiment.sweep.run_sweep, plus progress and
        # per-point evidence under points/, then the same sweep.csv writer.
        rows = []
        stopped_after = None
        for i, (value, config) in enumerate(zip(req.values, configs)):
            if tracker.is_stopped():
                stopped_after = i
                break
            tracker.set_step(i, f"{req.param} = {value}")
            point = re.sub(r"[^A-Za-z0-9._-]", "_", str(value))
            try:
                result = _run_one(config, out_dir / "points" / f"{i:02d}-{point}")
            except Exception:
                # Killing this point's relays for a stop can itself raise
                # (see _start_job's matching comment on the single-run
                # case) instead of letting run_experiment() return with
                # failed sessions. Treat that as "stop here" too, rather
                # than losing every point already written below by
                # letting the exception skip straight past write_sweep.
                # An unrelated failure (stop not requested) still surfaces
                # as a real error.
                if not tracker.is_stopped():
                    raise
                stopped_after = i
                break
            rows.append({req.param: value, **result.metrics})
        # Whatever points finished get written either way, so a stop never
        # throws away completed work.
        write_sweep(SweepResult(param=req.param, rows=rows), out_dir)
        (out_dir / "sweep_meta.json").write_text(json.dumps({"param": req.param, "values": req.values,
                                                             "base": base.name}))
        if stopped_after is not None:
            raise JobStopped(f"stopped after {stopped_after} of {len(configs)} points")
        return {"out_id": out_name, "param": req.param, "points": len(rows)}

    return _start_job("sweep", out_name, len(configs), out_dir, work)


@app.post("/api/paired")
async def api_paired(req: PairedRequest) -> dict[str, Any]:
    reference, treatment = _load_source(req.reference), _load_source(req.treatment)
    if len(req.seeds) < 2:
        raise _bad_request("a paired analysis needs at least two seeds")
    if req.margin <= 0:
        raise _bad_request("the equivalence margin must be positive")
    out_name = f"{reference.name}_vs_{treatment.name}_paired"
    out_dir = _pick_out_dir(req.out_dir, out_name, "paired output name")

    def work() -> dict[str, Any]:
        # The same loop as experiment.paired.run_paired, with progress.
        ref_values, treat_values, done_seeds = [], [], []
        stopped_after = None
        for i, seed in enumerate(req.seeds):
            if tracker.is_stopped():
                stopped_after = i
                break
            try:
                for j, (base, sink) in enumerate(((reference, ref_values), (treatment, treat_values))):
                    tracker.set_step(2 * i + j, f"seed {seed}, {base.name}")
                    metrics = run_experiment(dataclasses.replace(base, seed=seed), None, tracker.add_event).metrics
                    if req.metric not in metrics:
                        raise ValueError(f"metric {req.metric!r} not produced by {base.name!r}; "
                                         f"available: {sorted(metrics)}")
                    sink.append(float(metrics[req.metric]))
            except Exception:
                # Same race as the single-run case (see _start_job):
                # killing this seed's relays for a stop can raise instead
                # of run_experiment() returning with failed sessions.
                # ref_values/treat_values may now hold one more entry than
                # done_seeds for this seed (reference succeeded, treatment
                # didn't); drop it so the two stay aligned for bootstrapping.
                if not tracker.is_stopped():
                    raise
                del ref_values[len(done_seeds):]
                del treat_values[len(done_seeds):]
                stopped_after = i
                break
            done_seeds.append(seed)
        if len(done_seeds) < 2:
            raise JobStopped(f"stopped after {len(done_seeds)} seed(s), too few to summarize")
        effect = paired_bootstrap_delta(ref_values, treat_values, margin=req.margin, resamples=10000, seed=0)
        write_paired(PairedResult(req.metric, done_seeds, reference.name, treatment.name,
                                  ref_values, treat_values, effect, req.margin), out_dir)
        (out_dir / "reference.yaml").write_text(spec_yaml(reference))
        (out_dir / "treatment.yaml").write_text(spec_yaml(treatment))
        (out_dir / "paired_meta.json").write_text(json.dumps({"seeds": done_seeds, "metric": req.metric,
                                                              "margin": req.margin}))
        if stopped_after is not None:
            raise JobStopped(f"stopped after {stopped_after} of {len(req.seeds)} seeds")
        return {"out_id": out_name, "classification": effect.classification}

    return _start_job("paired", out_name, 2 * len(req.seeds), out_dir, work)


@app.post("/api/fidelity")
async def api_fidelity(req: FidelityRequest) -> dict[str, Any]:
    from ..experiment.fidelity import run_fidelity

    config = _load_source(req.source)
    if not 0 < req.limit_fraction < 1:
        raise _bad_request("limit_fraction must be in (0, 1)")
    out_name = f"{config.name}_fidelity"
    _check_name(out_name, "fidelity output name")
    out_dir = RESULTS_ROOT / out_name

    def work() -> dict[str, Any]:
        tracker.set_step(0, "probe with mixing switched off")
        report = run_fidelity(config, req.limit_fraction)
        report = {**report, "experiment": config.name, "limit_fraction": req.limit_fraction,
                  "mix_strategy": config.mix_strategy, "max_concurrent_sessions": config.max_concurrent_sessions,
                  "num_sessions": config.num_sessions}
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "fidelity.json").write_text(json.dumps(store.clean(report), indent=2))
        (out_dir / "experiment.yaml").write_text(spec_yaml(config))
        return {"out_id": out_name, "passes": report["passes"]}

    return _start_job("fidelity", out_name, 1, out_dir, work)


def _signal_pids(pids: list[int], sig: int) -> None:
    for pid in pids:
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            pass  # already exited
        except PermissionError:
            pass  # not a process we own; nothing more to do


@app.post("/api/stop")
async def api_stop() -> dict[str, Any]:
    """Ends the active job by killing its relay subprocesses: a sweep or
    paired run's loop also stops short of its remaining points/seeds
    (see JobStopped), but a single run or fidelity probe has no such loop,
    so it is the relay processes dying that makes run_experiment() return
    (with whatever sessions failed as a result), rather than anything
    asyncio-level reaching into the worker thread.

    request_stop() may run before relays_ready fires (pids still empty)
    and a relay may ignore SIGTERM, so one request kicks off a short
    background retry that re-signals the live pids every 0.7s, escalating
    to SIGKILL, until the job finishes or ten attempts pass.
    """
    pids, job_epoch = tracker.request_stop()
    if job_epoch is None:
        raise HTTPException(status_code=409, detail="No job is running.")
    _signal_pids(pids, signal.SIGTERM)

    async def escalate() -> None:
        # Each wakeup re-confirms it is still signalling job_epoch, not
        # whatever happens to be active by then (see request_stop).
        for _ in range(10):
            await asyncio.sleep(0.7)
            live_pids = tracker.pids_for_job(job_epoch)
            if not live_pids:
                return
            _signal_pids(live_pids, signal.SIGTERM)
        _signal_pids(tracker.pids_for_job(job_epoch), signal.SIGKILL)

    global _stop_task
    _stop_task = asyncio.create_task(escalate())
    return {"stopped": True, "pids_signalled": pids}


@app.get("/api/status")
async def api_status(since: int = 0) -> dict[str, Any]:
    return tracker.snapshot(since)


# ------------------------------------------------------ instant analyses


@app.post("/api/predict")
async def api_predict(src: Source) -> dict[str, Any]:
    """The model's predictions (what `atl predict` prints), and for a stored
    run also its measured metrics, so the page can set them side by side."""
    from ..model import predict

    config = _load_source(src)
    psi = config.suite_psi[0] if config.suite_psi else 0.9
    base_rate = config.suite_base_rates[0] if config.suite_base_rates else 1e-4
    fpr = config.suite_fpr_targets[0] if config.suite_fpr_targets else 1e-3
    try:
        predictions = await asyncio.to_thread(predict, config, fpr, psi, base_rate)
    except (ValueError, ZeroDivisionError) as e:
        raise _bad_request(f"The model can't predict this configuration: {e}") from e
    measured = None
    if src.run_id is not None:
        measured = store.output_detail(RESULTS_ROOT, src.run_id).get("metrics")
    return store.clean({
        "name": config.name, "fpr": fpr, "psi": psi, "base_rate": base_rate,
        "bin_widths_s": config.suite_bin_widths_s, "summary": store.config_summary(config.to_dict()),
        "predictions": predictions, "measured": measured,
    })


@app.get("/api/compare")
async def api_compare(a: str, b: str) -> dict[str, Any]:
    """Two stored runs side by side: what changed in the configuration,
    then what moved in the metrics (delta is b - a)."""
    try:
        return store.compare_runs(RESULTS_ROOT, a, b)
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


# --------------------------------------------------------- stored output


def _not_found(e: Exception) -> HTTPException:
    return HTTPException(status_code=404, detail=f"not found: {e}")


@app.get("/api/outputs")
async def api_outputs() -> list[dict[str, Any]]:
    return store.list_outputs(RESULTS_ROOT)


@app.get("/api/outputs/{run_id:path}/files/{name}")
async def api_output_file(run_id: str, name: str, download: bool = Query(False)) -> Response:
    try:
        if download:
            return FileResponse(store.file_path(RESULTS_ROOT, run_id, name), filename=name)
        return PlainTextResponse(store.read_text_file(RESULTS_ROOT, run_id, name))
    except (ValueError, FileNotFoundError) as e:
        raise _not_found(e) from e


@app.get("/api/outputs/{run_id:path}/npz/{name}")
async def api_output_npz(run_id: str, name: str) -> list[dict[str, Any]]:
    try:
        return store.npz_summary(RESULTS_ROOT, run_id, name)
    except (ValueError, FileNotFoundError) as e:
        raise _not_found(e) from e


@app.get("/api/outputs/{run_id:path}/suite")
async def api_output_suite(run_id: str) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(store.suite_evidence, RESULTS_ROOT, run_id)
    except (ValueError, FileNotFoundError) as e:
        raise _not_found(e) from e


@app.get("/api/outputs/{run_id:path}/latencies")
async def api_output_latencies(run_id: str) -> dict[str, Any]:
    try:
        return store.oneway_delays(RESULTS_ROOT, run_id)
    except (ValueError, FileNotFoundError) as e:
        raise _not_found(e) from e


@app.get("/api/outputs/{run_id:path}/spec")
async def api_output_spec(run_id: str) -> PlainTextResponse:
    """The runnable spec: experiment.yaml if the dashboard wrote one, else
    rebuilt from configuration.yaml (which `atl run` can't read directly)."""
    try:
        try:
            return PlainTextResponse(store.read_text_file(RESULTS_ROOT, run_id, "experiment.yaml"))
        except FileNotFoundError:
            detail = store.output_detail(RESULTS_ROOT, run_id)
            return PlainTextResponse(spec_yaml(config_from_flat(detail["config"])))
    except (ValueError, FileNotFoundError, KeyError, TypeError) as e:
        raise _not_found(e) from e


@app.get("/api/outputs/{run_id:path}/bundle.zip")
async def api_output_bundle(run_id: str) -> Response:
    try:
        data = await asyncio.to_thread(store.bundle, RESULTS_ROOT, run_id)
    except (ValueError, FileNotFoundError) as e:
        raise _not_found(e) from e
    filename = run_id.replace("/", "_") + ".zip"
    return Response(data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def _report_module():
    """The PDF builder, or a 503 naming the fix when matplotlib is missing:
    without this a fresh install without the extra returned a bare 500
    and the browser saved that error as a broken report.pdf."""
    try:
        from . import report
    except ImportError as e:
        raise HTTPException(
            status_code=503,
            detail=f'PDF reports need matplotlib ({e}). Install it with: pip install -e ".[dashboard]"',
        ) from e
    return report


@app.get("/api/outputs/{run_id:path}/report.pdf")
async def api_output_report(run_id: str) -> Response:
    """Dispatches by the output's own kind: a run report for a run, a
    paired-analysis report for a paired output. A comparison has no
    single id to hang this route off of (it names two runs); its report
    is the separate /api/compare/report.pdf below."""
    report = _report_module()

    try:
        kind = store.output_detail(RESULTS_ROOT, run_id)["kind"]
        if kind == "run":
            data = await asyncio.to_thread(report.build_run_report, RESULTS_ROOT, run_id)
        elif kind == "paired":
            data = await asyncio.to_thread(report.build_paired_report, RESULTS_ROOT, run_id)
        else:
            raise _bad_request(f"no PDF report for {run_id!r} ({kind} outputs don't have one yet)")
    except (ValueError, FileNotFoundError, KeyError) as e:
        raise _not_found(e) from e
    filename = run_id.replace("/", "_") + "-report.pdf"
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/api/compare/report.pdf")
async def api_compare_report(a: str, b: str) -> Response:
    report = _report_module()

    try:
        data = await asyncio.to_thread(report.build_compare_report, RESULTS_ROOT, a, b)
    except (ValueError, FileNotFoundError) as e:
        raise _not_found(e) from e
    filename = f"{a}_vs_{b}".replace("/", "_") + "-report.pdf"
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/api/outputs/{run_id:path}")
async def api_output(run_id: str) -> dict[str, Any]:
    try:
        return store.output_detail(RESULTS_ROOT, run_id)
    except (ValueError, FileNotFoundError) as e:
        raise _not_found(e) from e


def main(argv: list[str] | None = None) -> None:
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    print(f"AnonTestLab dashboard: http://127.0.0.1:{args.port}")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
