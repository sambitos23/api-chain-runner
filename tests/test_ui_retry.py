"""Retry of a failed stop-on-fail step in the UI server."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from api_chain_runner.executor import StepExecutor
from api_chain_runner.models import StepResult
from api_chain_runner.ui import server

ROOT = Path(__file__).resolve().parents[1]
FLOW_JS = (ROOT / "api_chain_runner/ui/static/flow.js").read_text(encoding="utf-8")
STYLE_CSS = (ROOT / "api_chain_runner/ui/static/style.css").read_text(encoding="utf-8")
ICONS_HTML = (ROOT / "api_chain_runner/ui/templates/icons.html").read_text(encoding="utf-8")

CHAIN = """
chain:
  - name: first
    url: http://example.test/first
    method: GET
  - name: second
    url: http://example.test/second
    method: GET
    continue_on_error: false
  - name: third
    url: http://example.test/third
    method: GET
"""


@pytest.fixture
def client(tmp_path, monkeypatch):
    (tmp_path / "flow.yaml").write_text(CHAIN, encoding="utf-8")
    monkeypatch.setattr(server, "_flow_dir", str(tmp_path))
    server._active_runs.clear()
    server._retry_contexts.clear()
    return server.app.test_client()


def _wait_for(client, run_id, statuses, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = client.get(f"/api/run/{run_id}").get_json()
        if data["status"] in statuses:
            return data
        time.sleep(0.02)
    raise AssertionError(f"run never reached {statuses}: {data}")


def _patch_execute(monkeypatch, fail_second_times, calls, raise_error=False):
    state = {"fails": fail_second_times}

    def execute(self, step):
        calls.append(step.name)
        if step.name == "second" and state["fails"] > 0:
            state["fails"] -= 1
            if raise_error:
                raise RuntimeError("boom")
            return StepResult(step.name, 404, "nope", 1.0, False, "HTTP 404")
        return StepResult(step.name, 200, {"ok": True}, 1.0, True)

    monkeypatch.setattr(StepExecutor, "execute", execute)


@pytest.mark.parametrize("raise_error", [False, True])
def test_failed_stop_on_fail_step_is_retryable_and_resumes(client, monkeypatch, raise_error):
    calls: list[str] = []
    _patch_execute(monkeypatch, 1, calls, raise_error)

    run_id = client.post("/api/run", json={"flow_path": "flow.yaml"}).get_json()["run_id"]
    data = _wait_for(client, run_id, {"aborted"})
    assert data["retryable"] is True
    assert data["failed_step_index"] == 1
    assert [r["step_name"] for r in data["results"]] == ["first", "second", "third"]
    assert calls == ["first", "second"]

    assert client.post(f"/api/run/{run_id}/retry").status_code == 200
    data = _wait_for(client, run_id, {"completed"})
    # first is not re-run; second is retried; third then runs.
    assert calls == ["first", "second", "second", "third"]
    assert [r["success"] for r in data["results"]] == [True, True, True]
    assert data["retryable"] is False
    assert run_id not in server._retry_contexts


def test_retry_can_fail_again_and_be_retried_again(client, monkeypatch):
    calls: list[str] = []
    _patch_execute(monkeypatch, 2, calls)
    run_id = client.post("/api/run", json={"flow_path": "flow.yaml"}).get_json()["run_id"]
    _wait_for(client, run_id, {"aborted"})
    client.post(f"/api/run/{run_id}/retry")
    data = _wait_for(client, run_id, {"aborted", "completed"})
    # Wait for the second abort (status flips to running first).
    while data["status"] != "aborted":
        data = _wait_for(client, run_id, {"aborted", "completed"})
    assert data["retryable"] is True
    assert len(data["results"]) == 3
    client.post(f"/api/run/{run_id}/retry")
    _wait_for(client, run_id, {"completed"})
    assert calls == ["first", "second", "second", "second", "third"]


def test_retry_rejected_when_not_aborted(client, monkeypatch):
    calls: list[str] = []
    _patch_execute(monkeypatch, 0, calls)
    run_id = client.post("/api/run", json={"flow_path": "flow.yaml"}).get_json()["run_id"]
    _wait_for(client, run_id, {"completed"})
    assert client.post(f"/api/run/{run_id}/retry").status_code == 404
    assert client.post("/api/run/missing/retry").status_code == 404


def test_second_retry_click_is_rejected(client, monkeypatch):
    calls: list[str] = []
    _patch_execute(monkeypatch, 1, calls)
    run_id = client.post("/api/run", json={"flow_path": "flow.yaml"}).get_json()["run_id"]
    _wait_for(client, run_id, {"aborted"})
    assert client.post(f"/api/run/{run_id}/retry").status_code == 200
    assert client.post(f"/api/run/{run_id}/retry").status_code in (400, 404)


def test_ui_declares_retry_button_for_both_themes():
    assert "buildRetryConnector" in FLOW_JS
    assert "/retry" in FLOW_JS
    assert 'id="i-retry"' in ICONS_HTML
    assert ".retry-btn" in STYLE_CSS
    # Colours come from theme variables, so one rule set serves light and dark.
    assert "var(--orange)" in STYLE_CSS.split("Retry (failed stop-on-fail step)")[1]
