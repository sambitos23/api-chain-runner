"""Stopping a UI run early keeps the results gathered so far as the report."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from api_chain_runner.pause import PauseController
from api_chain_runner.ui import server


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        body = json.dumps({"status": "PENDING", "n": 1}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture()
def api(tmp_path, monkeypatch):
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_port}"
    (tmp_path / "poll.yaml").write_text(
        "chain:\n"
        "- name: first\n"
        f"  url: {base}/a\n"
        "  method: GET\n"
        "- name: waiting\n"
        f"  url: {base}/job\n"
        "  method: GET\n"
        "  print_keys: [status]\n"
        "  polling:\n"
        "    key_path: status\n"
        "    expected_values: [DONE]\n"
        "    interval: 30\n"
        "    max_timeout: 300\n"
        "- name: never-runs\n"
        f"  url: {base}/c\n"
        "  method: GET\n"
    )
    monkeypatch.setattr(server, "_flow_dir", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    yield server.app.test_client()
    httpd.shutdown()


def _wait(client, run_id, predicate, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = client.get(f"/api/run/{run_id}").get_json()
        if predicate(data):
            return data
        time.sleep(0.1)
    raise AssertionError("timed out waiting for run state")


def test_stop_during_polling_ends_run_with_partial_report(api):
    run_id = api.post("/api/run", json={"flow_path": "poll.yaml"}).get_json()["run_id"]
    _wait(api, run_id, lambda d: d.get("live") and d["live"]["attempt"] >= 1)

    started = time.time()
    assert api.post(f"/api/run/{run_id}/stop").get_json()["success"] is True
    data = _wait(api, run_id, lambda d: d["status"] != "running")

    assert time.time() - started < 5, "stop must not wait for the 30s polling interval"
    assert data["status"] == "stopped"
    assert "waiting" in data["error"]
    assert [r["step_name"] for r in data["results"]] == ["first", "waiting"]
    assert data["results"][0]["success"] is True
    stopped = data["results"][1]
    assert stopped["stopped"] is True and stopped["success"] is False
    assert stopped["error"] == "Stopped by user"
    assert stopped["printed_keys"] == {"status": "PENDING"}
    assert data["retryable"] is False


def test_stop_unknown_or_finished_run_is_404(api):
    assert api.post("/api/run/nope/stop").status_code == 404


def test_pause_controller_stop_request_wakes_a_paused_run():
    pc = PauseController()
    pc._paused.set()
    assert not pc.stop_requested
    pc.request_stop()
    assert pc.stop_requested
    assert not pc._paused.is_set()
    pc.wait_if_paused()  # returns immediately


class _StatusHandler(BaseHTTPRequestHandler):
    """Reports INITIATED until `approved` is flipped, then DATASIGNS_APPROVED."""
    approved = False

    def log_message(self, *args):
        pass

    def do_GET(self):
        status = "DATASIGNS_APPROVED" if _StatusHandler.approved else "INITIATED"
        body = json.dumps({"applications": [{"status": "OLD"}, {"status": status}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)


def test_retry_returns_fresh_print_keys_not_the_failed_attempts(tmp_path, monkeypatch):
    _StatusHandler.approved = False
    httpd = HTTPServer(("127.0.0.1", 0), _StatusHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    (tmp_path / "retry.yaml").write_text(
        "chain:\n"
        "- name: final\n"
        f"  url: http://127.0.0.1:{httpd.server_port}/s\n"
        "  method: GET\n"
        "  continue_on_error: false\n"
        "  print_keys: [applications.-1.status]\n"
        "  polling:\n"
        "    key_path: applications.-1.status\n"
        "    expected_values: [DATASIGNS_APPROVED]\n"
        "    interval: 1\n"
        "    max_timeout: 1\n"
    )
    monkeypatch.setattr(server, "_flow_dir", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    client = server.app.test_client()
    try:
        run_id = client.post("/api/run", json={"flow_path": "retry.yaml"}).get_json()["run_id"]
        aborted = _wait(client, run_id, lambda d: d["status"] != "running")
        assert aborted["status"] == "aborted"
        assert aborted["results"][0]["printed_keys"] == {"applications.-1.status": "INITIATED"}

        _StatusHandler.approved = True
        assert client.post(f"/api/run/{run_id}/retry").get_json()["success"] is True
        done = _wait(client, run_id, lambda d: d["status"] != "running")
        assert done["status"] == "completed"
        assert done["results"][0]["printed_keys"] == {"applications.-1.status": "DATASIGNS_APPROVED"}
    finally:
        httpd.shutdown()
