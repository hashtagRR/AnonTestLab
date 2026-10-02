"""Dashboard tests. Skipped entirely if the optional dashboard deps
aren't installed (pip install -e '.[dashboard]')."""
import os
import time

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from anontestlab.dashboard.server import app

# Entered once for the whole module (not per-request) so a job's
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
    raise TimeoutError("job did not finish within the test timeout")


TOR_LIKE = """
experiment:
  name: {name}
  seed: {seed}
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


def test_index_serves_html():
    resp = client.get("/")
    assert resp.status_code == 200
    assert "AnonTestLab Dashboard" in resp.text


def test_static_modules_are_served():
    for path in ("app.js", "core.js", "charts.js", "builder.js", "views.js", "analyses.js", "styles.css"):
        resp = client.get(f"/static/{path}")
        assert resp.status_code == 200, path


def test_templates_escape_all_interpolation_by_default():
    # Regression guard: the old single-file dashboard escaped experiment
    # and baseline names by hand at each template call site, and once
    # missed one (a real audit finding). The rewrite moved templating to
    # a tagged-template helper (core.js's `html`) that escapes every
    # interpolated value unless it is itself template output, so there is
    # no longer a per-call-site escaping decision to get wrong. This is a
    # structural check (no browser in this suite) that the mechanism is
    # still in place, not a full DOM/XSS behavioral test.
    core = client.get("/static/core.js").text
    assert "function escapeHtml(" in core
    assert "export function html(" in core
    assert "render(values[i])" in core  # every interpolated value is routed through render(), which escapes


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


def test_outputs_resolve_rejects_path_traversal():
    resp = client.get("/api/outputs/..%2f..%2fetc")
    assert resp.status_code == 404


def test_status_before_any_run_is_inactive():
    data = client.get("/api/status").json()
    assert data["active"] is False


def test_meta_lists_options_and_templates():
    data = client.get("/api/meta").json()
    for key in ("routing_strategy", "mix_strategy", "crypto_algorithm", "adversaries", "merge"):
        assert data["options"][key], key
    assert "tor_like" in data["templates"]
    assert "blank" in data["templates"]
    assert "real_rate" in data["sweepable"]
    assert "name" not in data["sweepable"]


def test_spec_round_trips_a_template_and_reports_no_errors():
    meta = client.get("/api/meta").json()
    resp = client.post("/api/spec", json={"config": meta["defaults"]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["errors"] == []
    assert "experiment:" in body["yaml"]

    parsed = client.post("/api/parse", json={"yaml_text": body["yaml"]})
    assert parsed.status_code == 200
    assert parsed.json()["config"]["name"] == meta["defaults"]["name"]


def test_spec_rejects_unknown_field():
    resp = client.post("/api/spec", json={"config": {"name": "x", "not_a_real_field": 1}})
    assert resp.status_code == 400


def test_run_reports_progress_and_writes_a_runnable_spec():
    resp = client.post("/api/run", json={"yaml_text": TOR_LIKE.format(name="dashboard-test", seed=5)})
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"started": True, "name": "dashboard-test", "kind": "run", "out_id": "dashboard-test"}

    status = _wait_for_result()
    assert status["error"] is None
    assert status["kind"] == "run"
    event_types = {e["type"] for e in status["events"]}
    assert {"relays_ready", "session_complete", "experiment_complete"} <= event_types
    assert all("step" in e and "t" in e for e in status["events"])

    data = status["result"]
    assert data["name"] == "dashboard-test"
    assert data["out_id"] == "dashboard-test"
    assert data["metrics"]["delivery_rate"] == 1.0
    assert "baseline" not in data

    detail = client.get("/api/outputs/dashboard-test").json()
    assert detail["kind"] == "run"
    assert "experiment.yaml" in [f["name"] for f in detail["files"]]
    spec = client.get("/api/outputs/dashboard-test/spec").text
    assert "name: dashboard-test" in spec


def test_run_with_baseline_included_in_response(tmp_path):
    baseline_path = tmp_path / "baseline.yaml"
    baseline_path.write_text(TOR_LIKE.format(name="dashboard-baseline", seed=5).replace(
        "adversary:\n  type: global_observer\n", ""))
    yaml_text = TOR_LIKE.format(name="dashboard-treatment", seed=5).replace(
        "cover_rate: 0", "cover_rate: 8") + f"baseline: {baseline_path}\n"
    resp = client.post("/api/run", json={"yaml_text": yaml_text})
    assert resp.status_code == 200

    status = _wait_for_result()
    data = status["result"]
    assert data["baseline"]["name"] == "dashboard-baseline"
    assert data["baseline"]["metrics"]["bandwidth_overhead_x"] == 1.0
    assert data["metrics"]["bandwidth_overhead_x"] > 1.0

    cmp = client.get("/api/compare?a=dashboard-treatment&b=dashboard-test").json()
    assert cmp["a"]["name"] == "dashboard-treatment"
    assert any(row["key"] == "cover_rate" for row in cmp["config_diff"])


def test_run_rejects_a_second_concurrent_job():
    yaml_text = TOR_LIKE.format(name="dashboard-concurrent", seed=1).replace("duration_s: 1.0", "duration_s: 1.5")
    first = client.post("/api/run", json={"yaml_text": yaml_text})
    assert first.status_code == 200
    try:
        second = client.post("/api/run", json={"yaml_text": yaml_text})
        assert second.status_code == 409
        second_sweep = client.post("/api/sweep", json={"source": {"yaml_text": yaml_text},
                                                        "param": "real_rate", "values": [1]})
        assert second_sweep.status_code == 409
    finally:
        _wait_for_result()  # don't leak a background run into the next test


def _wait_for_relay_pids(timeout: float = 10.0) -> list[int]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for event in client.get("/api/status").json()["events"]:
            if event["type"] == "relays_ready":
                return event["pids"]
        time.sleep(0.1)
    raise TimeoutError("relays did not start within the test timeout")


def test_stop_rejects_when_no_job_is_running():
    resp = client.post("/api/stop")
    assert resp.status_code == 409


def test_stop_kills_relay_processes_and_ends_the_job():
    # Long enough, and with low throughput, that a stop requested right
    # after relays come up reliably lands mid-run rather than racing a
    # natural finish.
    yaml_text = TOR_LIKE.format(name="dashboard-stop", seed=1).replace(
        "duration_s: 1.0", "duration_s: 20.0").replace(
        "count: 2", "count: 20").replace("real_rate: 4", "real_rate: 1")
    resp = client.post("/api/run", json={"yaml_text": yaml_text})
    assert resp.status_code == 200
    pids = _wait_for_relay_pids()

    stop = client.post("/api/stop")
    assert stop.status_code == 200
    assert pids and set(stop.json()["pids_signalled"]) == set(pids)

    status = _wait_for_result(timeout=15.0)
    assert status["stopped"] is True
    assert status["error"] is None
    # Either shape is a clean stop: the generic stopped payload, or (when
    # killing the relays just made every session fail) a normal run result.
    assert status["result"].get("stopped") is True or "metrics" in status["result"]
    assert "has_output" in status["result"]

    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        alive = []
        for pid in pids:
            try:
                os.kill(pid, 0)
                alive.append(pid)
            except ProcessLookupError:
                pass
        if not alive:
            break
        time.sleep(0.1)
    assert not alive, f"relay process(es) {alive} still alive after stop"


def test_stop_of_a_sweep_keeps_finished_points():
    yaml_text = TOR_LIKE.format(name="dashboard-stop-sweep", seed=1).replace(
        "duration_s: 1.0", "duration_s: 15.0").replace("real_rate: 4", "real_rate: 1")
    resp = client.post("/api/sweep", json={
        "source": {"yaml_text": yaml_text}, "param": "real_rate", "values": [1, 2, 3, 4, 5],
    })
    assert resp.status_code == 200
    _wait_for_relay_pids()

    stop = client.post("/api/stop")
    assert stop.status_code == 200

    status = _wait_for_result(timeout=20.0)
    assert status["stopped"] is True
    assert status["error"] is None
    assert status["result"]["stopped"] is True

    # How far point 0 got before its relays died is a race, so the test
    # reads the server's own on-disk answer instead of assuming one: when a
    # point finished, sweep.csv holds it; when none did, there is no
    # sweep.csv, so the directory isn't classified as a sweep at all.
    detail = client.get("/api/outputs/dashboard-stop-sweep_sweep_real_rate").json()
    assert len(detail.get("rows", [])) < 5  # stopped before every value ran
    if detail.get("kind") == "sweep":
        assert detail["rows"], "a sweep.csv was written, so it should hold the finished points"


def test_predict_from_yaml_without_running():
    resp = client.post("/api/predict", json={"yaml_text": TOR_LIKE.format(name="dashboard-predict", seed=1)})
    assert resp.status_code == 200
    assert "model_observed_share" in resp.json()["predictions"]
    assert resp.json()["measured"] is None


def test_sweep_runs_each_value_and_writes_points():
    yaml_text = TOR_LIKE.format(name="dashboard-sweep-base", seed=1)
    resp = client.post("/api/sweep", json={"source": {"yaml_text": yaml_text}, "param": "real_rate", "values": [2, 4]})
    assert resp.status_code == 200
    status = _wait_for_result()
    assert status["error"] is None
    assert status["result"]["points"] == 2

    detail = client.get("/api/outputs/dashboard-sweep-base_sweep_real_rate").json()
    assert detail["kind"] == "sweep"
    assert len(detail["rows"]) == 2
    assert len(detail["points"]) == 2


def test_sweep_rejects_unknown_parameter():
    yaml_text = TOR_LIKE.format(name="dashboard-sweep-bad", seed=1)
    resp = client.post("/api/sweep", json={"source": {"yaml_text": yaml_text}, "param": "not_a_field", "values": [1]})
    assert resp.status_code == 400


def test_paired_classifies_an_identical_pair_as_no_meaningful_effect():
    yaml_text = TOR_LIKE.format(name="dashboard-paired-base", seed=1)
    resp = client.post("/api/paired", json={
        "reference": {"yaml_text": yaml_text}, "treatment": {"yaml_text": yaml_text},
        "seeds": [1, 2, 3], "metric": "delivery_rate", "margin": 0.2,
    })
    assert resp.status_code == 200
    status = _wait_for_result()
    assert status["error"] is None
    assert status["result"]["classification"] == "no_meaningful_effect"

    detail = client.get("/api/outputs/dashboard-paired-base_vs_dashboard-paired-base_paired").json()
    assert detail["kind"] == "paired"
    assert len(detail["rows"]) == 3


def test_fidelity_reports_pass_or_fail():
    yaml_text = TOR_LIKE.format(name="dashboard-fidelity", seed=1)
    resp = client.post("/api/fidelity", json={"source": {"yaml_text": yaml_text}, "limit_fraction": 0.5})
    assert resp.status_code == 200
    status = _wait_for_result()
    assert status["error"] is None
    assert isinstance(status["result"]["passes"], bool)

    detail = client.get("/api/outputs/dashboard-fidelity_fidelity").json()
    assert detail["kind"] == "fidelity"
    assert "passes" in detail["summary"]
