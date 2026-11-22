"""Environment variables popup: GET/POST /api/env."""
from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from api_chain_runner.__main__ import _load_env_file
from api_chain_runner.ui import server

ROOT = Path(__file__).resolve().parents[1] / "api_chain_runner/ui"
H = {"X-ACR-Request": "1"}


@pytest.fixture
def env_client(tmp_path, monkeypatch):
    flow_dir = tmp_path / "project" / "flow"
    flow_dir.mkdir(parents=True)
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.setattr(server, "_flow_dir", str(flow_dir))
    monkeypatch.chdir(cwd)
    for name in ("ACR_A", "ACR_B", "ACR_NEW", "ACR_Q"):
        monkeypatch.delenv(name, raising=False)
    return server.app.test_client(), flow_dir / ".env", tmp_path


def _save(client, entries, path=None):
    body = {"entries": entries}
    if path is not None:
        body["path"] = str(path)
    return client.post("/api/env", json=body, headers=H)


def test_lists_entries_and_candidate_files(env_client):
    client, env_file, tmp = env_client
    env_file.write_text('# my secrets\nACR_A="one"\n\nACR_B=two\n', encoding="utf-8")
    data = client.get("/api/env", headers=H).get_json()
    assert data["path"] == str(env_file) and data["exists"] is True
    assert data["entries"] == [{"key": "ACR_A", "value": "one"}, {"key": "ACR_B", "value": "two"}]
    paths = [f["path"] for f in data["files"]]
    assert paths[0] == str(env_file) and str(tmp / "project" / ".env") in paths and str(tmp / "cwd" / ".env") in paths


def test_summary_never_includes_values(env_client):
    client, env_file, _ = env_client
    env_file.write_text("ACR_A=topsecret\n", encoding="utf-8")
    res = client.get("/api/env?summary=1", headers=H)
    assert res.get_json()["count"] == 1 and "topsecret" not in res.get_data(as_text=True)


def test_save_keeps_comments_and_untouched_lines_and_applies_to_process(env_client):
    client, env_file, _ = env_client
    env_file.write_text("# header\nACR_A='keep me'\nACR_B=old\n# footer\n", encoding="utf-8")
    os.environ["ACR_A"], os.environ["ACR_B"] = "keep me", "old"
    res = _save(client, [{"key": "ACR_A", "value": "keep me"}, {"key": "ACR_B", "value": "new"}, {"key": "ACR_NEW", "value": "x y"}])
    assert res.status_code == 200
    assert env_file.read_text(encoding="utf-8") == "# header\nACR_A='keep me'\nACR_B=\"new\"\n# footer\nACR_NEW=\"x y\"\n"
    assert os.environ["ACR_B"] == "new" and os.environ["ACR_NEW"] == "x y"
    os.environ.pop("ACR_NEW", None)


def test_removed_variables_leave_the_file_and_the_process(env_client):
    client, env_file, _ = env_client
    env_file.write_text("ACR_A=1\nACR_B=2\n", encoding="utf-8")
    os.environ["ACR_A"], os.environ["ACR_B"] = "1", "2"
    assert _save(client, [{"key": "ACR_A", "value": "1"}]).status_code == 200
    assert env_file.read_text(encoding="utf-8") == "ACR_A=1\n"
    assert "ACR_B" not in os.environ
    os.environ.pop("ACR_A", None)


@pytest.mark.parametrize("value", ["plain", "has space", 'say "hi"', "it's", "both ' and \"", "a=b=c", "", "#not-a-comment", "trailing  "])
def test_values_round_trip_through_the_real_loader(env_client, value):
    client, env_file, _ = env_client
    assert _save(client, [{"key": "ACR_Q", "value": value}]).status_code == 200
    os.environ.pop("ACR_Q", None)  # make the loader read the file, not our in-process update
    _load_env_file(str(env_file))
    assert os.environ["ACR_Q"] == value
    os.environ.pop("ACR_Q", None)


def test_new_file_is_created_owner_only(env_client):
    client, env_file, _ = env_client
    assert not env_file.exists()
    assert _save(client, [{"key": "ACR_A", "value": "1"}]).status_code == 200
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600
    os.environ.pop("ACR_A", None)


@pytest.mark.parametrize(
    "entries",
    [
        [{"key": "1BAD", "value": "x"}],
        [{"key": "has space", "value": "x"}],
        [{"key": "", "value": "x"}],
        [{"key": "ACR_A", "value": "x"}, {"key": "ACR_A", "value": "y"}],
        [{"key": "ACR_A", "value": "line1\nline2"}],
        [{"key": "ACR_A", "value": 5}],
        "nope",
    ],
)
def test_invalid_entries_are_rejected_without_writing(env_client, entries):
    client, env_file, _ = env_client
    env_file.write_text("ACR_B=keep\n", encoding="utf-8")
    assert _save(client, entries).status_code == 400
    assert env_file.read_text(encoding="utf-8") == "ACR_B=keep\n"


def test_only_known_env_files_can_be_read_or_written(env_client, tmp_path):
    client, _, tmp = env_client
    outside = tmp / "elsewhere" / ".env"
    outside.parent.mkdir()
    outside.write_text("ACR_A=1\n", encoding="utf-8")
    assert client.get(f"/api/env?path={outside}", headers=H).status_code == 400
    assert _save(client, [{"key": "ACR_A", "value": "2"}], path=outside).status_code == 400
    assert outside.read_text(encoding="utf-8") == "ACR_A=1\n"


def test_can_pick_another_candidate_file(env_client):
    client, _, tmp = env_client
    other = tmp / "cwd" / ".env"
    other.write_text("ACR_B=from-cwd\n", encoding="utf-8")
    data = client.get(f"/api/env?path={other}", headers=H).get_json()
    assert data["entries"] == [{"key": "ACR_B", "value": "from-cwd"}]


def test_requires_custom_header_and_same_origin(env_client):
    client, env_file, _ = env_client
    env_file.write_text("ACR_A=1\n", encoding="utf-8")
    assert client.get("/api/env").status_code == 403
    assert client.get("/api/env", headers={**H, "Origin": "http://evil.example"}).status_code == 403
    assert client.post("/api/env", json={"entries": []}).status_code == 403
    assert env_file.read_text(encoding="utf-8") == "ACR_A=1\n"


def test_ui_wiring():
    for page in ("index", "flow", "docs", "editor"):
        html = (ROOT / f"templates/{page}.html").read_text(encoding="utf-8")
        assert "env_button.html" in html and "env_modal.html" in html and "env.js" in html, page
        assert html.index("env_button.html") < html.index("</aside>"), page
    assert 'id="env-btn"' in (ROOT / "templates/env_button.html").read_text(encoding="utf-8")
    assert "#i-key" in (ROOT / "templates/env_button.html").read_text(encoding="utf-8")
