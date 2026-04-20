"""StepExecutor — executes a single API step with reference resolution and logging."""

from __future__ import annotations

import json
import mimetypes
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
import requests
from api_chain_runner.generator import UniqueDataGenerator
from api_chain_runner.logger import ResultLogger
from api_chain_runner.models import LogEntry, StepDefinition, StepResult
from api_chain_runner.pause import PauseController
from api_chain_runner.resolver import ReferenceResolver
from api_chain_runner.store import ResponseStore

IST = timezone(timedelta(hours=5, minutes=30))


class StepExecutor:
    """Executes a single API step: resolve references, generate unique data,
    make the HTTP call, store the response, and log the result.

    Parameters
    ----------
    resolver:
        Resolves ``${step.key}`` references against stored responses.
    generator:
        Generates unique values for marked fields.
    store:
        In-memory response store for cross-step data sharing.
    logger:
        Logs every request/response to CSV or Excel.
    pause_controller:
        Optional controller for pause/resume during polling.
    """

    def __init__(
        self,
        resolver: ReferenceResolver,
        generator: UniqueDataGenerator,
        store: ResponseStore,
        logger: ResultLogger,
        pause_controller: PauseController | None = None,
    ) -> None:
        self.resolver = resolver
        self.generator = generator
        self.store = store
        self.logger = logger
        self.pause_controller = pause_controller

    def execute(self, step: StepDefinition) -> StepResult:
        """Execute a step, with optional polling until expected value is found.

        If the step has a ``polling`` config, the step is re-executed at the
        configured intervals until the response contains the expected value
        at the specified key path, or the max timeout is exceeded.

        Only the final polling result is logged to CSV — intermediate attempts
        are printed to console but not written to the log file.
        """
        if not step.polling:
            return self._execute_with_retry(step)

        polling = step.polling
        start_time = time.monotonic()
        attempt = 0

        # Status-only polling: no key_path, just retry until 2xx
        status_only = polling.key_path is None

        while True:
            # Check for pause before each poll attempt
            if self.pause_controller:
                self.pause_controller.wait_if_paused()

            result = self._execute_once(step, log_to_csv=False)
            attempt += 1

            # Subtract paused time from elapsed so timeout doesn't tick while paused
            paused_time = self.pause_controller.total_paused if self.pause_controller else 0.0
            elapsed = time.monotonic() - start_time - paused_time

            if status_only:
                # Poll until we get a successful HTTP response
                if result.success:
                    print(
                        f"  [polling] '{step.name}' got HTTP {result.status_code} "
                        f"after {attempt} attempt(s) ({elapsed:.1f}s)"
                    )
                    self._log_result(step, result)
                    return result
                else:
                    print(
                        f"  [polling] '{step.name}' attempt {attempt}: "
                        f"HTTP {result.status_code} (waiting for 2xx)"
                    )
            else:
                # Check if the response value matches any of the expected values
                if result.success and isinstance(result.response_body, dict):
                    actual = self._get_nested(result.response_body, polling.key_path)
                    if str(actual) in polling.expected_values:
                        print(
                            f"  [polling] '{step.name}' got expected "
                            f"'{polling.key_path}={actual}' "
                            f"after {attempt} attempt(s) ({elapsed:.1f}s)"
                        )
                        self._log_result(step, result)
                        return result
                    else:
                        print(
                            f"  [polling] '{step.name}' attempt {attempt}: "
                            f"'{polling.key_path}' = '{actual}' "
                            f"(waiting for {polling.expected_values})"
                        )
                elif not result.success:
                    print(
                        f"  [polling] '{step.name}' attempt {attempt}: "
                        f"HTTP {result.status_code} (waiting for 2xx)"
                    )

            # Check timeout before sleeping for next attempt
            if elapsed >= polling.max_timeout:
                if status_only:
                    error_msg = (
                        f"Polling timed out after {elapsed:.1f}s ({attempt} attempts). "
                        f"Expected HTTP 2xx, last status={result.status_code}."
                    )
                else:
                    actual_display = self._get_nested(
                        result.response_body, polling.key_path
                    ) if isinstance(result.response_body, dict) else "N/A"
                    error_msg = (
                        f"Polling timed out after {elapsed:.1f}s ({attempt} attempts). "
                        f"Expected '{polling.key_path}' in {polling.expected_values}, "
                        f"last value='{actual_display}'."
                    )
                print(f"  [polling] '{step.name}' TIMEOUT: {error_msg}")
                timeout_result = StepResult(
                    step_name=step.name,
                    status_code=result.status_code,
                    response_body=result.response_body,
                    duration_ms=(time.monotonic() - start_time - paused_time) * 1000,
                    success=False,
                    error=error_msg,
                )
                self._log_result(step, timeout_result)
                return timeout_result

            # Don't sleep past the timeout
            remaining = polling.max_timeout - elapsed
            actual_wait = min(polling.interval, remaining)
            if actual_wait <= 0:
                continue
            print(
                f"  [polling] '{step.name}' attempt {attempt}: "
                f"waiting {actual_wait:.0f}s before retry..."
            )
            self._interruptible_sleep(actual_wait)

    @staticmethod
    def _get_nested(data, key_path: str):
        """Traverse a dict/list by dot-separated key path.

        Supports array indexing via numeric segments, e.g.
        ``"applications.0.status"`` resolves to ``data["applications"][0]["status"]``.
        Negative indices are supported, e.g. ``"applications.-1.status"``
        resolves to the last element.

        Returns None if any segment is not found.
        """
        current = data
        for key in key_path.split("."):
            if isinstance(current, dict) and key in current:
                current = current[key]
            elif isinstance(current, list) and (key.isdigit() or (key.startswith("-") and key[1:].isdigit())):
                idx = int(key)
                if -len(current) <= idx < len(current):
                    current = current[idx]
                else:
                    return None
            else:
                return None
        return current

    def _evaluate_keys(self, step: StepDefinition, body: dict) -> dict | None:
        """Evaluate eval_keys and print success/failure messages based on condition.

        Returns a dict of extracted key-value pairs (for CSV logging), or None
        if no eval_keys are configured.
        """
        if not step.eval_keys:
            return None

        # Extract values for each eval_key
        eval_values = {}
        for alias, key_path in step.eval_keys.items():
            value = self._get_nested(body, key_path)
            eval_values[alias] = value
            print(f"  [eval] {alias} = {value} (from {key_path})")

        # Check if eval_condition is met
        if step.eval_condition:
            try:
                local_ns = {**eval_values}
                result = eval(step.eval_condition, {"__builtins__": {}}, local_ns)

                if result:
                    eval_values["_eval_result"] = "SUCCESS"
                    if step.success_message:
                        eval_values["_eval_message"] = step.success_message
                        print(f"  [eval] ✅ SUCCESS: {step.success_message}")
                else:
                    eval_values["_eval_result"] = "FAILURE"
                    if step.failure_message:
                        eval_values["_eval_message"] = step.failure_message
                        print(f"  [eval] ❌ FAILURE: {step.failure_message}")
            except Exception as e:
                eval_values["_eval_result"] = "ERROR"
                eval_values["_eval_message"] = str(e)
                print(f"  [eval] ERROR evaluating condition: {e}")

        return eval_values

    def _get_retry_config(self, step: StepDefinition):
        """Resolve the effective retry config for a step."""
        from api_chain_runner.models import RetryConfig, DEFAULT_RETRY_ON
        if step.retry is False:
            return None  # explicitly disabled
        if isinstance(step.retry, RetryConfig):
            return step.retry
        # Default: retry on timeout/connection, 3 attempts
        return RetryConfig()

    def _should_retry(self, result: StepResult, retry_on: list[str]) -> bool:
        """Check if a result matches any of the retry_on conditions."""
        error = (result.error or "").lower()
        # Also check response body for timeout messages (e.g. API Gateway 504)
        body_str = ""
        if isinstance(result.response_body, dict):
            body_str = str(result.response_body).lower()
        elif isinstance(result.response_body, str):
            body_str = result.response_body.lower()

        for condition in retry_on:
            c = condition.lower()
            if c == "timeout" and (
                "timeout" in error or "timed out" in error
                or "timeout" in body_str
                or result.status_code == 504
            ):
                return True
            if c == "connection" and ("connection" in error or "resolve" in error or "refused" in error):
                return True
            if c == "5xx" and 500 <= result.status_code < 600:
                return True
            if c == "4xx" and 400 <= result.status_code < 500:
                return True
        return False

    def _execute_with_retry(self, step: StepDefinition) -> StepResult:
        """Execute a step with automatic retry on transient failures."""
        retry_cfg = self._get_retry_config(step)
        if not retry_cfg or retry_cfg.max_attempts <= 1:
            return self._execute_once(step)

        last_result = None
        for attempt in range(1, retry_cfg.max_attempts + 1):
            is_last = attempt == retry_cfg.max_attempts
            result = self._execute_once(step, log_to_csv=is_last)
            last_result = result

            if result.success or not self._should_retry(result, retry_cfg.retry_on):
                if attempt > 1:
                    if result.success:
                        print(f"         🔄 [retry] Succeeded on attempt {attempt}/{retry_cfg.max_attempts}")
                    else:
                        print(f"         🔄 [retry] Non-retryable error on attempt {attempt} — stopping")
                if not is_last:
                    self._log_result(step, result)
                return result

            reason = result.error or f"HTTP {result.status_code}"
            print(
                f"         🔄 [retry] Attempt {attempt}/{retry_cfg.max_attempts} failed"
                f" — {reason}"
            )

            if not is_last:
                print(f"         🔄 [retry] Waiting {retry_cfg.delay}s before next attempt...")
                self._interruptible_sleep(retry_cfg.delay)

        print(f"         🔄 [retry] All {retry_cfg.max_attempts} attempts exhausted")
        return last_result

    def _execute_once(self, step: StepDefinition, log_to_csv: bool = True) -> StepResult:
        """Execute a single API step.

        Phases:
            1. Resolve ``${step.key}`` references in headers and payload.
            2. Apply unique field generation if ``unique_fields`` is set.
            3. Execute the HTTP request with a 30 s timeout.
            4. Store dict responses in :class:`ResponseStore`.
            5. Log the request/response as a :class:`LogEntry`.

        Args:
            step: The step definition to execute.

        Returns:
            A :class:`StepResult` capturing status code, body, timing, and errors.
        """
        # Phase 1: Resolve references in url, headers, and payload
        resolved_url = self.resolver.resolve(step.url)
        resolved_headers = self.resolver.resolve(step.headers)
        resolved_payload = self.resolver.resolve(step.payload) if step.payload else None

        # Phase 2: Generate unique fields if specified
        if resolved_payload and step.unique_fields:
            resolved_payload = self.generator.apply(resolved_payload, step.unique_fields)

        # Phase 3: Execute HTTP request
        start = time.monotonic()
        opened_files: list = []
        try:
            # Build request kwargs based on whether this is a file upload
            request_kwargs: dict = {
                "method": step.method,
                "url": resolved_url,
                "headers": resolved_headers,
                "timeout": 30,
            }

            opened_files = []
            if step.files:
                # Multipart file upload — open files and attach as multipart/form-data
                # files values can be a string (single file) or a list (multiple files
                # under the same field name, e.g. shop images).
                files_list = []
                for field_name, file_path in step.files.items():
                    paths = file_path if isinstance(file_path, list) else [file_path]
                    for fp in paths:
                        p = Path(fp)
                        mime_type = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
                        fh = open(p, "rb")
                        opened_files.append(fh)
                        files_list.append((field_name, (p.name, fh, mime_type)))
                request_kwargs["files"] = files_list
                # Send any extra payload fields as form data alongside the file
                if resolved_payload:
                    request_kwargs["data"] = resolved_payload
            else:
                request_kwargs["json"] = resolved_payload

            response = requests.request(**request_kwargs)
            duration_ms = (time.monotonic() - start) * 1000

            try:
                body = response.json()
            except ValueError:
                body = response.text

            # Phase 4: Store response for downstream steps
            if isinstance(body, dict):
                self.store.save(step.name, body)

            # Phase 4b: Evaluate eval_keys if specified
            eval_values = None
            if step.eval_keys and isinstance(body, dict):
                eval_values = self._evaluate_keys(step, body)

            result = StepResult(
                step_name=step.name,
                status_code=response.status_code,
                response_body=body,
                duration_ms=duration_ms,
                success=200 <= response.status_code < 300,
                eval_result=eval_values,
            )

        except requests.RequestException as e:
            duration_ms = (time.monotonic() - start) * 1000
            result = StepResult(
                step_name=step.name,
                status_code=-1,
                response_body="",
                duration_ms=duration_ms,
                success=False,
                error=str(e),
            )
        finally:
            for fh in opened_files:
                fh.close()

        # Phase 5: Log regardless of outcome (unless suppressed for polling)
        if log_to_csv:
            self._log_result(step, result)

        return result

    def _log_result(self, step: StepDefinition, result: StepResult) -> None:
        """Write a single result entry to the logger."""
        resolved_url = self.resolver.resolve(step.url)
        resolved_headers = self.resolver.resolve(step.headers)
        resolved_payload = self.resolver.resolve(step.payload) if step.payload else None

        # If eval_keys extracted values, log those instead of the full response
        if result.eval_result is not None:
            response_body_str = json.dumps(result.eval_result)
        elif isinstance(result.response_body, dict):
            response_body_str = json.dumps(result.response_body)
        else:
            response_body_str = str(result.response_body)

        self.logger.log(
            LogEntry(
                timestamp=datetime.now(IST).isoformat(),
                step_name=result.step_name,
                method=step.method,
                url=resolved_url,
                request_headers=json.dumps(resolved_headers),
                request_body=json.dumps(resolved_payload) if resolved_payload else "",
                status_code=result.status_code,
                response_body=response_body_str,
                duration_ms=result.duration_ms,
                error=result.error,
            )
        )

    def _interruptible_sleep(self, seconds: float) -> None:
        """Sleep for the given duration, checking for pause every 0.5s."""
        remaining = seconds
        while remaining > 0:
            if self.pause_controller:
                self.pause_controller.wait_if_paused()
            chunk = min(0.5, remaining)
            time.sleep(chunk)
            remaining -= chunk
