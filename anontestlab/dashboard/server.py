"""FastAPI backend for the local AnonTestLab dashboard.

Runs an experiment exactly the way `anontestlab run` does: same
ExperimentConfig.from_yaml, same run_experiment, just over HTTP instead
of the CLI. `run_experiment` is synchronous (it calls asyncio.run
internally via the emulator orchestrator), so it's dispatched to a worker
thread rather than awaited directly, which would fail: asyncio.run()
cannot be called from inside the event loop uvicorn is already running.

/api/run starts the experiment as a background task and returns
immediately; the frontend polls /api/status for live progress. One run
at a time, tracked by a single RunTracker rather than per-run IDs, since
this is a local single-user tool.
"""
from __future__ import annotations

import asyncio
import math
import re
import tempfile
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..experiment import ExperimentConfig, run_experiment

STATIC_DIR = Path(__file__).parent / "static"
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

app = FastAPI(title="AnonTestLab Dashboard")


class RunRequest(BaseModel):
    yaml_text: str


class RunTracker:
    """State for the one experiment allowed to run at a time. add_event
    is called from run_experiment's worker thread (via asyncio.to_thread),
    snapshot from the main event loop's /api/status handler, so every
    access goes through the lock."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active = False
        self._events: list[dict[str, Any]] = []
        self._result: dict[str, Any] | None = None
        self._error: str | None = None

    def start(self) -> None:
        with self._lock:
            self._active = True
            self._events = []
            self._result = None
            self._error = None

    def add_event(self, event: dict[str, Any]) -> None:
        with self._lock:
            self._events.append(event)

    def finish(self, result: dict[str, Any] | None = None, error: str | None = None) -> None:
        with self._lock:
            self._active = False
            self._result = result
            self._error = error

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "active": self._active,
                "events": list(self._events),
                "result": self._result,
                "error": self._error,
            }


tracker = RunTracker()


def _sanitize(metrics: dict[str, Any]) -> dict[str, Any]:
    """NaN isn't valid JSON. Browsers' JSON.parse rejects a literal NaN
    token, so map it to null before returning."""
    return {k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in metrics.items()}


def _result_payload(config_name: str, out_dir: Path, result) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": config_name,
        "metrics": _sanitize(result.metrics),
        "out_dir": str(out_dir),
    }
    if result.baseline_result is not None:
        payload["baseline"] = {
            "name": result.baseline_result.config.name,
            "metrics": _sanitize(result.baseline_result.metrics),
        }
    return payload


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/run")
async def api_run(req: RunRequest) -> dict[str, Any]:
    if tracker.snapshot()["active"]:
        raise HTTPException(status_code=409, detail="An experiment is already running. Wait for it to finish.")

    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        f.write(req.yaml_text)
        tmp_path = f.name
    try:
        config = ExperimentConfig.from_yaml(tmp_path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid experiment YAML: {e}")
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    if not _SAFE_NAME.match(config.name):
        raise HTTPException(
            status_code=400,
            detail=(
                f"experiment.name {config.name!r} isn't safe to use as a results directory name "
                "(it becomes results/<name>/ on disk). Use letters, digits, '.', '_', '-' only."
            ),
        )

    out_dir = Path("results") / config.name
    tracker.start()

    async def run_in_background() -> None:
        try:
            result = await asyncio.to_thread(run_experiment, config, out_dir, tracker.add_event)
            tracker.finish(result=_result_payload(config.name, out_dir, result))
        except Exception as e:
            tracker.finish(error=str(e))

    asyncio.create_task(run_in_background())
    return {"started": True, "name": config.name}


@app.get("/api/status")
async def api_status() -> dict[str, Any]:
    return tracker.snapshot()


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
