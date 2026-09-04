"""Dashboard tests. Skipped entirely if the optional dashboard deps
aren't installed (pip install -e '.[dashboard]')."""
import time

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from anontestlab.dashboard.server import app

# Entered once for the whole module (not per-request) so /api/run's
# background asyncio task keeps running on the same portal between polls.
# TestClient(app) without `with` spins up a fresh portal per request and
# tears it down right after, which cancels any task it scheduled.
_client_cm = TestClient(app)
client = _client_cm.__enter__()


def teardown_module() -> None:
    _client_cm.__exit__(None, None, None)


def _wait_for_result(timeout: float = 30.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = client.get("/api/status").json()
        if not data["active"]:
            return data
        time.sleep(0.2)
    raise TimeoutError("experiment did not finish within the test timeout")


def test_index_serves_html():
    resp = client.get("/")
    assert resp.status_code == 200
    assert "AnonTestLab Dashboard" in resp.text


def test_run_invalid_yaml_returns_400():
    resp = client.post("/api/run", json={"yaml_text": "not: [valid, experiment"})
    assert resp.status_code == 400


def test_run_missing_name_returns_400():
    resp = client.post("/api/run", json={"yaml_text": "experiment:\n  seed: 1\n"})
    assert resp.status_code == 400


def test_run_rejects_path_traversal_experiment_name():
    yaml_text = """
experiment:
  name: ../../etc/whatever
  seed: 1
  duration_s: 1.0
network:
  nodes: 4
sessions:
  count: 1
"""
    resp = client.post("/api/run", json={"yaml_text": yaml_text})
    assert resp.status_code == 400
    assert "results directory" in resp.json()["detail"]


def test_status_before_any_run_is_inactive():
    data = client.get("/api/status").json()
    assert data["active"] is False


def test_run_starts_immediately_and_status_reports_progress():
    yaml_text = """
experiment:
  name: dashboard-test
  seed: 5
  duration_s: 1.0
  grace_period_s: 0.8
network:
  nodes: 4
sessions:
  count: 2
routing:
  strategy: random
  path_length: 2
traffic:
  real_rate: 4
  cover_rate: 0
adversary:
  type: global_observer
"""
    resp = client.post("/api/run", json={"yaml_text": yaml_text})
    assert resp.status_code == 200
    assert resp.json() == {"started": True, "name": "dashboard-test"}

    status = _wait_for_result()
    assert status["error"] is None
    event_types = {e["type"] for e in status["events"]}
    assert "relays_ready" in event_types
    assert "session_complete" in event_types
    assert "experiment_complete" in event_types

    data = status["result"]
    assert data["name"] == "dashboard-test"
    assert data["metrics"]["delivery_rate"] == 1.0
    assert "baseline" not in data


def test_run_with_baseline_included_in_response(tmp_path):
    baseline_path = tmp_path / "baseline.yaml"
    baseline_path.write_text(
        """
experiment:
  name: dashboard-baseline
  seed: 5
  duration_s: 1.0
  grace_period_s: 0.8
network:
  nodes: 4
sessions:
  count: 2
routing:
  strategy: random
  path_length: 2
traffic:
  real_rate: 4
  cover_rate: 0
"""
    )
    yaml_text = f"""
experiment:
  name: dashboard-treatment
  seed: 5
  duration_s: 1.0
  grace_period_s: 0.8
baseline: {baseline_path}
network:
  nodes: 4
sessions:
  count: 2
routing:
  strategy: random
  path_length: 2
traffic:
  real_rate: 4
  cover_rate: 8
"""
    resp = client.post("/api/run", json={"yaml_text": yaml_text})
    assert resp.status_code == 200

    status = _wait_for_result()
    data = status["result"]
    assert data["baseline"]["name"] == "dashboard-baseline"
    assert data["baseline"]["metrics"]["bandwidth_overhead_x"] == 1.0
    assert data["metrics"]["bandwidth_overhead_x"] > 1.0


def test_run_rejects_a_second_concurrent_run():
    yaml_text = """
experiment:
  name: dashboard-concurrent
  seed: 1
  duration_s: 1.5
  grace_period_s: 1.0
network:
  nodes: 4
sessions:
  count: 2
routing:
  strategy: random
  path_length: 2
traffic:
  real_rate: 4
  cover_rate: 0
"""
    first = client.post("/api/run", json={"yaml_text": yaml_text})
    assert first.status_code == 200
    try:
        second = client.post("/api/run", json={"yaml_text": yaml_text})
        assert second.status_code == 409
    finally:
        _wait_for_result()  # don't leak a background run into the next test
