"""Backend contract tests for editable and newly appended flow steps."""

from pathlib import Path

import pytest
import yaml

from api_chain_runner.runner import ChainRunner
from api_chain_runner.ui import server


def write_flow(directory: Path) -> Path:
    flow = directory / "steps.yaml"
    flow.write_text(
        yaml.safe_dump(
            {
                "variables": {"token": "secret"},
                "chain": [
                    {
                        "name": "first",
                        "url": "https://example.test/first",
                        "method": "GET",
                        "headers": {"X-Test": "yes"},
                    },
                    {
                        "name": "second",
                        "url": "https://example.test/second",
                        "method": "POST",
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return flow


def client_for(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_flow_dir", str(tmp_path))
    return server.app.test_client()


def test_rename_preserves_other_fields(tmp_path, monkeypatch):
    flow = write_flow(tmp_path)
    response = client_for(tmp_path, monkeypatch).post(
        "/api/flow/steps.yaml/step/0", json={"updates": {"name": "renamed"}}
    )

    assert response.status_code == 200
    stored = yaml.safe_load(flow.read_text(encoding="utf-8"))
    assert stored["variables"] == {"token": "secret"}
    assert stored["chain"][0]["name"] == "renamed"
    assert stored["chain"][0]["headers"] == {"X-Test": "yes"}
    assert ChainRunner(str(flow)).steps[0].name == "renamed"


def test_invalid_rename_does_not_write(tmp_path, monkeypatch):
    flow = write_flow(tmp_path)
    before = flow.read_text(encoding="utf-8")
    client = client_for(tmp_path, monkeypatch)

    for name in ("", "second"):
        response = client.post(
            "/api/flow/steps.yaml/step/0", json={"updates": {"name": name}}
        )
        assert 400 <= response.status_code < 500
        assert flow.read_text(encoding="utf-8") == before


def test_append_api_step_validates_and_preserves_flow_metadata(tmp_path, monkeypatch):
    flow = write_flow(tmp_path)
    response = client_for(tmp_path, monkeypatch).post(
        "/api/flow/steps.yaml/step",
        json={
            "step": {
                "name": "third",
                "url": "https://example.test/third",
                "method": "PATCH",
                "headers": {"Content-Type": "application/json"},
            }
        },
    )

    assert response.status_code == 200
    stored = yaml.safe_load(flow.read_text(encoding="utf-8"))
    assert stored["variables"] == {"token": "secret"}
    assert [step["name"] for step in stored["chain"]] == ["first", "second", "third"]
    assert ChainRunner(str(flow)).steps[-1].method == "PATCH"


def test_append_manual_step_is_supported(tmp_path, monkeypatch):
    flow = write_flow(tmp_path)
    response = client_for(tmp_path, monkeypatch).post(
        "/api/flow/steps.yaml/step",
        json={
            "step": {
                "name": "manual-check",
                "manual": True,
                "instruction": "Verify the result manually",
            }
        },
    )

    assert response.status_code == 200
    assert yaml.safe_load(flow.read_text(encoding="utf-8"))["chain"][-1]["manual"] is True
    assert ChainRunner(str(flow)).steps[-1].manual is True


def test_invalid_append_does_not_write(tmp_path, monkeypatch):
    flow = write_flow(tmp_path)
    before = flow.read_text(encoding="utf-8")
    response = client_for(tmp_path, monkeypatch).post(
        "/api/flow/steps.yaml/step",
        json={"step": {"name": "first", "url": "", "method": "INVALID"}},
    )

    assert 400 <= response.status_code < 500
    assert flow.read_text(encoding="utf-8") == before


def test_append_allows_non_name_step_values_without_schema_validation(tmp_path, monkeypatch):
    flow = write_flow(tmp_path)
    response = client_for(tmp_path, monkeypatch).post(
        "/api/flow/steps.yaml/step",
        json={"step": {"name": "loose-step", "url": "", "method": "INVALID", "polling": False}},
    )

    assert response.status_code == 200
    stored = yaml.safe_load(flow.read_text(encoding="utf-8"))
    assert stored["chain"][-1]["polling"] is False


def test_parse_ignores_non_mapping_polling_for_editor_display(tmp_path):
    flow = tmp_path / "malformed-polling.yaml"
    flow.write_text(
        yaml.safe_dump({"chain": [{"name": "json-response-2", "url": "", "method": "GET", "polling": False}]}),
        encoding="utf-8",
    )

    parsed = server._parse_chain(str(flow))["steps"][0]
    assert parsed["has_polling"] is False
    assert "polling" not in parsed


def test_delete_step_preserves_remaining_flow_metadata(tmp_path, monkeypatch):
    flow = write_flow(tmp_path)
    response = client_for(tmp_path, monkeypatch).delete("/api/flow/steps.yaml/step/0")

    assert response.status_code == 200
    stored = yaml.safe_load(flow.read_text(encoding="utf-8"))
    assert stored["variables"] == {"token": "secret"}
    assert [step["name"] for step in stored["chain"]] == ["second"]


def test_delete_last_step_is_rejected_without_writing(tmp_path, monkeypatch):
    flow = write_flow(tmp_path)
    client = client_for(tmp_path, monkeypatch)
    client.delete("/api/flow/steps.yaml/step/0")
    before = flow.read_text(encoding="utf-8")

    response = client.delete("/api/flow/steps.yaml/step/0")

    assert 400 <= response.status_code < 500
    assert flow.read_text(encoding="utf-8") == before


def test_delete_uses_in_app_confirmation_popup():
    root = Path(__file__).resolve().parents[1]
    template = (root / "api_chain_runner/ui/templates/flow.html").read_text(encoding="utf-8")
    script = (root / "api_chain_runner/ui/static/flow.js").read_text(encoding="utf-8")

    assert 'id="delete-confirm-modal"' in template
    assert 'id="delete-confirm-ok"' in template
    assert "window.confirm" not in script
    assert "deleteConfirmModal.classList.remove(\"hidden\")" in script
    assert "method: \"DELETE\"" in script


@pytest.mark.parametrize(
    "position, expected",
    [(0, ["new", "first", "second"]), (1, ["first", "new", "second"]), (2, ["first", "second", "new"]), (None, ["first", "second", "new"])],
)
def test_insert_step_at_position(tmp_path, monkeypatch, position, expected):
    flow = write_flow(tmp_path)
    response = client_for(tmp_path, monkeypatch).post(
        "/api/flow/steps.yaml/step",
        json={"step": {"name": "new", "url": "https://example.test/new", "method": "GET"}, "position": position},
    )
    assert response.status_code == 200
    stored = yaml.safe_load(flow.read_text(encoding="utf-8"))
    assert [step["name"] for step in stored["chain"]] == expected


@pytest.mark.parametrize("position", [-1, 3, "1", True, 1.5])
def test_insert_step_rejects_invalid_position(tmp_path, monkeypatch, position):
    flow = write_flow(tmp_path)
    before = flow.read_text(encoding="utf-8")
    response = client_for(tmp_path, monkeypatch).post(
        "/api/flow/steps.yaml/step",
        json={"step": {"name": "new", "url": "https://example.test/new", "method": "GET"}, "position": position},
    )
    assert response.status_code == 400
    assert flow.read_text(encoding="utf-8") == before


def test_add_step_button_is_per_card_and_hover_revealed():
    root = Path(__file__).resolve().parents[1] / "api_chain_runner/ui"
    js = (root / "static/flow.js").read_text(encoding="utf-8")
    css = (root / "static/style.css").read_text(encoding="utf-8")
    html = (root / "templates/flow.html").read_text(encoding="utf-8")
    assert 'id="add-step-btn"' not in html
    assert "buildInsertButton(i + 1" in js and "position: insertPosition" in js
    assert ".step-node:hover > .insert-step-btn" in css


def test_manual_step_without_instruction_is_rejected_without_writing(tmp_path, monkeypatch):
    flow = write_flow(tmp_path)
    before = flow.read_text(encoding="utf-8")
    response = client_for(tmp_path, monkeypatch).post(
        "/api/flow/steps.yaml/step", json={"step": {"name": "check", "manual": True, "instruction": "  "}}
    )
    assert response.status_code == 400
    assert flow.read_text(encoding="utf-8") == before


def test_manual_step_can_be_inserted_mid_flow_and_the_flow_still_loads(tmp_path, monkeypatch):
    flow = write_flow(tmp_path)
    response = client_for(tmp_path, monkeypatch).post(
        "/api/flow/steps.yaml/step",
        json={
            "step": {"name": "approve", "manual": True, "instruction": "Check the dashboard", "print_ref": ["first.id"],
                     "delay": 0, "continue_on_error": True},
            "position": 1,
        },
    )
    assert response.status_code == 200
    steps = ChainRunner(str(flow)).steps
    assert [s.name for s in steps] == ["first", "approve", "second"] and steps[1].manual is True


def test_new_step_drawer_offers_manual_type():
    js = (Path(__file__).resolve().parents[1] / "api_chain_runner/ui/static/flow.js").read_text(encoding="utf-8")
    assert 'id="new-step-type"' in js and 'data-type="manual"' in js
    assert "updates.manual = true" in js and "blankStep(wantManual" in js
