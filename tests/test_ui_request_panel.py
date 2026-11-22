"""Postman-style single request panel: POST /api/flow/<flow>/step/<n>/send."""
from __future__ import annotations

from pathlib import Path

import pytest
import requests

from api_chain_runner.ui import server

ROOT = Path(__file__).resolve().parents[1] / "api_chain_runner/ui"
FLOW_JS = (ROOT / "static/flow.js").read_text(encoding="utf-8")
FLOW_HTML = (ROOT / "templates/flow.html").read_text(encoding="utf-8")

CHAIN = """
variables:
  token: abc
chain:
  - name: login
    url: http://example.test/login
    method: POST
    payload: {user: admin}
  - name: profile
    url: http://example.test/me?id=${login.id}
    method: GET
    headers:
      Authorization: "Bearer ${login.token}"
      X-Var: "${vars.token}"
    retry: {max_attempts: 3, delay: 0, on: [5xx]}
    polling: {interval: 1, key_path: ready, expected_values: ["yes"]}
  - name: manual-step
    manual: true
    instruction: do it
"""


class FakeResponse:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code = status
        self._body = body
        self.headers = headers or {"Content-Type": "application/json"}
        self.text = str(body)

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


@pytest.fixture
def client(tmp_path, monkeypatch):
    (tmp_path / "flow.yaml").write_text(CHAIN, encoding="utf-8")
    monkeypatch.setattr(server, "_flow_dir", str(tmp_path))
    server._flow_stores.clear()
    return server.app.test_client()


@pytest.fixture
def sent(monkeypatch):
    calls = []

    def fake_request(**kwargs):
        calls.append(kwargs)
        return FakeResponse(200, {"id": 7, "token": "T"}, {"X-Test": "1"})

    monkeypatch.setattr("api_chain_runner.executor.requests.request", fake_request)
    return calls


def _send(client, index, **body):
    payload = {"method": "POST", "url": "http://example.test/login", "headers": {}, "body": ""}
    payload.update(body)
    return client.post(f"/api/flow/flow.yaml/step/{index}/send", json=payload)


def test_send_runs_exactly_one_request_with_edited_values(client, sent):
    res = _send(client, 0, url="http://example.test/login?x=1", headers={"X-A": "b"}, body='{"user": "me"}')
    data = res.get_json()
    assert res.status_code == 200
    assert len(sent) == 1
    assert sent[0]["method"] == "POST"
    assert sent[0]["url"] == "http://example.test/login?x=1"
    assert sent[0]["headers"] == {"X-A": "b"}
    assert sent[0]["json"] == {"user": "me"}
    assert data["status_code"] == 200 and data["success"] is True
    assert data["response_headers"] == {"X-Test": "1"}
    assert '"token": "T"' in data["response_body"]
    assert data["size_bytes"] > 0


def test_polling_and_retry_are_ignored_for_a_single_send(client, sent):
    res = _send(client, 1, method="GET", url="http://example.test/me?id=1", headers={"Authorization": "x"}, body="")
    assert res.status_code == 200
    assert len(sent) == 1


def test_unresolved_reference_reports_a_clear_error(client, sent):
    res = _send(client, 1, method="GET", url="http://example.test/me?id=${login.id}")
    assert res.status_code == 400
    assert res.get_json()["unresolved_reference"] is True
    assert sent == []


def test_references_resolve_from_earlier_sends_and_vars(client, sent):
    assert _send(client, 0).status_code == 200  # stores login response
    res = _send(
        client, 1, method="GET", url="http://example.test/me?id=${login.id}",
        headers={"Authorization": "Bearer ${login.token}", "X-Var": "${vars.token}"},
    )
    assert res.status_code == 200 and res.get_json()["context_used"] is True
    assert sent[-1]["url"] == "http://example.test/me?id=7"
    assert sent[-1]["headers"] == {"Authorization": "Bearer T", "X-Var": "abc"}


