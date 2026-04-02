"""Flask server for the API Chain Runner web UI."""

from __future__ import annotations

import glob
import json
import os
import threading
import webbrowser
from pathlib import Path

import yaml
from flask import Flask, jsonify, render_template, request

from api_chain_runner.runner import ChainRunner
from api_chain_runner.models import ConfigurationError

app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(__file__), "templates"),
    static_folder=os.path.join(os.path.dirname(__file__), "static"),
)

# Will be set by start_server()
_flow_dir: str = "."


def _discover_flows(base_dir: str) -> list[dict]:
    """Recursively find all .yaml/.yml files and extract chain metadata."""
    flows = []
    for ext in ("**/*.yaml", "**/*.yml"):
        for filepath in glob.glob(os.path.join(base_dir, ext), recursive=True):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    raw = yaml.safe_load(f)
                if not isinstance(raw, dict) or "chain" not in raw:
                    continue
                chain = raw["chain"]
                if not isinstance(chain, list):
                    continue
                rel_path = os.path.relpath(filepath, base_dir)
                # Determine folder group
                parts = Path(rel_path).parts
                folder = "/".join(parts[:-1]) if len(parts) > 1 else ""
                flows.append({
                    "name": Path(filepath).stem,
                    "path": rel_path,
                    "abs_path": os.path.abspath(filepath),
                    "step_count": len(chain),
                    "folder": folder,
                    "has_docs": os.path.isfile(os.path.splitext(filepath)[0] + ".doc.yaml"),
                })
            except Exception:
                continue
    flows.sort(key=lambda f: f["path"])
    return flows


