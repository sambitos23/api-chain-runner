"""Run only Ctrl/Cmd+click selected steps, with per-run payload/query values."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from api_chain_runner.executor import StepExecutor
from api_chain_runner.models import StepResult
from api_chain_runner.ui import server

ROOT = Path(__file__).resolve().parents[1] / "api_chain_runner/ui"
FLOW_JS = (ROOT / "static/flow.js").read_text(encoding="utf-8")
STYLE_CSS = (ROOT / "static/style.css").read_text(encoding="utf-8")

CHAIN = """
chain:
  - name: login
    url: http://example.test/login
    method: POST
    payload:
      user: admin
  - name: search
    url: http://example.test/search?q=old&page=1&tag=a&tag=b#frag
    method: POST
    payload:
      filter:
        age: 5
        active: false
        name: old
      ids: [1, 2]
  - name: report
    url: http://example.test/report
    method: GET
    condition:
      step: login
      key_path: ok
      expected_value: "True"
  - name: last
    url: http://example.test/last
    method: GET
"""


@pytest.fixture
def client(tmp_path, monkeypatch):
    (tmp_path / "flow.yaml").write_text(CHAIN, encoding="utf-8")
    monkeypatch.setattr(server, "_flow_dir", str(tmp_path))
    server._active_runs.clear()
    server._retry_contexts.clear()
    return server.app.test_client()


@pytest.fixture
def executed(monkeypatch):
    seen: list = []

    def execute(self, step):
        seen.append(step)
        return StepResult(step.name, 200, {"ok": True}, 1.0, True)

    monkeypatch.setattr(StepExecutor, "execute", execute)
    return seen


def _finish(client, run_id, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = client.get(f"/api/run/{run_id}").get_json()
        if data["status"] != "running":
            return data
        time.sleep(0.02)
    raise AssertionError("run did not finish")


def _run(client, **body):
    res = client.post("/api/run", json={"flow_path": "flow.yaml", **body})
    assert res.status_code == 200, res.get_json()
    return _finish(client, res.get_json()["run_id"])


def test_only_selected_steps_run_and_results_stay_aligned(client, executed):
    data = _run(client, steps=[1, 3])
    assert [s.name for s in executed] == ["search", "last"]
    assert [r["step_name"] for r in data["results"]] == ["login", "search", "report", "last"]
    assert [bool(r.get("not_selected")) for r in data["results"]] == [True, False, True, False]
    assert data["status"] == "completed"
    assert all(r["success"] for r in data["results"])


def test_overrides_patch_query_and_payload_with_original_types(client, executed):
    overrides = {
        "1": {
            "query": [{"index": 0, "value": "new value&x"}, {"index": 3, "value": "z"}],
            "payload": [
                {"path": ["filter", "age"], "value": "42"},
                {"path": ["filter", "active"], "value": "true"},
                {"path": ["filter", "name"], "value": "new"},
                {"path": ["ids", 1], "value": "9"},
            ],
        }
    }
    _run(client, steps=[1], overrides=overrides)
    (step,) = executed
    assert step.url == "http://example.test/search?q=new%20value%26x&page=1&tag=a&tag=z#frag"
    assert step.payload == {"filter": {"age": 42, "active": True, "name": "new"}, "ids": [1, 9]}
    # The flow file itself is untouched.
    assert "q=old" in (Path(server._flow_dir) / "flow.yaml").read_text(encoding="utf-8")


def test_condition_on_unselected_step_does_not_silently_skip(client, executed):
    _run(client, steps=[2])
    assert [s.name for s in executed] == ["report"]


def test_full_run_still_skips_when_condition_step_has_no_stored_response(client, executed):
    # The stubbed executor stores nothing, so "login" has no response and "report" is skipped.
    # Only runs with an explicit selection bypass that skip.
    _run(client)
    assert [s.name for s in executed] == ["login", "search", "last"]


@pytest.mark.parametrize("steps", [[], "1", [True], [-1], [1.5]])
def test_invalid_selection_is_rejected(client, executed, steps):
    res = client.post("/api/run", json={"flow_path": "flow.yaml", "steps": steps})
    assert res.status_code == 400


def test_out_of_range_selection_and_bad_override_fail_the_run(client, executed):
    assert _run(client, steps=[99])["status"] == "error"
    bad = {"1": {"payload": [{"path": ["nope"], "value": "x"}]}}
    assert _run(client, steps=[1], overrides=bad)["status"] == "error"
    assert executed == []


def test_failed_selected_step_can_be_retried_within_selection(client, monkeypatch):
    (Path(server._flow_dir) / "flow.yaml").write_text(
        CHAIN.replace("name: last\n    url: http://example.test/last\n    method: GET",
                      "name: last\n    url: http://example.test/last\n    method: GET\n    continue_on_error: false"),
        encoding="utf-8",
    )
    calls: list[str] = []
    fails = {"n": 1}

    def execute(self, step):
        calls.append(step.name)
        if step.name == "last" and fails["n"]:
            fails["n"] -= 1
            return StepResult(step.name, 500, "x", 1.0, False, "HTTP 500")
        return StepResult(step.name, 200, {}, 1.0, True)

    monkeypatch.setattr(StepExecutor, "execute", execute)
    data = _run(client, steps=[1, 3])
    assert data["status"] == "aborted" and data["failed_step_index"] == 3
    run_id = next(iter(server._retry_contexts))
    assert client.post(f"/api/run/{run_id}/retry").status_code == 200
    data = _finish(client, run_id)
    assert data["status"] == "completed"
    assert calls == ["search", "last", "last"]


def test_ui_wiring_for_selection_and_values_popup():
    assert "e.ctrlKey || e.metaKey" in FLOW_JS
    assert '"contextmenu"' in FLOW_JS  # macOS reports Ctrl+click as a context menu
    assert "function openRunInputs()" in FLOW_JS
    assert "startRun({ steps: order, overrides })" in FLOW_JS
    assert ".step-box.is-selected" in STYLE_CSS
    assert "var(--accent)" in STYLE_CSS.split("Step selection + run-values popup")[1]


def test_sidebar_lists_steps_and_keeps_documentation_link():
    html = (ROOT / "templates/flow.html").read_text(encoding="utf-8")
    icons = (ROOT / "templates/icons.html").read_text(encoding="utf-8")
    sidebar = html.split("</aside>")[0]
    header = html.split("</aside>")[1].split('class="page-content')[0]
    assert 'href="/flow/{{ flow_path }}/docs" class="nav-item"' in sidebar
    assert "/docs" not in header
    assert 'id="sidebar-steps"' in sidebar
    assert 'id="i-sun"' in icons and 'id="i-moon"' in icons
    assert ".nav-step.active" in STYLE_CSS
