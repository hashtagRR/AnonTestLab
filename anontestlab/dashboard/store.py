"""Read-only view of the results directory for the dashboard.

Everything here is derived from what the CLI and the dashboard jobs write
to disk (results/<name>/...), so a run started from the terminal shows up
in the dashboard the same way as one started from the browser. There is no
separate database: the directory is the record.
"""
from __future__ import annotations

import csv
import io
import json
import math
import re
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import yaml

_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._=-]{0,127}$")
# Runnable specs the dashboard writes next to its outputs (`atl run` and
# friends read these; configuration.yaml is the flat dict and they can't).
_SPECS = ("experiment.yaml", "reference.yaml", "treatment.yaml")
_TEXT_SUFFIXES = {".yaml", ".yml", ".txt", ".csv", ".json", ".md"}

# Marker file -> kind of output directory, in priority order.
_KINDS = (
    ("metrics.json", "run"),
    ("sweep.csv", "sweep"),
    ("paired_summary.json", "paired"),
    ("comparison.csv", "compare"),
    ("fidelity.json", "fidelity"),
)


def clean(value: Any) -> Any:
    """NaN and infinities aren't valid JSON; browsers' JSON.parse rejects
    them, so they become null, recursively."""
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else value
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, np.generic):
        return clean(value.item())
    return value


def resolve(root: Path, run_id: str) -> Path:
    """Maps a run id (a '/'-separated relative path under the results root)
    to its directory, refusing anything that could step outside root."""
    parts = run_id.split("/")
    if not parts or not all(_SEGMENT.match(p) for p in parts):
        raise ValueError(f"invalid run id {run_id!r}")
    root = root.resolve()
    path = (root / Path(*parts)).resolve()
    if not path.is_relative_to(root) or not path.is_dir():
        raise FileNotFoundError(run_id)
    return path


def kind_of(path: Path) -> str | None:
    for marker, kind in _KINDS:
        if (path / marker).is_file():
            return kind
    return None