def _parse_chain(filepath: str) -> dict:
    """Parse a YAML chain file and return structured data for visualization."""
    with open(filepath, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    chain = raw.get("chain", [])
    steps = []
    for step in chain:
        if not isinstance(step, dict):
            continue
        step_info = {
            "name": step.get("name", "unnamed"),
            "method": step.get("method", "MANUAL") if not step.get("manual") else "MANUAL",
            "url": step.get("url", ""),
            "continue_on_error": step.get("continue_on_error", True),
            "delay": step.get("delay", 0),
            "has_polling": "polling" in step,
            "has_payload": "payload" in step,
            "has_files": "files" in step,
            "has_unique_fields": "unique_fields" in step,
            "has_condition": "condition" in step,
            "manual": step.get("manual", False),
            "instruction": step.get("instruction", ""),
            "print_ref": step.get("print_ref", []),
            "headers": step.get("headers", {}),
            "print_keys": step.get("print_keys", []),
            "payload": step.get("payload"),
            "unique_fields": step.get("unique_fields"),
            "files": step.get("files"),
            "eval_keys": step.get("eval_keys"),
            "eval_condition": step.get("eval_condition", ""),
            "success_message": step.get("success_message", ""),
            "failure_message": step.get("failure_message", ""),
        }
        if "polling" in step:
            p = step["polling"]
            step_info["polling"] = {
                "key_path": p.get("key_path", ""),
                "expected_values": p.get("expected_values", []),
                "interval": p.get("interval", 5),
                "max_timeout": p.get("max_timeout", 120),
            }
        steps.append(step_info)

    return {
        "name": Path(filepath).stem,
        "variables": list(raw.get("variables", {}).keys()) if raw.get("variables") else [],
        "steps": steps,
    }


def _read_raw_yaml(filepath: str) -> str:
    """Read raw YAML content for editing."""
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()


def _format_yaml_for_readability(yaml_str: str) -> str:
    """Post-process YAML to add blank lines before each step for better readability."""
    # Add newline before '- name:' if it's not already preceded by a blank line
    import re
    # Match '- name:' that starts a line (possibly with indentation)
    formatted = re.sub(r'(\n\s*-\s+name:)', r'\n\1', yaml_str)
    # Avoid triple newlines if double already existed
    formatted = formatted.replace('\n\n\n', '\n\n')
    return formatted.strip() + '\n'


# ── Active run tracking ──────────────────────────────────────────────
_active_runs: dict[str, dict] = {}
_active_runners: dict[str, ChainRunner] = {}
_run_lock = threading.Lock()


def _run_chain_thread(run_id: str, filepath: str):
    """Execute a chain in a background thread, tracking results."""
    with _run_lock:
        _active_runs[run_id] = {
            "status": "running",
            "paused": False,
            "current_step": 0,
            "results": [],
            "error": None,
        }

    try:
        runner = ChainRunner(filepath)
        # Don't start the keyboard listener — we control pause from the UI
        runner.pause_controller.stop()

        with _run_lock:
            _active_runners[run_id] = runner

        for idx, step in enumerate(runner.steps):
            with _run_lock:
                _active_runs[run_id]["current_step"] = idx
                _active_runs[run_id]["paused"] = runner.pause_controller._paused.is_set()

            # Block if paused from UI
            runner.pause_controller.wait_if_paused()

            try:
                if step.manual:
                    step_result = {
                        "step_name": step.name,
                        "status_code": 0,
                        "success": True,
                        "duration_ms": 0,
                        "error": None,
                        "manual": True,
                    }
                else:
                    if step.condition:
                        skip = False
                        for cond in step.condition:
                            if runner.store.has(cond.step):
                                from api_chain_runner.executor import StepExecutor
                                stored = runner.store.get_raw(cond.step)
                                actual = StepExecutor._get_nested(stored, cond.key_path)
                                if str(actual) != cond.expected_value:
                                    skip = True
                                    break
                            else:
                                skip = True
                                break
                        if skip:
                            step_result = {
                                "step_name": step.name,
                                "status_code": 0,
                                "success": True,
                                "duration_ms": 0,
                                "error": None,
                                "skipped": True,
                            }
                            with _run_lock:
                                _active_runs[run_id]["results"].append(step_result)
                            continue

                    if step.delay > 0:
                        import time
                        time.sleep(step.delay)

                    result = runner.executor.execute(step)
                    resp_preview = json.dumps(result.response_body, indent=2, default=str) if isinstance(result.response_body, (dict, list)) else str(result.response_body)

                    step_result = {
                        "step_name": result.step_name,
                        "status_code": result.status_code,
                        "success": result.success,
                        "duration_ms": round(result.duration_ms, 1),
                        "error": result.error,
                        "response_body": resp_preview,
                    }

                    # Extract print_keys values from response
                    if step.print_keys:
                        from api_chain_runner.executor import StepExecutor
                        printed = {}
                        body = result.response_body
                        if isinstance(body, dict):
                            for kp in step.print_keys:
                                try:
                                    val = StepExecutor._get_nested(body, kp)
                                    printed[kp] = str(val) if val is not None else "null"
                                except Exception:
                                    printed[kp] = "—"
                        else:
                            for kp in step.print_keys:
                                printed[kp] = "—"
                        step_result["printed_keys"] = printed

                    # Extract eval results
                    if result.eval_result:
                        step_result["eval_result"] = {
                            k: str(v) for k, v in result.eval_result.items()
                            if not k.startswith("_")
                        }
                        eval_status = result.eval_result.get("_eval_result")
                        eval_msg = result.eval_result.get("_eval_message")
                        if eval_status and eval_msg:
                            step_result["eval_message"] = {
                                "type": "success" if eval_status == "SUCCESS" else "failure",
                                "text": eval_msg,
                            }

                    if not result.success and not step.continue_on_error:
                        with _run_lock:
                            _active_runs[run_id]["results"].append(step_result)
                            _active_runs[run_id]["status"] = "aborted"
                            _active_runs[run_id]["error"] = f"Chain aborted at step '{step.name}'"
                            # Add placeholders for remaining steps so UI can show print_keys hints
                            for remaining_step in runner.steps[idx + 1:]:
                                placeholder = {
                                    "step_name": remaining_step.name,
                                    "status_code": 0,
                                    "success": False,
                                    "duration_ms": 0,
                                    "error": "Not executed (chain aborted)",
                                    "skipped": True,
                                }
                                if remaining_step.print_keys:
                                    placeholder["printed_keys"] = {kp: "—" for kp in remaining_step.print_keys}
                                _active_runs[run_id]["results"].append(placeholder)
                            _active_runners.pop(run_id, None)
                        return

            except Exception as exc:
                step_result = {
                    "step_name": step.name,
                    "status_code": -1,
                    "success": False,
                    "duration_ms": 0,
                    "error": str(exc),
                    "response_body": "",
                }
                # Still include print_keys info so UI knows this step has them
                if step.print_keys:
                    step_result["printed_keys"] = {kp: "—" for kp in step.print_keys}

            with _run_lock:
                _active_runs[run_id]["results"].append(step_result)

        with _run_lock:
            _active_runs[run_id]["status"] = "completed"
            _active_runners.pop(run_id, None)

    except Exception as exc:
        with _run_lock:
            _active_runs[run_id]["status"] = "error"
            _active_runs[run_id]["error"] = str(exc)
            _active_runners.pop(run_id, None)


# ── Routes ────────────────────────────────────────────────────────────

@app.route("/")
def index():
    flows = _discover_flows(_flow_dir)
    return render_template("index.html", flows=flows)


@app.route("/flow/<path:flow_path>")
def flow_view(flow_path):
    abs_path = os.path.join(_flow_dir, flow_path)
    if not os.path.isfile(abs_path):
        return "Flow not found", 404
    chain_data = _parse_chain(abs_path)
    return render_template("flow.html", chain=chain_data, flow_path=flow_path)


@app.route("/flow/<path:flow_path>/editor")
def flow_editor_view(flow_path):
    abs_path = os.path.join(_flow_dir, flow_path)
    if not os.path.isfile(abs_path):
        return "Flow not found", 404
    flow_name = Path(flow_path).stem
    return render_template("editor.html", flow_path=flow_path, flow_name=flow_name)


@app.route("/api/flows")
def api_flows():
    return jsonify(_discover_flows(_flow_dir))


@app.route("/api/flow/<path:flow_path>")
def api_flow_detail(flow_path):
    abs_path = os.path.join(_flow_dir, flow_path)
    if not os.path.isfile(abs_path):
        return jsonify({"error": "not found"}), 404
    return jsonify(_parse_chain(abs_path))


@app.route("/api/flow/<path:flow_path>/raw")
def api_flow_raw(flow_path):
    """Return raw YAML content for editing."""
    abs_path = os.path.join(_flow_dir, flow_path)
    if not os.path.isfile(abs_path):
        return jsonify({"error": "not found"}), 404
    return jsonify({"content": _read_raw_yaml(abs_path)})


@app.route("/api/flow/<path:flow_path>/save", methods=["POST"])
def api_flow_save(flow_path):
    """Save edited YAML content back to the file."""
    abs_path = os.path.join(_flow_dir, flow_path)
    if not os.path.isfile(abs_path):
        return jsonify({"error": "not found"}), 404

    data = request.get_json()
    content = data.get("content", "")

    # Validate YAML before saving
    try:
        parsed = yaml.safe_load(content)
        if not isinstance(parsed, dict) or "chain" not in parsed:
            return jsonify({"error": "YAML must contain a top-level 'chain' key"}), 400
    except yaml.YAMLError as exc:
        return jsonify({"error": f"Invalid YAML: {exc}"}), 400

    try:
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(_format_yaml_for_readability(content))
        return jsonify({"success": True})
    except OSError as exc:
        return jsonify({"error": f"Failed to save: {exc}"}), 500


@app.route("/api/flow/<path:flow_path>/step/<int:step_index>", methods=["POST"])
def api_step_update(flow_path, step_index):
    """Update a specific step's editable fields (payload, headers, url, etc.) and save to file."""
    abs_path = os.path.join(_flow_dir, flow_path)
    if not os.path.isfile(abs_path):
        return jsonify({"error": "not found"}), 404

    data = request.get_json()
    updates = data.get("updates", {})

    try:
        with open(abs_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        chain = raw.get("chain", [])
        if step_index < 0 or step_index >= len(chain):
            return jsonify({"error": "step index out of range"}), 400

        step = chain[step_index]
        # Apply updates to allowed fields
        allowed = {"payload", "headers", "url", "unique_fields", "delay", "continue_on_error", "method", "files", "print_keys", "polling", "eval_keys", "eval_condition", "success_message", "failure_message", "manual", "instruction", "print_ref"}
        for key, value in updates.items():
            if key in allowed:
                if value is None or value == "":
                    step.pop(key, None)
                else:
                    step[key] = value

        # Write back preserving original formatting as much as possible
        dumped = yaml.dump(raw, default_flow_style=False, allow_unicode=True, sort_keys=False)
        formatted = _format_yaml_for_readability(dumped)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(formatted)

        return jsonify({"success": True})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/flow/create", methods=["POST"])
def api_flow_create():
    """Create a new flow YAML file with initial steps."""
    data = request.get_json()
    name = data.get("name", "").strip()
    folder = data.get("folder", "").strip()
    steps_data = data.get("steps", [])

    if not name:
        return jsonify({"error": "Flow name is required"}), 400
    if not steps_data:
        return jsonify({"error": "At least one step is required"}), 400

    # Sanitize name
    safe_name = name.replace(" ", "_").replace("/", "_")
    if not safe_name.endswith((".yaml", ".yml")):
        safe_name += ".yaml"

    # Build path
    if folder:
        rel_path = os.path.join(folder, safe_name)
    else:
        rel_path = safe_name

    abs_path = os.path.join(_flow_dir, rel_path)

    if os.path.exists(abs_path):
        return jsonify({"error": f"Flow '{rel_path}' already exists"}), 400

    # Build YAML content
    chain = []
    for s in steps_data:
        step = {
            "name": s.get("name", "unnamed"),
            "url": "https://example.com/api",
            "method": s.get("method", "GET"),
            "continue_on_error": True,
            "headers": {"Content-Type": "application/json"},
        }
        if s.get("method", "GET") in ("POST", "PUT", "PATCH"):
            step["payload"] = {}
        chain.append(step)

    flow_data = {"chain": chain}

    try:
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            yaml.dump(flow_data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        return jsonify({"success": True, "path": rel_path})
    except OSError as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/run", methods=["POST"])
def api_run_chain():
    data = request.get_json()
    flow_path = data.get("flow_path")
    if not flow_path:
        return jsonify({"error": "flow_path required"}), 400

    abs_path = os.path.join(_flow_dir, flow_path)
    if not os.path.isfile(abs_path):
        return jsonify({"error": "flow not found"}), 404

    import uuid
    run_id = uuid.uuid4().hex[:8]
    t = threading.Thread(target=_run_chain_thread, args=(run_id, abs_path), daemon=True)
    t.start()

    return jsonify({"run_id": run_id})


@app.route("/api/run/<run_id>")
def api_run_status(run_id):
    with _run_lock:
        run = _active_runs.get(run_id)
        if run and run_id in _active_runners:
            run["paused"] = _active_runners[run_id].pause_controller._paused.is_set()
    if not run:
        return jsonify({"error": "run not found"}), 404
    return jsonify(run)


@app.route("/api/run/<run_id>/pause", methods=["POST"])
def api_run_pause(run_id):
    with _run_lock:
        runner = _active_runners.get(run_id)
    if not runner:
        return jsonify({"error": "run not found or already finished"}), 404
    runner.pause_controller._paused.set()
    return jsonify({"success": True, "paused": True})


@app.route("/api/run/<run_id>/resume", methods=["POST"])
def api_run_resume(run_id):
    with _run_lock:
        runner = _active_runners.get(run_id)
    if not runner:
        return jsonify({"error": "run not found or already finished"}), 404
    runner.pause_controller._paused.clear()
    return jsonify({"success": True, "paused": False})


# ── Flow Documentation ────────────────────────────────────────────────

def _doc_path_for(flow_path: str) -> str:
    """Return the .doc.yaml path for a given flow path."""
    base = os.path.splitext(flow_path)[0]
    return base + ".doc.yaml"


def _get_doc(flow_path: str) -> dict | None:
    """Load the doc file for a flow, or return None."""
    dp = os.path.join(_flow_dir, _doc_path_for(flow_path))
    if not os.path.isfile(dp):
        return None
    try:
        with open(dp, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return None


def _default_doc(flow_name: str) -> dict:
    """Return a default doc template."""
    return {
        "title": flow_name.replace("_", " ").replace("-", " ").title(),
        "description": "",
        "authors": [{"name": "", "email": "", "role": ""}],
        "group": "",
        "tags": [],
        "context": "",
        "images": [],
        "changelog": [],
    }


@app.route("/flow/<path:flow_path>/docs")
def flow_docs_view(flow_path):
    """Render the docs page for a flow."""
    abs_path = os.path.join(_flow_dir, flow_path)
    if not os.path.isfile(abs_path):
        return "Flow not found", 404
    flow_name = Path(flow_path).stem
    doc = _get_doc(flow_path) or _default_doc(flow_name)
    return render_template("docs.html", doc=doc, flow_path=flow_path, flow_name=flow_name)


@app.route("/api/flow/<path:flow_path>/docs")
def api_flow_docs(flow_path):
    """Get doc data for a flow."""
    doc = _get_doc(flow_path)
    if doc is None:
        return jsonify({"exists": False, "doc": _default_doc(Path(flow_path).stem)})
    return jsonify({"exists": True, "doc": doc})


@app.route("/api/flow/<path:flow_path>/docs/save", methods=["POST"])
def api_flow_docs_save(flow_path):
    """Save doc data for a flow."""
    data = request.get_json()
    doc = data.get("doc", {})
    dp = os.path.join(_flow_dir, _doc_path_for(flow_path))
    try:
        os.makedirs(os.path.dirname(dp), exist_ok=True)
        with open(dp, "w", encoding="utf-8") as f:
            yaml.dump(doc, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        return jsonify({"success": True})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/flow/<path:flow_path>/docs/upload", methods=["POST"])
def api_flow_docs_upload(flow_path):
    """Upload an image for a flow's documentation."""
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "Empty filename"}), 400

    flow_stem = Path(flow_path).stem
    docs_dir = os.path.join(_flow_dir, "docs", flow_stem)
    os.makedirs(docs_dir, exist_ok=True)

    # Sanitize filename
    safe_name = f.filename.replace(" ", "_").replace("/", "_")
    save_path = os.path.join(docs_dir, safe_name)
    f.save(save_path)

    rel_path = f"docs/{flow_stem}/{safe_name}"
    return jsonify({"success": True, "path": rel_path})


@app.route("/docs/<path:img_path>")
def serve_doc_image(img_path):
    """Serve uploaded doc images."""
    from flask import send_from_directory
    return send_from_directory(os.path.join(_flow_dir, "docs"), img_path)


def start_server(flow_dir: str = ".", host: str = "127.0.0.1", port: int = 5656):
    """Start the Flask UI server."""
    global _flow_dir
    _flow_dir = os.path.abspath(flow_dir)

    # Load .env if present in the flow directory or current directory
    from api_chain_runner.__main__ import _load_env_file
    _load_env_file(os.path.join(_flow_dir, ".env"))
    _load_env_file(".env")

    print(f"\n🌐 API Chain Runner UI")
    print(f"   Scanning flows in: {_flow_dir}")
    print(f"   Open http://{host}:{port}\n")

    webbrowser.open(f"http://{host}:{port}")
    app.run(host=host, port=port, debug=False)
