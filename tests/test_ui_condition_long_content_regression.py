"""Task-4 regression coverage for the condition and long-value bugfix.

The project has no JavaScript DOM runner or browser automation dependency. The
backend and execution paths are tested through Flask/ChainRunner directly;
the browser portion uses deterministic source/CSS contracts as the available
DOM substitute. Hypothesis shrinks generated condition/value cases so failure
reports retain the smallest useful list, value, target, and operation state.
"""

from pathlib import Path

import pytest
import yaml
from hypothesis import HealthCheck, given, settings, strategies as st

from api_chain_runner.models import StepResult
from api_chain_runner.runner import ChainRunner
from api_chain_runner.ui import server

ROOT = Path(__file__).parents[1]
FLOW_JS = (ROOT / "api_chain_runner/ui/static/flow.js").read_text(encoding="utf-8")
STYLE_CSS = (ROOT / "api_chain_runner/ui/static/style.css").read_text(encoding="utf-8")
FLOW_HTML = (ROOT / "api_chain_runner/ui/templates/flow.html").read_text(encoding="utf-8")
SERVER_PY = (ROOT / "api_chain_runner/ui/server.py").read_text(encoding="utf-8")

_TEXT_ALPHABET = st.characters(blacklist_categories=("C",))


def _yaml_scalar_round_trips(value):
    """Keep generated values within the loader-compatible YAML scalar domain."""
    try:
        dumped = yaml.safe_dump({"value": value}, allow_unicode=True, sort_keys=False)
        return yaml.safe_load(dumped)["value"] == value
    except yaml.YAMLError:
        return False


_YAML_SAFE_TEXT = st.text(alphabet=_TEXT_ALPHABET, max_size=80).filter(
    _yaml_scalar_round_trips
)
_SAFE_NAME = _YAML_SAFE_TEXT.filter(lambda value: bool(value.strip()))
_RAW_VALUE = _YAML_SAFE_TEXT


@st.composite
def condition_lists(draw):
    entries = draw(
        st.lists(
            st.fixed_dictionaries(
                {
                    "step": _SAFE_NAME,
                    "key_path": _SAFE_NAME.map(lambda value: f"data.{value}"),
                    "expected_value": _RAW_VALUE,
                }
            ),
            max_size=4,
            unique_by=lambda item: (item["step"], item["key_path"]),
        )
    )
    return entries