def test_connection_errors_come_back_as_a_result(client, monkeypatch):
    def boom(**kwargs):
        raise requests.ConnectionError("refused")

    monkeypatch.setattr("api_chain_runner.executor.requests.request", boom)
    data = _send(client, 0).get_json()
    assert data["status_code"] == -1 and data["success"] is False and "refused" in data["error"]


def test_nothing_is_written_to_the_flow_file(client, sent, tmp_path):
    before = (tmp_path / "flow.yaml").read_text(encoding="utf-8")
    _send(client, 0, url="http://example.test/changed", body='{"a": 1}')
    assert (tmp_path / "flow.yaml").read_text(encoding="utf-8") == before


@pytest.mark.parametrize(
    "body, status",
    [
        ({"method": "TRACE"}, 400),
        ({"url": ""}, 400),
        ({"headers": {"a": 1}}, 400),
        ({"body": "{not json"}, 400),
        ({"body": 5}, 400),
    ],
)
def test_invalid_input_is_rejected_without_sending(client, sent, body, status):
    assert _send(client, 0, **body).status_code == status
    assert sent == []


def test_manual_and_missing_steps_and_flows(client, sent):
    assert _send(client, 2).status_code == 404
    assert _send(client, 9).status_code == 404
    res = client.post("/api/flow/missing.yaml/step/0/send", json={"method": "GET", "url": "http://x"})
    assert res.status_code == 404


def test_panel_wiring():
    assert 'id="request-modal"' in FLOW_HTML and 'id="req-send"' in FLOW_HTML
    assert 'id="req-curl"' in FLOW_HTML and 'id="req-beautify"' in FLOW_HTML
    assert "function buildCurl()" in FLOW_JS and "function highlightJson(" in FLOW_JS
    assert "(e.ctrlKey || e.metaKey) && e.key === \"Enter\"" in FLOW_JS
    assert "function openRequestPanel(i)" in FLOW_JS
    assert "openRequestPanel(i);" in FLOW_JS.split("function openStepFromSidebar")[1][:400]
    assert "/send`" in FLOW_JS


def test_icon_sprite_is_well_formed_and_has_every_referenced_icon():
    import re
    import xml.dom.minidom

    icons = (ROOT / "templates/icons.html").read_text(encoding="utf-8")
    xml.dom.minidom.parseString(icons)  # a broken sprite silently hides icons
    defined = set(re.findall(r'<symbol id="(i-[a-z-]+)"', icons))
    used = set()
    for path in list((ROOT / "templates").glob("*.html")) + list((ROOT / "static").glob("*.js")):
        used |= set(re.findall(r"#(i-[a-z-]+)", path.read_text(encoding="utf-8")))
    assert used - defined == set(), used - defined


# ── Body types: form-data, x-www-form-urlencoded, uploads ──────────────────────

import io
import json as _json


def _meta(**kw):
    meta = {"method": "POST", "url": "http://example.test/upload", "headers": {}, "body_mode": "form", "fields": []}
    meta.update(kw)
    return meta


def _post_json(client, index, meta):
    return client.post(f"/api/flow/flow.yaml/step/{index}/send", json=meta, headers={"X-ACR-Request": "1"})


def test_form_data_text_only_is_sent_as_multipart(client, sent):
    meta = _meta(
        headers={"Content-Type": "application/json", "X-Keep": "1"},
        fields=[{"key": "name", "type": "text", "value": "Jane"}, {"key": "age", "type": "text", "value": "30"}],
    )
    assert _post_json(client, 0, meta).status_code == 200
    call = sent[0]
    assert call["files"] == [("name", (None, "Jane")), ("age", (None, "30"))]
    assert "json" not in call and "data" not in call
    # A JSON Content-Type would break the multipart boundary, so it is dropped.
    assert call["headers"] == {"X-Keep": "1"}


