"""FastAPI backend for the local AnonTestLab dashboard.

Runs an experiment exactly the way `anontestlab run` does: same
ExperimentConfig.from_yaml, same run_experiment, just over HTTP instead
of the CLI. `run_experiment` is synchronous (it calls asyncio.run
internally via the emulator orchestrator), so it's dispatched to a worker
thread rather than awaited directly, which would fail: asyncio.run()
cannot be called from inside the event loop uvicorn is already running.
"""
from __future__ import annotations

import asyncio
import math
import re
import tempfile
from pathlib import Path
from typing import Any

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..experiment import ExperimentConfig, run_experiment

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="AnonTestLab Dashboard")


class RunRequest(BaseModel):
    yaml_text: str


def _sanitize(metrics: dict[str, Any]) -> dict[str, Any]:
    """NaN isn't valid JSON. Browsers' JSON.parse rejects a literal NaN
    token, so map it to null before returning."""
    return {k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in metrics.items()}


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/run")
async def api_run(req: RunRequest) -> dict[str, Any]:
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
    try:
        result = await asyncio.to_thread(run_experiment, config, out_dir)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    response: dict[str, Any] = {
        "name": config.name,
        "metrics": _sanitize(result.metrics),
        "out_dir": str(out_dir),
    }
    if result.baseline_result is not None:
        response["baseline"] = {
            "name": result.baseline_result.config.name,
            "metrics": _sanitize(result.baseline_result.metrics),
        }
    return response


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