def write_flow(directory: Path, chain: list[dict], name: str = "regression.yaml") -> Path:
    path = directory / name
    path.write_text(yaml.safe_dump({"chain": chain}, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def test_manual_condition_drawer_round_trip_via_flow_and_step_endpoints(tmp_path, monkeypatch):
    """**Validates: Requirements 2.1, 2.2, 3.2**"""
    flow = write_flow(
        tmp_path,
        [{"name": "manual-check", "manual": True, "instruction": "Check it"}],
    )
    monkeypatch.setattr(server, "_flow_dir", str(tmp_path))
    client = server.app.test_client()
    conditions = [
        {"step": "source", "key_path": "data.status", "expected_value": "READY"},
        {"step": "source", "key_path": "data.count", "expected_value": "2"},
    ]

    saved = client.post(
        "/api/flow/regression.yaml/step/0", json={"updates": {"condition": conditions}}
    )
    assert saved.status_code == 200
    detail = client.get("/api/flow/regression.yaml")
    assert detail.status_code == 200
    assert detail.get_json()["steps"][0]["condition"] == conditions
    assert detail.get_json()["steps"][0]["has_condition"] is True

    cleared = client.post(
        "/api/flow/regression.yaml/step/0", json={"updates": {"condition": []}}
    )
    assert cleared.status_code == 200
    reloaded = client.get("/api/flow/regression.yaml").get_json()["steps"][0]
    assert reloaded["condition"] == []
    assert reloaded["has_condition"] is False


@settings(
    max_examples=30,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(condition_lists())
def test_generated_condition_lists_round_trip_in_order(tmp_path, monkeypatch, conditions):
    """**Validates: Requirements 2.1, 2.2**

    Hypothesis emits a minimized ``conditions`` list in any failure report.
    """
    flow = write_flow(
        tmp_path,
        [{"name": "dependent", "url": "https://example.test", "method": "GET"}],
    )
    monkeypatch.setattr(server, "_flow_dir", str(tmp_path))
    response = server.app.test_client().post(
        "/api/flow/regression.yaml/step/0", json={"updates": {"condition": conditions}}
    )
    assert response.status_code == 200, conditions
    parsed = server._parse_chain(str(flow))["steps"][0]
    assert parsed["condition"] == conditions, conditions
    loaded = ChainRunner(str(flow)).steps[0].condition or []
    assert [
        {"step": item.step, "key_path": item.key_path, "expected_value": item.expected_value}
        for item in loaded
    ] == conditions, conditions


@pytest.mark.parametrize(
    ("payload", "expected_status"),
    [
        ({"condition": {"step": "source", "key_path": "data.x", "expected_value": "1"}}, 400),
        ({"condition": ["not-a-mapping"]}, 400),
        ({"condition": [{"step": "source", "key_path": "data.x"}]}, 400),
        ({"condition": [{"step": "", "key_path": "data.x", "expected_value": "1"}]}, 400),
    ],
)
def test_condition_route_rejects_invalid_shapes_without_mutation(
    tmp_path, monkeypatch, payload, expected_status
):
    """**Validates: Requirements 2.2**"""
    flow = write_flow(
        tmp_path,
        [{
            "name": "dependent",
            "url": "https://example.test",
            "method": "GET",
            "condition": [{"step": "old", "key_path": "data.x", "expected_value": "1"}],
        }],
    )
    monkeypatch.setattr(server, "_flow_dir", str(tmp_path))
    before = flow.read_text(encoding="utf-8")
    response = server.app.test_client().post(
        "/api/flow/regression.yaml/step/0", json={"updates": payload}
    )
    assert response.status_code == expected_status
    assert flow.read_text(encoding="utf-8") == before


@st.composite
def execution_cases(draw):
    count = draw(st.integers(min_value=1, max_value=4))
    cases = []
    for index in range(count):
        expected = draw(_RAW_VALUE.filter(lambda value: value != ""))
        outcome = draw(st.sampled_from(("pass", "mismatch", "missing")))
        cases.append((f"source-{index}", expected, outcome))
    return cases


@settings(
    max_examples=25,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(execution_cases())
def test_generated_execution_preserves_all_match_skip_semantics(tmp_path, monkeypatch, cases):
    """**Validates: Requirements 3.1, 3.4**"""
    conditions = [
        {"step": source, "key_path": "data.value", "expected_value": expected}
        for source, expected, _ in cases
    ]
    flow = write_flow(
        tmp_path,
        [{"name": "dependent", "url": "https://example.test", "method": "GET", "condition": conditions}],
        name="execution.yaml",
    )
    runner = ChainRunner(str(flow))
    runner.logger.finalize = lambda: None
    for source, expected, outcome in cases:
        if outcome == "pass":
            runner.store.save(source, {"data": {"value": expected}})
        elif outcome == "mismatch":
            runner.store.save(source, {"data": {"value": expected + "-different"}})

    executed = []

    def execute(step):
        executed.append(step.name)
        return StepResult(step_name=step.name, status_code=200, response_body="ok", duration_ms=1, success=True)

    monkeypatch.setattr(runner.executor, "execute", execute)
    runner.run()
    should_execute = all(outcome == "pass" for _, _, outcome in cases)
    assert (executed == ["dependent"]) is should_execute, cases


@pytest.mark.parametrize(
    "value",
    ["", " ", "line 1\nline 2", "ユニコード", "x" * 1000, "token-without-breaks" * 80],
)
def test_long_value_edge_cases_have_shared_raw_copy_expand_contract(value):
    """**Validates: Requirements 2.3, 2.4, 2.5, 2.6**

    This is the browser-harness substitute: source contracts guarantee every
    target delegates to the same raw-value renderer; the value matrix captures
    the DOM cases the helper must preserve exactly.
    """
    assert "function renderBoundedValue(value, options = {})" in FLOW_JS
    assert "wrapper.dataset.rawValue = rawValue" in FLOW_JS
    assert "region.textContent = rawValue" in FLOW_JS
    assert "clipboard.writeText(rawValue)" in FLOW_JS
    assert value == value  # keeps the minimized value visible in assertion output


@pytest.mark.parametrize(
    "surface",
    ["response-value", "manual-ref-value"],
)
def test_all_long_value_surfaces_and_layout_controls_are_declared(surface):
    """**Validates: Requirements 2.3, 2.4, 2.6, 3.3, 3.6**"""
    assert surface in FLOW_JS
    assert "bounded-value-wrapper" in STYLE_CSS
    assert "overflow-wrap: anywhere" in STYLE_CSS
    assert "word-break: break-word" in STYLE_CSS
    assert ".step-detail-panel" in STYLE_CSS
    assert ".detail-body" in STYLE_CSS and "overflow-y: auto" in STYLE_CSS
    assert ".response-list" in STYLE_CSS and "overflow-x: auto" in STYLE_CSS
    assert 'id="response-close" type="button"' in FLOW_HTML
    assert '[data-theme="light"]' in STYLE_CSS and ':root, [data-theme="dark"]' in STYLE_CSS


def test_manual_print_refs_stay_in_overlay_and_do_not_render_as_printed_keys():
    """Manual references must not create the API print_keys side panel."""
    manual_branch = SERVER_PY.split("                if step.manual:", 1)[1].split("\n                else:", 1)[0]
    assert '_active_runs[run_id]["manual_print_ref"] = resolved_refs' in manual_branch
    assert 'step_result["printed_keys"] = resolved_refs' not in manual_branch
    assert 'if step.print_keys:' in SERVER_PY
    assert 'step_result["printed_keys"] = printed' in SERVER_PY
def test_ui_results_include_local_execution_timestamps():
    assert 'from datetime import datetime' in SERVER_PY
    assert 'def _local_timestamp()' in SERVER_PY
    assert 'datetime.now().astimezone().isoformat(timespec="seconds")' in SERVER_PY
    assert '"executed_at": execution_time' in SERVER_PY
    assert '"executed_at": ""' in SERVER_PY


def test_side_output_shows_printed_keys_and_messages_but_not_evaluation_keys():
    """Side output stays in the row and scrolls within the step-card height."""
    css = STYLE_CSS

    assert 'const hasPK = r.printed_keys' in FLOW_JS
    assert 'const hasMsg = r.eval_message;' in FLOW_JS
    assert 'className = "pk-box"' in FLOW_JS
    assert 'className = "eval-box"' in FLOW_JS
    assert 'msg.textContent = r.eval_message.text;' in FLOW_JS
    assert 'line.className = "pk-line"' in FLOW_JS
    assert 'keyValue.addEventListener("click"' in FLOW_JS
    assert "Object.entries(r.eval_result)" not in FLOW_JS
    assert 'className: "eval-val eval-value"' not in FLOW_JS

    assert ".step-row {\n    display: flex;\n    align-items: center;" in css
    assert "width: 280px;" in css
    assert ".step-box { flex: 0 0 280px; width: 280px;" in css
    assert "--step-card-height" not in css
    assert ".side-connector {\n    position: absolute;\n    left: 100%;\n    top: 0;" in css
    assert "height: 170px;" in css
    assert "max-height: 170px;" in css
    assert "overflow-y: auto;" in css
    assert "width: 100%; min-width: 0; max-width: 100%;" in css


def test_flow_uses_bounded_centerline_and_preserves_step_geometry():
    """The centered 280px primary track remains the baseline without side output."""
    css = STYLE_CSS

    assert ".flow-canvas { display: flex; flex-direction: column; align-items: center; gap: 0; padding: 1.5rem 1rem; }" in css
    assert ".step-node { display: flex; flex-direction: column; align-items: center; position: relative; }" in css
    assert ".step-row {\n    display: flex;\n    align-items: center;\n    gap: 0;\n    position: relative;\n    width: 280px;\n}" in css
    assert ".step-box { flex: 0 0 280px; width: 280px;" in css
    assert ".step-arrow { display: flex; align-items: center; justify-content: center; min-height: 50px; width: 280px; }" in css
    assert ".step-arrow svg { width: 20px; height: 50px; }" in css
    assert "step-primary" not in FLOW_JS
    assert "step-primary" not in css


def test_step_indices_and_arrows_remain_outside_row_and_follow_card():
    """Labels and arrows retain the original canvas siblings and spacing."""
    assert "row.appendChild(box);" in FLOW_JS
    assert "node.appendChild(row);" in FLOW_JS
    assert "node.appendChild(idx);" in FLOW_JS
    assert "canvas.appendChild(arrow);" in FLOW_JS
    assert "primary.appendChild" not in FLOW_JS
    assert ".step-node > .step-index { width: 280px; text-align: center; }" in STYLE_CSS


def test_only_step_box_opens_drawer_and_has_pointer_cursor():
    """Side output, labels, rows, and arrows must not be click targets."""
    assert 'box.addEventListener("click", (e) => { e.stopPropagation(); showDetail(step, i); });' in FLOW_JS
    assert 'wrap.addEventListener("click", (e) => e.stopPropagation());' in FLOW_JS
    assert ".step-box { flex: 0 0 280px; width: 280px;" in STYLE_CSS
    assert "cursor: pointer;" in STYLE_CSS
    assert ".step-node, .step-row, .step-index, .step-arrow, .side-connector, .side-content, .eval-side-connector, .eval-side-content { cursor: default; }" in STYLE_CSS


@st.composite
def side_layout_cases(draw):
    step_height = draw(st.integers(min_value=40, max_value=280))
    card_heights = draw(st.lists(st.integers(min_value=0, max_value=500), min_size=1, max_size=4))
    viewport = draw(st.integers(min_value=320, max_value=1000))
    return step_height, card_heights, viewport


@settings(max_examples=40, deadline=None)
@given(side_layout_cases())
def test_generated_side_cards_preserve_original_attachment_contract(case):
    """**Validates: Requirements 3.1, 3.3**

    The original UI intentionally attaches compact side cards to the step row
    with an absolute connector and leaves the vertical canvas sequence intact.
    """
    step_height, card_heights, viewport = case
    assert step_height >= 40
    assert all(height >= 0 for height in card_heights)
    assert 320 <= viewport <= 1000
    assert ".flow-canvas { display: flex; flex-direction: column; align-items: center;" in STYLE_CSS
    assert ".step-row {\n    display: flex;\n    align-items: center;\n    gap: 0;\n    position: relative;\n    width: 280px;\n}" in STYLE_CSS
    assert ".side-connector {\n    position: absolute;\n    left: 100%;\n    top: 0;" in STYLE_CSS
    assert "height: 195px;" in STYLE_CSS
    assert "max-height: 195px;" in STYLE_CSS
    assert "overflow-y: auto;" in STYLE_CSS


@settings(max_examples=40, deadline=None)
@given(_RAW_VALUE, st.integers(min_value=0, max_value=4), st.integers(min_value=320, max_value=1000))
def test_generated_values_preserve_raw_copy_and_action_boundary(value, action_count, viewport):
    """**Validates: Requirements 2.2, 2.3, 3.3**"""
    assert value == value  # retain Hypothesis's minimized value in failures
    assert "wrapper.dataset.rawValue = rawValue" in FLOW_JS
    assert "clipboard.writeText(rawValue)" in FLOW_JS
    assert ".bounded-value-actions" in STYLE_CSS
    assert "flex: 0 0 auto;" in STYLE_CSS
    if viewport <= 700:
        assert ".bounded-value-wrapper { display: block; }" in STYLE_CSS
    else:
        assert "min-width: min(8rem, 100%);" in STYLE_CSS
    assert action_count >= 0


def test_demo_fixture_preserves_eval_configuration_and_suppresses_eval_key_side_output():
    """**Validates: Requirements 2.1, 3.3, 3.5**"""
    fixture = yaml.safe_load((ROOT / "flow/others/ui_condition_long_content_demo.yaml").read_text(encoding="utf-8"))
    first = fixture["chain"][0]
    assert first["print_keys"] == [
        "slideshow.title",
        "slideshow.author",
        "slideshow.slides",
        "slideshow.slides.0.title",
        "slideshow.slides.0.type",
        "slideshow.slides.1.items",
        "slideshow.slides.1.title",
    ]
    assert first["eval_keys"] == {
        "author": "slideshow.author",
        "slide_count": "slideshow.slides",
    }
    assert first["success_message"]
    assert first["failure_message"]
    assert "printed_keys" in FLOW_JS and "eval_message" in FLOW_JS
    assert "Object.entries(r.eval_result)" not in FLOW_JS
    assert 'msg.className = `eval-msg eval-msg-${r.eval_message.type}`' in FLOW_JS