def _read_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError):
        return None


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _read_csv(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            rows.append({k: _number(v) for k, v in row.items()})
    return rows


def _number(raw: str | None) -> Any:
    if raw is None or raw == "":
        return None
    for caster in (int, float):
        try:
            return caster(raw)
        except ValueError:
            continue
    return raw


def config_summary(cfg: dict[str, Any]) -> dict[str, Any]:
    """The handful of design axes the experiment table shows."""
    extra = cfg.get("extra_paths") or []
    lengths = [cfg.get("path_length")] + [p.get("path_length") for p in extra]
    return {
        "nodes": cfg.get("num_nodes"),
        "sessions": cfg.get("num_sessions"),
        "seed": cfg.get("seed"),
        "paths": len(lengths),
        "path_lengths": lengths,
        "merge": cfg.get("merge"),
        "split": cfg.get("split_strategy") if extra else None,
        "traffic": cfg.get("real_traffic_distribution"),
        "real_rate": cfg.get("real_rate"),
        "cover_rate": cfg.get("cover_rate"),
        "mix": cfg.get("mix_strategy"),
        "mix_delay_ms": cfg.get("mix_delay_ms"),
        "pool_interval_ms": cfg.get("pool_interval_ms"),
        "shaping": cfg.get("traffic_mode"),
        "cell_size": cfg.get("cell_size"),
        "crypto": cfg.get("crypto_algorithm"),
        "adversaries": cfg.get("adversaries") or [],
        "observed_paths": cfg.get("observed_path_count"),
    }


_HEADLINE = (
    "delivery_rate",
    "oneway_delay_p50_s",
    "oneway_delay_p95_s",
    "bandwidth_overhead_x",
    "tpr_at_fpr_0.001",
    "auc",
    "sessions_failed",
)


def list_outputs(root: Path) -> list[dict[str, Any]]:
    """Every top-level output directory under root, newest first. Sweep
    points live under <sweep>/points/ and are reached from their sweep."""
    if not root.is_dir():
        return []
    out = []
    for path in root.iterdir():
        if not path.is_dir() or not _SEGMENT.match(path.name):
            continue
        kind = kind_of(path)
        if kind is None:
            continue
        marker = next(path / m for m, k in _KINDS if k == kind)
        entry: dict[str, Any] = {"id": path.name, "kind": kind, "mtime": marker.stat().st_mtime}
        if kind == "run":
            cfg = _read_yaml(path / "configuration.yaml") or {}
            metrics = _read_json(path / "metrics.json") or {}
            entry["name"] = cfg.get("name", path.name)
            entry["summary"] = config_summary(cfg)
            entry["metrics"] = {k: metrics.get(k) for k in _HEADLINE if k in metrics}
        elif kind == "paired":
            entry["summary"] = _read_json(path / "paired_summary.json") or {}
        elif kind == "fidelity":
            entry["summary"] = _read_json(path / "fidelity.json") or {}
        elif kind == "sweep":
            meta = _read_json(path / "sweep_meta.json") or {}
            entry["summary"] = {"param": meta.get("param"), "points": len(_read_csv(path / "sweep.csv"))}
        out.append(entry)
    out.sort(key=lambda e: e["mtime"], reverse=True)
    return clean(out)


def _files(path: Path) -> list[dict[str, Any]]:
    files = []
    for f in sorted(path.iterdir()):
        if f.is_file() and _SEGMENT.match(f.name):
            files.append({"name": f.name, "size": f.stat().st_size, "suffix": f.suffix.lstrip(".")})
    return files


def output_detail(root: Path, run_id: str) -> dict[str, Any]:
    path = resolve(root, run_id)
    kind = kind_of(path)
    detail: dict[str, Any] = {"id": run_id, "kind": kind, "files": _files(path), "dir": str(path),
                              "specs": [n for n in _SPECS if (path / n).is_file()]}
    if kind == "run":
        cfg = _read_yaml(path / "configuration.yaml") or {}
        detail.update(
            config=cfg,
            summary=config_summary(cfg),
            metrics=_read_json(path / "metrics.json") or {},
            runnable_spec=(path / "experiment.yaml").is_file(),
            mtime=(path / "metrics.json").stat().st_mtime,
        )
    elif kind == "sweep":
        meta = _read_json(path / "sweep_meta.json") or {}
        rows = _read_csv(path / "sweep.csv")
        points_dir = path / "points"
        points = sorted(p.name for p in points_dir.iterdir() if p.is_dir()) if points_dir.is_dir() else []
        detail.update(param=meta.get("param") or (next(iter(rows[0])) if rows else None), rows=rows,
                      base=meta.get("base"), points=points)
    elif kind == "paired":
        detail.update(summary=_read_json(path / "paired_summary.json") or {},
                      rows=_read_csv(path / "paired_runs.csv") if (path / "paired_runs.csv").is_file() else [],
                      meta=_read_json(path / "paired_meta.json") or {})
    elif kind == "compare":
        detail.update(rows=_read_csv(path / "comparison.csv"))
    elif kind == "fidelity":
        detail.update(summary=_read_json(path / "fidelity.json") or {})
    return clean(detail)


def file_path(root: Path, run_id: str, name: str) -> Path:
    if not _SEGMENT.match(name):
        raise ValueError(f"invalid file name {name!r}")
    f = resolve(root, run_id) / name
    if not f.is_file():
        raise FileNotFoundError(name)
    return f


def read_text_file(root: Path, run_id: str, name: str, limit: int = 2_000_000) -> str:
    f = file_path(root, run_id, name)
    if f.suffix not in _TEXT_SUFFIXES:
        raise ValueError(f"{name} is not a text file")
    data = f.read_bytes()[:limit]
    return data.decode("utf-8", errors="replace")


def npz_summary(root: Path, run_id: str, name: str) -> list[dict[str, Any]]:
    f = file_path(root, run_id, name)
    if f.suffix != ".npz":
        raise ValueError(f"{name} is not an .npz file")
    with np.load(f, allow_pickle=False) as z:
        out = []
        for key in z.files:
            arr = z[key]
            entry: dict[str, Any] = {"key": key, "shape": list(arr.shape), "dtype": str(arr.dtype)}
            if arr.size and np.issubdtype(arr.dtype, np.number):
                finite = arr[np.isfinite(arr)] if np.issubdtype(arr.dtype, np.floating) else arr
                if finite.size:
                    entry.update(min=float(finite.min()), max=float(finite.max()), mean=float(finite.mean()))
            out.append(entry)
    return clean(out)


def oneway_delays(root: Path, run_id: str, points: int = 400) -> dict[str, Any]:
    """The run's empirical one-way-delay CDF: every delivered real packet's
    entry-to-exit delay (from oneway_delays.npz, sorted), thinned to about
    `points` by sampling at evenly spaced ranks, which is a valid way to
    thin an already-sorted empirical distribution without distorting its
    shape (unlike bucketing, which would). Absent entirely when a run
    predates this file or delivered nothing."""
    f = resolve(root, run_id) / "oneway_delays.npz"
    if not f.is_file():
        return {"n": 0, "values": [], "cdf": []}
    with np.load(f, allow_pickle=False) as z:
        values = z["values"]
    n = int(values.size)
    idx = np.arange(n)
    if n > points:
        idx = np.unique(np.linspace(0, n - 1, points).round().astype(int))
    # cdf[i] is the fraction of the FULL (untruncated) population at or
    # below values[idx[i]], i.e. (rank + 1) / n, not (position in the
    # thinned array) / len(thinned array), so the curve stays correct
    # under thinning rather than just visually smooth.
    return clean({"n": n, "values": values[idx].tolist(), "cdf": ((idx + 1) / n).tolist()})


def bundle(root: Path, run_id: str) -> bytes:
    path = resolve(root, run_id)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(path.rglob("*")):
            if f.is_file() and not f.is_symlink():
                z.write(f, Path(path.name) / f.relative_to(path))
    return buf.getvalue()


def _roc(true: np.ndarray, impostor: np.ndarray, points: int = 120) -> list[list[float]]:
    """Empirical ROC of true-pair vs impostor scores, thinned to about
    `points` vertices. Higher score = more likely a true pair."""
    if not true.size or not impostor.size:
        return []
    thresholds = np.unique(np.concatenate([true, impostor]))[::-1]
    if thresholds.size > points:
        idx = np.unique(np.linspace(0, thresholds.size - 1, points).round().astype(int))
        thresholds = thresholds[idx]
    curve = [[0.0, 0.0]]
    for t in thresholds:
        curve.append([float((impostor >= t).mean()), float((true >= t).mean())])
    curve.append([1.0, 1.0])
    return curve


def _histogram(true: np.ndarray, impostor: np.ndarray, bins: int = 30) -> dict[str, Any]:
    both = np.concatenate([true, impostor])
    if not both.size:
        return {"edges": [], "true": [], "impostor": []}
    lo, hi = float(both.min()), float(both.max())
    if hi <= lo:
        hi = lo + 1.0
    edges = np.linspace(lo, hi, bins + 1)
    t, _ = np.histogram(true, edges)
    i, _ = np.histogram(impostor, edges)
    # densities, so a few true pairs and many impostors share one scale
    return {
        "edges": edges.tolist(),
        "true": (t / max(t.sum(), 1)).tolist(),
        "impostor": (i / max(i.sum(), 1)).tolist(),
    }


def compare_runs(root: Path, a: str, b: str) -> dict[str, Any]:
    """Two stored runs side by side: what changed in the configuration,
    then what moved in the metrics (delta is b - a). Shared by the
    /api/compare endpoint and the comparison PDF report, so the two never
    drift apart on what counts as the diff."""
    da, db = output_detail(root, a), output_detail(root, b)
    if da["kind"] != "run" or db["kind"] != "run":
        raise ValueError("compare needs two experiment runs")
    ca, cb = da["config"], db["config"]
    diff = [{"key": k, "a": ca.get(k), "b": cb.get(k)}
            for k in sorted(set(ca) | set(cb)) if ca.get(k) != cb.get(k) and k != "name"]
    ma, mb = da["metrics"], db["metrics"]
    rows = []
    for k in sorted(set(ma) | set(mb)):
        x, y = ma.get(k), mb.get(k)
        is_num = isinstance(x, (int, float)) and isinstance(y, (int, float))
        rows.append({"metric": k, "a": x, "b": y, "delta": (y - x) if is_num else None})
    return clean({"a": {"id": a, "name": ca.get("name"), "seed": ca.get("seed")},
                  "b": {"id": b, "name": cb.get("name"), "seed": cb.get("seed")},
                  "config_diff": diff, "rows": rows})


def suite_evidence(root: Path, run_id: str) -> dict[str, Any]:
    """ROC and score distributions per correlation-suite attacker, scored on
    the suite's own held-out test sessions (test_idx), which is the split
    its TPR@FPR metrics are reported on. True pairs are the diagonal of the
    score matrix, impostors every off-diagonal ingress/egress pairing."""
    f = file_path(root, run_id, "correlation_suite.npz")
    out: dict[str, Any] = {"attackers": []}
    with np.load(f, allow_pickle=False) as z:
        test = z["test_idx"] if "test_idx" in z.files else None
        out["test_sessions"] = int(test.size) if test is not None else None
        for key in z.files:
            if not key.startswith("scores_"):
                continue
            s = z[key]
            if test is not None and test.size:
                s = s[np.ix_(test, test)]
            n = s.shape[0]
            true = np.diag(s)
            impostor = s[~np.eye(n, dtype=bool)]
            true, impostor = true[np.isfinite(true)], impostor[np.isfinite(impostor)]
            out["attackers"].append({
                "id": key[len("scores_"):],
                "true_pairs": int(true.size),
                "impostor_pairs": int(impostor.size),
                "roc": _roc(true, impostor),
                "hist": _histogram(true, impostor),
            })
    return clean(out)