def test_form_data_with_path_file_and_text(client, sent, tmp_path):
    doc = tmp_path / "doc.txt"
    doc.write_text("hello", encoding="utf-8")
    meta = _meta(fields=[
        {"key": "kind", "type": "text", "value": "aadhaar"},
        {"key": "file", "type": "file", "value": str(doc)},
    ])
    assert _post_json(client, 0, meta).status_code == 200
    names = [(k, v[0]) for k, v in sent[0]["files"]]
    assert ("file", "doc.txt") in names and ("kind", None) in names


def test_browser_uploaded_file_is_forwarded_with_its_name_and_cleaned_up(client, monkeypatch):
    seen = {}

    def fake_request(**kwargs):
        name, handle, mime = next(v for k, v in kwargs["files"] if k == "doc")
        seen.update(name=name, body=handle.read(), path=handle.name)
        return FakeResponse(200, {"ok": True})

    monkeypatch.setattr("api_chain_runner.executor.requests.request", fake_request)
    meta = _meta(fields=[{"key": "doc", "type": "file", "upload": "file_0"}])
    res = client.post(
        "/api/flow/flow.yaml/step/0/send",
        data={"meta": _json.dumps(meta), "file_0": (io.BytesIO(b"PDFDATA"), "aadhaar.pdf")},
        content_type="multipart/form-data",
        headers={"X-ACR-Request": "1"},
    )
    assert res.status_code == 200, res.get_json()
    assert seen["name"] == "aadhaar.pdf" and seen["body"] == b"PDFDATA"
    assert not Path(seen["path"]).exists()  # temp upload removed after the request


def test_urlencoded_body_and_none_mode(client, sent):
    meta = _meta(body_mode="urlencoded", fields=[{"key": "a", "type": "text", "value": "1"}])
    assert _post_json(client, 0, meta).status_code == 200
    assert sent[0]["data"] == {"a": "1"} and "json" not in sent[0]
    assert _post_json(client, 0, _meta(body_mode="none")).status_code == 200
    assert sent[1]["json"] is None


def test_env_placeholders_are_substituted_before_sending(client, sent, monkeypatch):
    monkeypatch.setenv("PANEL_BASE", "http://example.test")
    meta = _meta(body_mode="json", url="${ENV:PANEL_BASE}/lead?x=1", headers={"X-T": "${ENV:PANEL_BASE}"}, body="")
    res = _post_json(client, 0, meta)
    assert res.status_code == 200, res.get_json()
    assert sent[0]["url"] == "http://example.test/lead?x=1" and sent[0]["headers"] == {"X-T": "http://example.test"}


def test_multipart_requests_need_the_custom_header_and_same_origin(client, sent):
    meta = _meta(fields=[{"key": "a", "type": "text", "value": "1"}])
    plain_form = client.post("/api/flow/flow.yaml/step/0/send", data={"meta": _json.dumps(meta)}, content_type="multipart/form-data")
    assert plain_form.status_code == 403
    cross = client.post("/api/flow/flow.yaml/step/0/send", json=meta, headers={"Origin": "http://evil.example"})
    assert cross.status_code == 403
    assert sent == []


@pytest.mark.parametrize(
    "meta",
    [
        _meta(body_mode="bogus"),
        _meta(fields="nope"),
        _meta(fields=[{"key": "f", "type": "file", "upload": "file_9"}]),
        _meta(body_mode="urlencoded", fields=[{"key": "f", "type": "file", "value": "x"}]),
    ],
)
def test_invalid_body_definitions_are_rejected(client, sent, meta):
    assert _post_json(client, 0, meta).status_code == 400
    assert sent == []


def test_form_data_ui_wiring():
    assert 'data-mode="form"' in FLOW_HTML and "x-www-form-urlencoded" in FLOW_HTML
    assert "function buildFormTable(" in FLOW_JS and '"X-ACR-Request"' in FLOW_JS
    assert "new FormData()" in FLOW_JS
