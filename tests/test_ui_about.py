"""About popup and guided tour."""
from __future__ import annotations
from pathlib import Path
import pytest
from api_chain_runner.ui import server

UI = Path(__file__).resolve().parents[1] / "api_chain_runner/ui"
GITHUB = "https://github.com/sambitos23/api-chain-runner"
LINKEDIN = "https://www.linkedin.com/in/sambit-saha/"


@pytest.fixture
def client(tmp_path, monkeypatch):
    (tmp_path / "demo.yaml").write_text(
        "chain:\n  - name: a\n    url: http://x.test\n    method: GET\n")
    monkeypatch.setattr(server, "_flow_dir", str(tmp_path))
    return server.app.test_client()


def test_about_modal_has_creator_and_links():
    html = (UI / "templates/about_modal.html").read_text()
    assert "Sambit Saha" in html
    assert GITHUB in html and LINKEDIN in html
    assert html.count('rel="noopener noreferrer"') == 2
    assert 'id="about-tour-btn"' in html


@pytest.mark.parametrize("path", ["/", "/flow/demo.yaml", "/flow/demo.yaml/docs", "/flow/demo.yaml/editor"])
def test_every_page_includes_about(client, path):
    html = client.get(path).get_data(as_text=True)
    assert 'id="about-btn"' in html
    assert 'id="about-modal"' in html
    assert "about.js" in html


def test_tour_selectors_exist_in_templates():
    js = (UI / "static/about.js").read_text()
    templates = "".join(p.read_text() for p in (UI / "templates").glob("*.html"))
    flow_js = (UI / "static/flow.js").read_text()
    for ident in ("create-flow-btn", "flow-search", "edit-toggle-btn", "run-btn", "pause-btn",
                  "sidebar-steps", "response-panel", "edit-toggle", "save-btn", "doc-view",
                  "editor-save", "monaco-container", "theme-toggle", "env-btn", "about-btn"):
        assert f"#{ident}" in js
        assert f'id="{ident}"' in templates, ident
    assert "step-box" in flow_js


def test_help_button_is_floating_and_glows_first_time():
    css = (UI / "static/style.css").read_text()
    js = (UI / "static/about.js").read_text()
    assert ".help-fab { position: fixed;" in css
    assert ".help-fab.is-new" in css
    assert "acr-help-seen" in js
    assert 'id="about-btn"' not in (UI / "templates/env_button.html").read_text()


def test_guide_page(client):
    r = client.get("/about")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "Sambit Saha" in html
    assert GITHUB in html and LINKEDIN in html
    for anchor in ("overview", "quick-start", "step-options", "flow-page", "request-panel", "environment"):
        assert f'id="{anchor}"' in html and f'href="#{anchor}"' in html


def test_modal_links_to_guide():
    assert 'href="/about"' in (UI / "templates/about_modal.html").read_text()


def test_corner_radius_is_capped():
    import re
    css = (UI / "static/style.css").read_text()
    for value in re.findall(r"border-radius:\s*([^;}]*)", css):
        if value.strip() == "50%":
            continue  # true circles: dots, spinner, avatar
        for px in re.findall(r"(\d+(?:\.\d+)?)px", value):
            assert float(px) <= 6, value
        assert "999" not in value


def test_modal_credit_line():
    html = (UI / "templates/about_modal.html").read_text()
    assert "Made with" in html and "🧠" in html and "Sambit Saha" in html
    assert "Created by" not in html


def test_drawer_body_rows_follow_method_select():
    js = (UI / "static/flow.js").read_text()
    # Payload rows are always rendered and toggled by the Method select, not by the method at open time.
    assert 'id="method-body-rows"' in js
    assert "function wireMethodSelect()" in js
    assert 'select.addEventListener("change"' in js
    assert 'if (curMethod !== "GET" && curMethod !== "HEAD" && curMethod !== "OPTIONS") {' not in js


def test_drawer_has_query_params_editor():
    js = (UI / "static/flow.js").read_text()
    assert "function buildQueryParams(url)" in js and "wireQueryParams();" in js
    assert 'id="sec-query"' in js


def test_tour_drawer_anchors_exist():
    js = (UI / "static/flow.js").read_text()
    tour = (UI / "static/about.js").read_text()
    for anchor in ("sec-query", "sec-request-data", "sec-print", "sec-condition", "sec-polling"):
        assert f'id="{anchor}"' in js, anchor
        assert f"#{anchor}" in tour, anchor
