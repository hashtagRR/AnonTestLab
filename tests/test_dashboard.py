"""Dashboard tests. Skipped entirely if the optional dashboard deps
aren't installed (pip install -e '.[dashboard]')."""
import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from anontestlab.dashboard.server import app

client = TestClient(app)


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


def test_run_small_experiment_end_to_end():
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
    data = resp.json()
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
    data = resp.json()
    assert data["baseline"]["name"] == "dashboard-baseline"
    assert data["baseline"]["metrics"]["bandwidth_overhead_x"] == 1.0
    assert data["metrics"]["bandwidth_overhead_x"] > 1.0
