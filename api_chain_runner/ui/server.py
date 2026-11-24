"""Flask server for the API Chain Runner web UI."""

from __future__ import annotations

import copy
import dataclasses
import glob
import json
import os
import re
import tempfile
import threading
import webbrowser
from datetime import datetime
from urllib.parse import quote, unquote, urlparse
from pathlib import Path

import yaml
from flask import Flask, jsonify, redirect, render_template, request

from api_chain_runner.runner import ChainRunner, _substitute_env_vars
from api_chain_runner.models import VALID_CONDITION_OPERATORS

app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(__file__), "templates"),
    static_folder=os.path.join(os.path.dirname(__file__), "static"),
)

# Will be set by start_server()
_flow_dir: str = "."


def _local_timestamp() -> str:
    """Return the local timezone timestamp used by the UI response timeline."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


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


def _build_flow_tree(flows: list[dict]) -> dict:
    """Group discovered flows into a folder tree for the dashboard and sidebar.

    Each node has ``name``, ``path`` (folder path, "" for the root), ``flows``,
    ``children`` and ``total`` (flows in this folder and everything below it).
    """
    root: dict = {"name": "", "path": "", "flows": [], "children": [], "total": 0}
    for flow in flows:
        node = root
        node["total"] += 1
        parts = [p for p in flow["folder"].split("/") if p]
        for i, part in enumerate(parts):
            child = next((c for c in node["children"] if c["name"] == part), None)
            if child is None:
                child = {"name": part, "path": "/".join(parts[: i + 1]),
                         "flows": [], "children": [], "total": 0}
                node["children"].append(child)
            node = child
            node["total"] += 1
        node["flows"].append(flow)

    def _sort(node: dict) -> None:
        node["children"].sort(key=lambda c: c["name"].lower())
        node["flows"].sort(key=lambda f: f["name"].lower())
        for c in node["children"]:
            _sort(c)

    _sort(root)
    return root


def _normalize_conditions(value, *, field_name="condition") -> list[dict[str, str]]:
    """Return condition data in the UI's ordered-list representation.

    ChainRunner accepts both the legacy single mapping form and the current
    list form.  The UI always receives and persists a list, with values
    normalized to strings so the result can be loaded by ChainRunner without
    changing condition comparison semantics.
    """
    if value is None:
        return []
    entries = [value] if isinstance(value, dict) else value
    if not isinstance(entries, list):
        raise ValueError(f"'{field_name}' must be a mapping or list of mappings")

    normalized = []
    required = ("step", "key_path", "expected_value")
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"condition at index {index} must be a mapping")
        missing = [name for name in required if name not in entry]
        if missing:
            raise ValueError(
                f"condition at index {index} missing required field(s): {', '.join(missing)}"
            )
        if not isinstance(entry["step"], str) or not entry["step"].strip():
            raise ValueError(f"condition at index {index} 'step' must be a non-empty string")
        if not isinstance(entry["key_path"], str) or not entry["key_path"].strip():
            raise ValueError(f"condition at index {index} 'key_path' must be a non-empty string")
        operator = str(entry.get("operator", "equals")).strip().lower()
        if operator not in VALID_CONDITION_OPERATORS:
            raise ValueError(
                f"condition at index {index} has invalid operator '{operator}'"
            )
        normalized_entry = {
            "step": entry["step"],
            "key_path": entry["key_path"],
            "expected_value": str(entry["expected_value"]),
        }
        # Keep legacy YAML/UI output unchanged when operator was omitted.
        if "operator" in entry:
            normalized_entry["operator"] = operator
        normalized.append(normalized_entry)
    return normalized


def _parse_chain(filepath: str) -> dict:
    """Parse a YAML chain file and return structured data for visualization."""
    with open(filepath, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    chain = raw.get("chain", [])
    steps = []
    for step in chain:
        if not isinstance(step, dict):
            continue
        condition = _normalize_conditions(step.get("condition"))
        step_info = {
            "name": step.get("name", "unnamed"),
            "method": step.get("method", "MANUAL") if not step.get("manual") else "MANUAL",
            "url": step.get("url", ""),
            "continue_on_error": step.get("continue_on_error", True),
            "delay": step.get("delay", 0),
            "has_polling": isinstance(step.get("polling"), dict),
            "has_payload": "payload" in step,
            "has_files": "files" in step,
            "has_unique_fields": "unique_fields" in step,
            "has_condition": bool(condition),
            "condition": condition,
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
            "retry": step.get("retry"),
        }
        if isinstance(step.get("polling"), dict):
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


def _validate_step_names(raw: dict) -> None:
    """Validate only the required and unique names in a candidate chain."""
    chain = raw.get("chain") if isinstance(raw, dict) else None
    if not isinstance(chain, list) or not chain:
        raise ValueError("Configuration must contain a non-empty 'chain' list.")

    seen = set()
    for index, step in enumerate(chain):
        if not isinstance(step, dict):
            raise ValueError(f"Step at index {index} must be a mapping.")
        name = step.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Step at index {index} must have a non-empty name.")
        normalized = name.strip()
        if normalized in seen:
            raise ValueError(f"Duplicate step name '{normalized}'. Step names must be unique.")
        seen.add(normalized)


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
_manual_events: dict[str, threading.Event] = {}
# Runners kept alive after a stop-on-fail abort so the failed step can be
# retried with the same response store (context). Keyed by run_id.
_retry_contexts: dict[str, dict] = {}
# Last known step responses per flow file, so a single step sent from the
# request panel can resolve ${step.key} references from earlier runs/sends.
_flow_stores: dict[str, dict] = {}
_MAX_RETRY_CONTEXTS = 10
_run_lock = threading.Lock()


def _coerce_like(original, text):
    """Convert user-entered *text* back to the type of the *original* template value."""
    text = "" if text is None else str(text)
    if isinstance(original, bool):
        return text.strip().lower() == "true"
    if isinstance(original, int):
        try:
            return int(text.strip())
        except ValueError:
            return text
    if isinstance(original, float):
        try:
            return float(text.strip())
        except ValueError:
            return text
    return text


def _set_payload_value(payload, path: list, text) -> None:
    """Set the leaf at *path* (dict keys / list indexes) in *payload* in place."""
    if not isinstance(path, list) or not path:
        raise ValueError("payload override path must be a non-empty list")
    node = payload
    for seg in path[:-1]:
        node = node[seg] if isinstance(node, list) and isinstance(seg, int) else node[str(seg)]
    last = path[-1]
    if isinstance(node, list):
        if not isinstance(last, int) or isinstance(last, bool):
            raise ValueError(f"invalid payload path {path!r}")
        node[last] = _coerce_like(node[last], text)
    elif isinstance(node, dict) and str(last) in node:
        node[str(last)] = _coerce_like(node[str(last)], text)
    else:
        raise ValueError(f"invalid payload path {path!r}")


def _apply_query_overrides(url: str, overrides: list) -> str:
    """Replace the value of query-string parts (by position) in *url*."""
    base, sep, rest = url.partition("?")
    if not sep:
        raise ValueError("step URL has no query string")
    rest, hsep, fragment = rest.partition("#")
    parts = rest.split("&")
    for item in overrides:
        idx, value = item.get("index"), item.get("value")
        if not isinstance(idx, int) or isinstance(idx, bool) or not 0 <= idx < len(parts):
            raise ValueError("invalid query parameter index")
        key = parts[idx].partition("=")[0]
        parts[idx] = f"{key}={quote('' if value is None else str(value), safe='${}')}"
    return f"{base}?{'&'.join(parts)}{hsep}{fragment}"


def _apply_overrides(runner: ChainRunner, overrides: dict) -> None:
    """Apply per-run payload/query overrides to the runner's in-memory steps.

    The flow YAML is never modified. *overrides* maps a step index (as a
    string) to ``{"query": [{"index", "value"}], "payload": [{"path", "value"}]}``.
    """
    for key, spec in overrides.items():
        try:
            idx = int(key)
        except (TypeError, ValueError):
            raise ValueError(f"invalid step index {key!r}")
        if not 0 <= idx < len(runner.steps) or not isinstance(spec, dict):
            raise ValueError(f"invalid step index {key!r}")
        step = runner.steps[idx]
        changes = {}
        if spec.get("query"):
            changes["url"] = _apply_query_overrides(step.url, spec["query"])
        if spec.get("payload"):
            if not isinstance(step.payload, (dict, list)):
                raise ValueError(f"step '{step.name}' has no payload to override")
            payload = copy.deepcopy(step.payload)
            for item in spec["payload"]:
                _set_payload_value(payload, item.get("path"), item.get("value"))
            changes["payload"] = payload
        if changes:
            runner.steps[idx] = dataclasses.replace(step, **changes)


def _abort_run(run_id: str, runner: ChainRunner, filepath: str, idx: int, step_result: dict) -> None:
    """Mark a run aborted at step *idx* and keep its runner so it can be retried."""
    step = runner.steps[idx]
    with _run_lock:
        run = _active_runs[run_id]
        run["results"].append(step_result)
        run["status"] = "aborted"
        run["error"] = f"Chain aborted at step '{step.name}'"
        run["retryable"] = True
        run["failed_step_index"] = idx
        # Add placeholders for remaining steps so UI can show print_keys hints
        for remaining_idx, remaining_step in enumerate(runner.steps[idx + 1:], start=idx + 1):
            placeholder = {
                "step_name": remaining_step.name,
                "status_code": 0,
                "success": False,
                "duration_ms": 0,
                "executed_at": "",
                "error": "Not executed (chain aborted)",
                "skipped": True,
            }
            selected = getattr(runner, "_selected_indexes", None)
            if selected is not None and remaining_idx not in selected:
                placeholder.update(success=True, error="Not selected", not_selected=True)
            if remaining_step.print_keys:
                placeholder["printed_keys"] = {kp: "—" for kp in remaining_step.print_keys}
            run["results"].append(placeholder)
        _active_runners.pop(run_id, None)
        _manual_events.pop(run_id, None)
        _retry_contexts[run_id] = {"runner": runner, "filepath": filepath}
        _flow_stores[filepath] = dict(runner.store._data)
        # Bound memory: drop the oldest retry contexts first.
        while len(_retry_contexts) > _MAX_RETRY_CONTEXTS:
            oldest = next(iter(_retry_contexts))
            _retry_contexts.pop(oldest, None)
            stale = _active_runs.get(oldest)
            if stale:
                stale["retryable"] = False


def _run_chain_thread(
    run_id: str,
    filepath: str,
    start_idx: int = 0,
    runner: ChainRunner | None = None,
    selected: set[int] | None = None,
    overrides: dict | None = None,
):
    """Execute a chain in a background thread, tracking results.

    When *runner* and *start_idx* are given, the run resumes from that step
    using the runner's existing response store (used by retry). When
    *selected* is given, only those step indexes run; *overrides* patches
    their payload/query values for this run only.
    """
    if runner is None:
        with _run_lock:
            _active_runs[run_id] = {
                "status": "running",
                "paused": False,
                "waiting_manual": False,
                "manual_instruction": "",
                "manual_step_name": "",
                "manual_print_ref": [],
                "current_step": 0,
                "results": [],
                "error": None,
                "retryable": False,
                "failed_step_index": None,
            }
            _manual_events[run_id] = threading.Event()

    try:
        if runner is None:
            runner = ChainRunner(filepath)
            # Don't start the keyboard listener — we control pause from the UI
            runner.pause_controller.stop()
            if selected is not None:
                if not selected or any(i < 0 or i >= len(runner.steps) for i in selected):
                    raise ValueError("selected steps are out of range")
                runner._selected_indexes = set(selected)
            if overrides:
                _apply_overrides(runner, overrides)

        with _run_lock:
            _active_runners[run_id] = runner

        for idx, step in enumerate(runner.steps):
            if idx < start_idx:
                continue
            chosen = getattr(runner, "_selected_indexes", None)
            if chosen is not None and idx not in chosen:
                with _run_lock:
                    _active_runs[run_id]["results"].append({
                        "step_name": step.name,
                        "status_code": 0,
                        "success": True,
                        "duration_ms": 0,
                        "executed_at": "",
                        "error": "Not selected",
                        "skipped": True,
                        "not_selected": True,
                    })
                continue
            with _run_lock:
                _active_runs[run_id]["current_step"] = idx
                _active_runs[run_id]["paused"] = runner.pause_controller._paused.is_set()

            # Block if paused from UI
            runner.pause_controller.wait_if_paused()

            try:
                execution_time = None
                if step.condition:
                    execution_time = _local_timestamp()
                    skip = False
                    for cond in step.condition:
                        if runner.store.has(cond.step):
                            from api_chain_runner.executor import StepExecutor
                            stored = runner.store.get_raw(cond.step)
                            actual = StepExecutor._get_nested(stored, cond.key_path)
                            if not runner.condition_matches(actual, cond):
                                skip = True
                                break
                        elif chosen is None:
                            skip = True
                            break
                    if skip:
                        step_result = {
                            "step_name": step.name,
                            "status_code": 0,
                            "success": True,
                            "duration_ms": 0,
                            "executed_at": execution_time or _local_timestamp(),
                            "error": None,
                            "skipped": True,
                        }
                        with _run_lock:
                            _active_runs[run_id]["results"].append(step_result)
                        continue

                if step.manual:
                    execution_time = _local_timestamp()
                    # Resolve print_ref values from previous steps
                    resolved_refs = {}
                    if step.print_ref:
                        from api_chain_runner.executor import StepExecutor
                        for ref in step.print_ref:
                            parts = ref.split(".", 1)
                            if len(parts) == 2 and runner.store.has(parts[0]):
                                try:
                                    stored = runner.store.get_raw(parts[0])
                                    val = StepExecutor._get_nested(stored, parts[1])
                                    resolved_refs[ref] = str(val) if val is not None else "null"
                                except Exception:
                                    resolved_refs[ref] = "—"
                            else:
                                resolved_refs[ref] = "—"

                    # Signal the UI that we're waiting for manual completion
                    manual_evt = _manual_events.get(run_id)
                    if manual_evt:
                        manual_evt.clear()

                    with _run_lock:
                        _active_runs[run_id]["waiting_manual"] = True
                        _active_runs[run_id]["manual_instruction"] = step.instruction or ""
                        _active_runs[run_id]["manual_step_name"] = step.name
                        _active_runs[run_id]["manual_print_ref"] = resolved_refs

                    # Block until the user clicks "Mark as Done" in the UI
                    if manual_evt:
                        manual_evt.wait()

                    with _run_lock:
                        _active_runs[run_id]["waiting_manual"] = False
                        _active_runs[run_id]["manual_instruction"] = ""
                        _active_runs[run_id]["manual_step_name"] = ""
                        _active_runs[run_id]["manual_print_ref"] = []

                    step_result = {
                        "step_name": step.name,
                        "status_code": 0,
                        "success": True,
                        "duration_ms": 0,
                        "executed_at": execution_time,
                        "error": None,
                        "manual": True,
                    }
                else:
                    if step.delay > 0:
                        import time
                        time.sleep(step.delay)

                    execution_time = _local_timestamp()
                    result = runner.executor.execute(step)
                    resp_preview = json.dumps(result.response_body, indent=2, default=str) if isinstance(result.response_body, (dict, list)) else str(result.response_body)

                    step_result = {
                        "step_name": result.step_name,
                        "status_code": result.status_code,
                        "success": result.success,
                        "duration_ms": round(result.duration_ms, 1),
                        "executed_at": execution_time,
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
                        _abort_run(run_id, runner, filepath, idx, step_result)
                        return

            except Exception as exc:
                step_result = {
                    "step_name": step.name,
                    "status_code": -1,
                    "success": False,
                    "duration_ms": 0,
                    "executed_at": execution_time or "",
                    "error": str(exc),
                    "response_body": "",
                }
                # Still include print_keys info so UI knows this step has them
                if step.print_keys:
                    step_result["printed_keys"] = {kp: "—" for kp in step.print_keys}
                if not step.continue_on_error:
                    _abort_run(run_id, runner, filepath, idx, step_result)
                    return

            with _run_lock:
                _active_runs[run_id]["results"].append(step_result)

        with _run_lock:
            _flow_stores[filepath] = dict(runner.store._data)
            _active_runs[run_id]["status"] = "completed"
            _active_runners.pop(run_id, None)
            _manual_events.pop(run_id, None)

    except Exception as exc:
        with _run_lock:
            _active_runs[run_id]["status"] = "error"
            _active_runs[run_id]["error"] = str(exc)
            _active_runners.pop(run_id, None)
            _manual_events.pop(run_id, None)


# ── Routes ────────────────────────────────────────────────────────────

@app.route("/")
def index():
    flows = _discover_flows(_flow_dir)
    tree = _build_flow_tree(flows)
    # Drive-style navigation: ?folder=a/b shows the contents of that folder.
    wanted = [p for p in request.args.get("folder", "").split("/") if p]
    current, crumbs = tree, []
    for part in wanted:
        nxt = next((c for c in current["children"] if c["name"] == part), None)
        if nxt is None:
            return redirect("/")
        current = nxt
        crumbs.append(nxt)
    return render_template("index.html", flows=flows, tree=tree, current=current, crumbs=crumbs)


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
        # Validate conditions before mutating any other field so malformed
        # editor submissions cannot partially save a step.
        normalized_condition = None
        if "condition" in updates:
            submitted_condition = updates["condition"]
            if not isinstance(submitted_condition, list):
                return jsonify({"error": "'condition' must be a list of mappings"}), 400
            try:
                normalized_condition = _normalize_conditions(submitted_condition)
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 400

        # Apply updates to allowed fields
        allowed = {"name", "payload", "headers", "url", "unique_fields", "delay", "continue_on_error", "method", "files", "print_keys", "polling", "eval_keys", "eval_condition", "success_message", "failure_message", "manual", "instruction", "print_ref", "retry", "condition"}
        for key, value in updates.items():
            if key not in allowed:
                continue
            if key == "condition":
                if normalized_condition:
                    step[key] = normalized_condition
                else:
                    # An explicit empty list is the clearing contract.
                    step.pop(key, None)
            elif value is None or value == "":
                step.pop(key, None)
            else:
                step[key] = value

        try:
            _validate_step_names(raw)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        # Write back preserving original formatting as much as possible
        dumped = yaml.dump(
            raw,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
            default_style='"',
        )
        formatted = _format_yaml_for_readability(dumped)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(formatted)

        return jsonify({"success": True})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/flow/<path:flow_path>/step/<int:step_index>", methods=["DELETE"])
def api_step_delete(flow_path, step_index):
    """Delete one step after checking the remaining step names."""
    abs_path = os.path.join(_flow_dir, flow_path)
    if not os.path.isfile(abs_path):
        return jsonify({"error": "not found"}), 404

    try:
        with open(abs_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        chain = raw.get("chain", []) if isinstance(raw, dict) else []
        if step_index < 0 or step_index >= len(chain):
            return jsonify({"error": "step index out of range"}), 400

        candidate = dict(raw)
        candidate["chain"] = list(chain)
        candidate["chain"].pop(step_index)
        _validate_step_names(candidate)

        dumped = yaml.dump(
            candidate,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
            default_style='"',
        )
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(_format_yaml_for_readability(dumped))
        return jsonify({"success": True})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/flow/<path:flow_path>/step", methods=["POST"])
def api_step_add(flow_path):
    """Insert one validated step into an existing flow (appended unless ``position`` is given)."""
    abs_path = os.path.join(_flow_dir, flow_path)
    if not os.path.isfile(abs_path):
        return jsonify({"error": "not found"}), 404

    data = request.get_json(silent=True) or {}
    new_step = data.get("step", data.get("updates"))
    if not isinstance(new_step, dict):
        return jsonify({"error": "step must be a mapping"}), 400
    if new_step.get("manual") is True and not str(new_step.get("instruction") or "").strip():
        return jsonify({"error": "manual steps need an instruction"}), 400

    try:
        with open(abs_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        if not isinstance(raw, dict) or not isinstance(raw.get("chain"), list):
            return jsonify({"error": "Configuration must contain a top-level 'chain' list."}), 400
        candidate = dict(raw)
        chain_steps = list(raw["chain"])
        position = data.get("position")
        if position is None:
            position = len(chain_steps)
        if isinstance(position, bool) or not isinstance(position, int) or not 0 <= position <= len(chain_steps):
            return jsonify({"error": "position must be an integer between 0 and the number of steps"}), 400
        chain_steps.insert(position, dict(new_step))
        candidate["chain"] = chain_steps
        _validate_step_names(candidate)

        dumped = yaml.dump(
            candidate,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
            default_style='"',
        )
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(_format_yaml_for_readability(dumped))
        return jsonify({"success": True})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


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

    selected = None
    overrides = None
    if data.get("steps") is not None:
        raw_steps = data["steps"]
        if (
            not isinstance(raw_steps, list)
            or not raw_steps
            or any(isinstance(i, bool) or not isinstance(i, int) or i < 0 for i in raw_steps)
        ):
            return jsonify({"error": "steps must be a non-empty list of step indexes"}), 400
        selected = set(raw_steps)
        overrides = data.get("overrides") or {}
        if not isinstance(overrides, dict):
            return jsonify({"error": "overrides must be a mapping"}), 400

    import uuid
    run_id = uuid.uuid4().hex[:8]
    t = threading.Thread(
        target=_run_chain_thread,
        args=(run_id, abs_path, 0, None, selected, overrides),
        daemon=True,
    )
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


@app.route("/api/run/<run_id>/retry", methods=["POST"])
def api_run_retry(run_id):
    """Re-run the failed stop-on-fail step and continue with the existing context."""
    with _run_lock:
        run = _active_runs.get(run_id)
        ctx = _retry_contexts.get(run_id)
        if not run or not ctx:
            return jsonify({"error": "run not found or not retryable"}), 404
        if run.get("status") != "aborted" or not run.get("retryable"):
            return jsonify({"error": "run is not in a retryable state"}), 400
        idx = run["failed_step_index"]
        # Results line up one-to-one with steps, so dropping from idx removes
        # the failed result and the "not executed" placeholders.
        run["results"] = run["results"][:idx]
        run["status"] = "running"
        run["error"] = None
        run["retryable"] = False
        run["failed_step_index"] = None
        run["paused"] = False
        run["current_step"] = idx
        _retry_contexts.pop(run_id, None)
        _manual_events[run_id] = threading.Event()
        runner = ctx["runner"]
        runner.pause_controller._paused.clear()

    t = threading.Thread(
        target=_run_chain_thread,
        args=(run_id, ctx["filepath"], idx, runner),
        daemon=True,
    )
    t.start()
    return jsonify({"success": True, "run_id": run_id})


_SEND_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
_BODY_MODES = {"none", "json", "form", "urlencoded"}


def _same_origin(req) -> bool:
    """True when the request carries no Origin header or it matches this server."""
    origin = req.headers.get("Origin")
    if not origin:
        return True
    return urlparse(origin).netloc == req.host


def _read_send_meta():
    """Return (meta dict, uploaded files mapping) from a JSON or multipart request."""
    if request.mimetype == "multipart/form-data":
        try:
            meta = json.loads(request.form.get("meta", ""))
        except ValueError:
            return None, {}
        return meta, request.files
    return request.get_json(silent=True), {}


def _safe_upload_name(name: str) -> str:
    base = Path((name or "").replace("\\", "/")).name
    return base or "upload"


@app.route("/api/flow/<path:flow_path>/step/<int:step_index>/send", methods=["POST"])
def api_step_send(flow_path, step_index):
    """Send one step on its own (request panel). Nothing is written to the YAML."""
    abs_path = os.path.join(_flow_dir, flow_path)
    if not os.path.isfile(abs_path):
        return jsonify({"error": "flow not found"}), 404
    # Multipart bodies need no CORS preflight, so a web page on another origin could
    # otherwise post here and make this server read local files. Require same-origin.
    if not _same_origin(request):
        return jsonify({"error": "cross-origin requests are not allowed"}), 403
    if request.mimetype == "multipart/form-data" and request.headers.get("X-ACR-Request") != "1":
        return jsonify({"error": "missing X-ACR-Request header"}), 403
    data, uploads = _read_send_meta()
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body required"}), 400

    method = str(data.get("method", "")).upper()
    url = data.get("url")
    headers = data.get("headers") or {}
    body_mode = data.get("body_mode") or "json"
    body_text = data.get("body")
    fields = data.get("fields") or []
    if method not in _SEND_METHODS:
        return jsonify({"error": f"method must be one of {sorted(_SEND_METHODS)}"}), 400
    if not isinstance(url, str) or not url.strip():
        return jsonify({"error": "url is required"}), 400
    if not isinstance(headers, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in headers.items()):
        return jsonify({"error": "headers must be a mapping of strings"}), 400
    if body_mode not in _BODY_MODES:
        return jsonify({"error": f"body_mode must be one of {sorted(_BODY_MODES)}"}), 400
    if not isinstance(fields, list) or not all(isinstance(f, dict) for f in fields):
        return jsonify({"error": "fields must be a list of objects"}), 400

    payload = None
    if body_mode == "json":
        if isinstance(body_text, str) and body_text.strip():
            try:
                payload = json.loads(body_text)
            except ValueError as exc:
                return jsonify({"error": f"Body must be valid JSON: {exc}"}), 400
        elif body_text is not None and not isinstance(body_text, str):
            return jsonify({"error": "body must be a string"}), 400

    tmp = tempfile.TemporaryDirectory(prefix="acr-upload-")
    try:
        text_fields: dict = {}
        file_fields: dict = {}
        if body_mode in ("form", "urlencoded"):
            for n, field in enumerate(fields):
                key = field.get("key")
                if not isinstance(key, str) or not key.strip():
                    continue
                key = key.strip()
                if field.get("type") == "file":
                    if body_mode != "form":
                        return jsonify({"error": "file fields need Form-data"}), 400
                    part = field.get("upload")
                    if part:
                        up = uploads.get(part) if hasattr(uploads, "get") else None
                        if up is None:
                            return jsonify({"error": f"uploaded file '{part}' is missing"}), 400
                        folder = Path(tmp.name) / str(n)
                        folder.mkdir()
                        dest = folder / _safe_upload_name(up.filename)
                        up.save(dest)
                        file_fields.setdefault(key, []).append(str(dest))
                    elif isinstance(field.get("value"), str) and field["value"].strip():
                        file_fields.setdefault(key, []).append(field["value"].strip())
                else:
                    value = field.get("value", "")
                    if not isinstance(value, str):
                        return jsonify({"error": "field values must be strings"}), 400
                    text_fields[key] = value
            payload = text_fields or None
            # The HTTP client must set Content-Type itself (multipart boundary / urlencoded).
            headers = {k: v for k, v in headers.items() if k.strip().lower() != "content-type"}

        runner = ChainRunner(abs_path)
        if not 0 <= step_index < len(runner.steps) or runner.steps[step_index].manual:
            return jsonify({"error": "step not found or not an API step"}), 404
        context_used = False
        with _run_lock:
            previous = dict(_flow_stores.get(abs_path, {}))
        for name, response in previous.items():
            if name != "vars":
                runner.store.save(name, response)
                context_used = True
        # The panel shows raw YAML values, so ${ENV:...} placeholders still need substituting.
        step = dataclasses.replace(
            runner.steps[step_index],
            method=method,
            url=_substitute_env_vars(url.strip()),
            headers={k.strip(): v for k, v in _substitute_env_vars(headers).items() if k.strip()},
            payload=_substitute_env_vars(payload),
            files=_substitute_env_vars(file_fields) or None,
            body_type={"form": "form", "urlencoded": "urlencoded"}.get(body_mode),
            polling=None,
            retry=False,
            delay=0,
            condition=None,
        )
        resolved_url = runner.resolver.resolve(step.url)
        runner.resolver.resolve(step.headers)
        if step.payload:
            runner.resolver.resolve(step.payload)
        result = runner.executor.execute(step)
    except ReferenceError as exc:
        return jsonify({"error": str(exc), "unresolved_reference": True}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400
    finally:
        tmp.cleanup()

    body = result.response_body
    body_out = json.dumps(body, indent=2, default=str, ensure_ascii=False) if isinstance(body, (dict, list)) else str(body)
    if isinstance(body, dict):
        with _run_lock:
            merged = dict(_flow_stores.get(abs_path, {}))
            merged[step.name] = body
            _flow_stores[abs_path] = merged
    return jsonify({
        "status_code": result.status_code,
        "success": result.success,
        "duration_ms": round(result.duration_ms, 1),
        "error": result.error,
        "response_body": body_out,
        "response_headers": result.response_headers or {},
        "size_bytes": len(body_out.encode("utf-8")),
        "resolved_url": resolved_url,
        "context_used": context_used,
    })


@app.route("/api/run/<run_id>/manual-done", methods=["POST"])
def api_run_manual_done(run_id):
    """Signal that the user has completed the manual step."""
    with _run_lock:
        evt = _manual_events.get(run_id)
        run = _active_runs.get(run_id)
    if not evt or not run:
        return jsonify({"error": "run not found or already finished"}), 404
    if not run.get("waiting_manual"):
        return jsonify({"error": "not waiting for manual step"}), 400
    evt.set()
    return jsonify({"success": True})


# ── Environment variables (.env) ──────────────────────────────────────
_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MAX_ENV_ENTRIES = 500


def _env_candidates() -> list[str]:
    """The .env files a flow can load, in the order ChainRunner reads them (first one wins)."""
    flow_dir = os.path.abspath(_flow_dir)
    ordered = [
        os.path.join(flow_dir, ".env"),
        os.path.join(os.path.dirname(flow_dir), ".env"),
        os.path.join(os.getcwd(), ".env"),
    ]
    seen, unique = set(), []
    for path in ordered:
        real = os.path.realpath(path)
        if real not in seen:
            seen.add(real)
            unique.append(path)
    return unique


def _parse_env_text(text: str) -> list[dict]:
    """Split .env text into lines, tagging KEY=VALUE lines the same way the loader reads them."""
    parsed = []
    for raw in text.splitlines():
        stripped = raw.strip()
        key = value = None
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k, _, v = stripped.partition("=")
            k, v = k.strip(), v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
                v = v[1:-1]
            if k:
                key, value = k, v
        parsed.append({"raw": raw, "key": key, "value": value})
    return parsed


def _format_env_line(key: str, value: str) -> str:
    """Quote so the loader (which only strips one matching outer pair) reads the value back unchanged."""
    if value == "":
        return f"{key}="
    if '"' not in value:
        return f'{key}="{value}"'
    if "'" not in value:
        return f"{key}='{value}'"
    return f"{key}={value}"


def _resolve_env_path(requested: str | None):
    candidates = _env_candidates()
    if requested:
        for path in candidates:
            if os.path.realpath(path) == os.path.realpath(requested):
                return path, candidates
        return None, candidates
    for path in candidates:
        if os.path.isfile(path):
            return path, candidates
    return candidates[0], candidates


def _env_guard():
    if not _same_origin(request) or request.headers.get("X-ACR-Request") != "1":
        return jsonify({"error": "cross-origin requests are not allowed"}), 403
    return None


@app.route("/api/env")
def api_env_get():
    blocked = _env_guard()
    if blocked:
        return blocked
    path, candidates = _resolve_env_path(request.args.get("path"))
    if path is None:
        return jsonify({"error": "unknown .env file"}), 400
    entries = []
    exists = os.path.isfile(path)
    if exists:
        with open(path, "r", encoding="utf-8") as fh:
            for item in _parse_env_text(fh.read()):
                if item["key"] is not None:
                    entries.append({"key": item["key"], "value": item["value"]})
    if request.args.get("summary"):
        return jsonify({"count": len(entries), "path": path})  # no values: used for the sidebar badge
    return jsonify({
        "path": path,
        "exists": exists,
        "entries": entries,
        "files": [{"path": c, "exists": os.path.isfile(c)} for c in candidates],
    })


@app.route("/api/env", methods=["POST"])
def api_env_save():
    """Rewrite one .env file. Comments, blank lines and untouched values are kept as written."""
    blocked = _env_guard()
    if blocked:
        return blocked
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        return jsonify({"error": "entries must be a list"}), 400
    path, _ = _resolve_env_path(data.get("path"))
    if path is None:
        return jsonify({"error": "unknown .env file"}), 400
    if len(data["entries"]) > _MAX_ENV_ENTRIES:
        return jsonify({"error": f"at most {_MAX_ENV_ENTRIES} variables are supported"}), 400

    new: dict[str, str] = {}
    for item in data["entries"]:
        if not isinstance(item, dict) or not isinstance(item.get("key"), str) or not isinstance(item.get("value", ""), str):
            return jsonify({"error": "each entry needs a string key and value"}), 400
        key, value = item["key"].strip(), item.get("value", "")
        if not _ENV_KEY_RE.match(key):
            return jsonify({"error": f"'{key}' is not a valid name (letters, digits and _, not starting with a digit)"}), 400
        if key in new:
            return jsonify({"error": f"'{key}' appears more than once"}), 400
        if "\n" in value or "\r" in value:
            return jsonify({"error": f"'{key}': values cannot contain line breaks"}), 400
        new[key] = value

    existing_text = ""
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as fh:
            existing_text = fh.read()
    lines = _parse_env_text(existing_text)
    old_values = {}
    for ln in lines:
        if ln["key"] is not None and ln["key"] not in old_values:
            old_values[ln["key"]] = ln["value"]

    out, seen = [], set()
    for ln in lines:
        if ln["key"] is None:
            out.append(ln["raw"])
        elif ln["key"] in new and ln["key"] not in seen:
            seen.add(ln["key"])
            out.append(ln["raw"] if new[ln["key"]] == ln["value"] else _format_env_line(ln["key"], new[ln["key"]]))
    for key, value in new.items():
        if key not in seen:
            out.append(_format_env_line(key, value))

    try:
        directory = os.path.dirname(path) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=".env.", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write("\n".join(out) + ("\n" if out else ""))
            if os.path.isfile(path):
                os.chmod(tmp_path, os.stat(path).st_mode & 0o777)
            else:
                os.chmod(tmp_path, 0o600)  # secrets: owner-only for newly created files
            os.replace(tmp_path, path)
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise
    except OSError as exc:
        return jsonify({"error": f"could not write {path}: {exc}"}), 500

    # Apply to this server process so the next run sees the change without a restart.
    for key, old in old_values.items():
        if key not in new and os.environ.get(key) == old:
            os.environ.pop(key, None)
    for key, value in new.items():
        os.environ[key] = value
    return jsonify({"success": True, "path": path, "count": len(new)})


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
