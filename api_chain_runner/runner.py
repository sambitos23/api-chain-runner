"""ChainRunner — top-level orchestrator for chained API execution."""

from __future__ import annotations
import os
import re
import time
import yaml
from datetime import datetime, timezone, timedelta
from pathlib import Path
from api_chain_runner.executor import StepExecutor
from api_chain_runner.generator import UniqueDataGenerator
from api_chain_runner.logger import ResultLogger
from api_chain_runner.models import (
    ChainResult,
    ConditionConfig,
    ConfigurationError,
    LogEntry,
    PollingConfig,
    StepDefinition,
    StepResult,
    validate_steps,
)
from api_chain_runner.pause import PauseController
from api_chain_runner.resolver import ReferenceResolver
from api_chain_runner.store import ResponseStore


IST = timezone(timedelta(hours=5, minutes=30))


def _load_env_file(env_path: str) -> None:
    """Load key=value pairs from a .env file into os.environ.

    Skips blank lines and comments. Strips quotes. Does not override
    existing environment variables.
    """
    if not os.path.isfile(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            if key and key not in os.environ:
                os.environ[key] = value


def _substitute_env_vars(obj):
    """Recursively substitute ``${ENV:VAR_NAME}`` placeholders."""
    if isinstance(obj, dict):
        return {k: _substitute_env_vars(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_substitute_env_vars(item) for item in obj]
    if isinstance(obj, str):
        def _replace(match):
            return os.environ.get(match.group(1), match.group(0))
        return re.sub(r"\$\{ENV:([^}]+)\}", _replace, obj)
    return obj


class ChainRunner:
    """Top-level orchestrator that loads a chain configuration and executes
    steps in order.

    Parameters
    ----------
    config_path:
        Path to a YAML file describing the chain of API steps.
    """

    def __init__(self, config_path: str, env_file: str | None = None) -> None:
        self.config_path = config_path

        # Auto-load .env files (config dir → parent dir → cwd → explicit)
        config_dir = str(Path(config_path).resolve().parent)
        _load_env_file(os.path.join(config_dir, ".env"))
        _load_env_file(os.path.join(config_dir, "..", ".env"))
        _load_env_file(".env")
        if env_file:
            _load_env_file(env_file)

        # Core components
        self.store = ResponseStore()
        self.resolver = ReferenceResolver(self.store)
        self.generator = UniqueDataGenerator()
        self.pause_controller = PauseController()

        # Derive default output path from config filename
        config_stem = Path(config_path).stem
        output_path = f"{config_stem}_results.csv"
        self.logger = ResultLogger(output_path)

        self.executor = StepExecutor(
            resolver=self.resolver,
            generator=self.generator,
            store=self.store,
            logger=self.logger,
            pause_controller=self.pause_controller,
        )

        # Load and validate the chain
        self.steps = self.load_chain(config_path)

        # Pre-seed store with top-level variables (accessible as ${vars.key})
        self._load_variables(config_path)

    def load_chain(self, config_path: str) -> list[StepDefinition]:
        """Parse a YAML config file into a list of validated step definitions.

        Args:
            config_path: Path to the YAML configuration file.

        Returns:
            A list of :class:`StepDefinition` objects.

        Raises:
            ConfigurationError: If the file cannot be read, is not valid YAML,
                or contains invalid step definitions.
        """
        try:
            with open(config_path, "r", encoding="utf-8") as fh:
                raw = yaml.safe_load(fh)
        except FileNotFoundError as exc:
            raise ConfigurationError(
                f"Configuration file not found: {config_path}"
            ) from exc
        except yaml.YAMLError as exc:
            raise ConfigurationError(
                f"Invalid YAML in configuration file: {exc}"
            ) from exc

        # Substitute ${ENV:VAR_NAME} placeholders
        raw = _substitute_env_vars(raw)

        if not isinstance(raw, dict) or "chain" not in raw:
            raise ConfigurationError(
                "Configuration must contain a top-level 'chain' key."
            )

        chain_list = raw["chain"]
        if not isinstance(chain_list, list) or len(chain_list) == 0:
            raise ConfigurationError(
                "'chain' must be a non-empty list of step definitions."
            )

        steps: list[StepDefinition] = []
        for idx, entry in enumerate(chain_list):
            if not isinstance(entry, dict):
                raise ConfigurationError(
                    f"Step at index {idx} must be a mapping, got {type(entry).__name__}."
                )

            # name is always required
            if "name" not in entry:
                raise ConfigurationError(
                    f"Step at index {idx} is missing required field 'name'."
                )

            # Parse condition config if present (single dict or list of dicts)
            condition = None
            if "condition" in entry:
                c = entry["condition"]
                if isinstance(c, dict):
                    c_list = [c]
                elif isinstance(c, list):
                    c_list = c
                else:
                    raise ConfigurationError(
                        f"Step '{entry['name']}': 'condition' must be a mapping or list of mappings."
                    )
                conditions = []
                for ci in c_list:
                    if not isinstance(ci, dict):
                        raise ConfigurationError(
                            f"Step '{entry['name']}': each condition must be a mapping."
                        )
                    for req_field in ("step", "key_path", "expected_value"):
                        if req_field not in ci:
                            raise ConfigurationError(
                                f"Step '{entry['name']}': condition missing required field '{req_field}'."
                            )
                    conditions.append(ConditionConfig(
                        step=ci["step"],
                        key_path=ci["key_path"],
                        expected_value=str(ci["expected_value"]),
                    ))
                condition = conditions

            # Handle manual steps (no url/method required)
            if entry.get("manual", False):
                step = StepDefinition(
                    name=entry["name"],
                    url="",
                    method="",
                    headers={},
                    manual=True,
                    instruction=entry.get("instruction", ""),
                    print_ref=entry.get("print_ref"),
                    condition=condition,
                    delay=int(entry.get("delay", 0)),
                    continue_on_error=entry.get("continue_on_error", True),
                    eval_keys=entry.get("eval_keys"),
                    eval_condition=entry.get("eval_condition"),
                    success_message=entry.get("success_message"),
                    failure_message=entry.get("failure_message"),
                )
                steps.append(step)
                continue

            # Check required fields for API steps
            for required in ("url", "method"):
                if required not in entry:
                    raise ConfigurationError(
                        f"Step at index {idx} is missing required field '{required}'."
                    )

            # Parse polling config if present
            polling = None
            if "polling" in entry:
                p = entry["polling"]
                if not isinstance(p, dict):
                    raise ConfigurationError(
                        f"Step '{entry['name']}': 'polling' must be a mapping."
                    )
                if "interval" not in p:
                    raise ConfigurationError(
                        f"Step '{entry['name']}': polling missing required field 'interval'."
                    )

                # key_path and expected_values are optional — if omitted, polls until 2xx
                key_path = p.get("key_path")
                ev = None
                if key_path is not None:
                    if "expected_values" not in p:
                        raise ConfigurationError(
                            f"Step '{entry['name']}': polling with 'key_path' requires 'expected_values'."
                        )
                    ev = p["expected_values"]
                    if isinstance(ev, str):
                        ev = [ev]
                    ev = [str(v) for v in ev]

                polling = PollingConfig(
                    interval=int(p["interval"]),
                    max_timeout=p.get("max_timeout", 120),
                    key_path=key_path,
                    expected_values=ev,
                )

            step = StepDefinition(
                name=entry["name"],
                url=entry["url"],
                method=entry["method"],
                headers=entry.get("headers", {}),
                payload=entry.get("payload"),
                files=entry.get("files"),
                unique_fields=entry.get("unique_fields"),
                extract=entry.get("extract"),
                polling=polling,
                delay=int(entry.get("delay", 0)),
                print_keys=entry.get("print_keys"),
                condition=condition,
                continue_on_error=entry.get("continue_on_error", True),
                eval_keys=entry.get("eval_keys"),
                eval_condition=entry.get("eval_condition"),
                success_message=entry.get("success_message"),
                failure_message=entry.get("failure_message"),
            )
            steps.append(step)

        # Validate individual steps and cross-step uniqueness
        validate_steps(steps)

        return steps

    def _load_variables(self, config_path: str) -> None:
        """Load top-level 'variables' from YAML and pre-seed the store as 'vars'.

        This allows referencing variables in steps as ``${vars.my_token}``.
        """
        with open(config_path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
        raw = _substitute_env_vars(raw)
        variables = raw.get("variables")
        if variables and isinstance(variables, dict):
            self.store.save("vars", variables)

    def run(self) -> ChainResult:
        """Execute all steps in the chain sequentially.

        For each step, the executor resolves references, generates unique
        data, makes the HTTP call, stores the response, and logs the result.

        If a step fails and its ``continue_on_error`` flag is ``False``,
        the chain aborts immediately.  :class:`ReferenceError` exceptions
        are caught per-step and recorded as failures.

        Returns:
            A :class:`ChainResult` summarising pass/fail counts and
            individual step results.
        """
        results: list[StepResult] = []
        total = len(self.steps)
        chain_name = Path(self.config_path).stem

        print(f"\n{'='*60}")
        print(f"  Running chain: {chain_name} ({total} steps)")
        print("  Press 'p' to pause, 'r' to resume")
        print(f"{'='*60}\n")

        self.pause_controller.start()

        try:
            for idx, step in enumerate(self.steps, 1):
                self.pause_controller.wait_if_paused()

                # Check conditions — skip step if any condition not met
                if step.condition:
                    skip = False
                    for cond in step.condition:
                        if self.store.has(cond.step):
                            stored = self.store.get_raw(cond.step)
                            actual = StepExecutor._get_nested(stored, cond.key_path)
                            if str(actual) != cond.expected_value:
                                print(f"[{idx}/{total}] ⏭ {step.name} — skipped (condition not met: "
                                      f"{cond.key_path}='{actual}', expected '{cond.expected_value}')")
                                skip = True
                                break
                        else:
                            print(f"[{idx}/{total}] ⏭ {step.name} — skipped (step '{cond.step}' not found)")
                            skip = True
                            break
                    if skip:
                        continue

                # Handle manual steps
                if step.manual:
                    result = self._handle_manual_step(idx, total, step)
                    results.append(result)
                    continue

                print(f"[{idx}/{total}] ▶ {step.name} running....")

                if step.delay > 0:
                    print(f"         ⏳ Waiting {step.delay}s before executing...")
                    self._interruptible_sleep(step.delay)

                try:
                    result = self.executor.execute(step)
                except ReferenceError as exc:
                    result = StepResult(
                        step_name=step.name,
                        status_code=-1,
                        response_body="",
                        duration_ms=0.0,
                        success=False,
                        error=str(exc),
                    )
                    self.logger.log(
                        LogEntry(
                            timestamp=datetime.now(IST).isoformat(),
                            step_name=step.name,
                            method=step.method,
                            url=step.url,
                            request_headers="{}",
                            request_body="",
                            status_code=-1,
                            response_body="",
                            duration_ms=0.0,
                            error=str(exc),
                        )
                    )

                if result.success:
                    print(f"         ✅ Passed — HTTP {result.status_code} ({result.duration_ms:.0f}ms)")
                else:
                    error_info = f" — {result.error}" if result.error else ""
                    print(f"         ❌ Failed — HTTP {result.status_code} ({result.duration_ms:.0f}ms){error_info}")

                if step.print_keys and isinstance(result.response_body, dict):
                    for key_path in step.print_keys:
                        value = StepExecutor._get_nested(result.response_body, key_path)
                        print(f"         📋 {key_path} = {value}")

                results.append(result)

                if not result.success and not step.continue_on_error:
                    print(f"\n⛔ Chain aborted at step '{step.name}' (continue_on_error=false)")
                    break
        finally:
            self.pause_controller.stop()

        self.logger.finalize()

        passed = sum(1 for r in results if r.success)
        failed = len(results) - passed

        print(f"\n{'='*60}")
        print(f"  Done: {passed} passed, {failed} failed out of {len(results)} steps")
        print(f"  Results saved to: {self.logger._output_path}")
        print(f"{'='*60}\n")

        return ChainResult(
            total_steps=len(results),
            passed=passed,
            failed=failed,
            results=results,
        )

    def _interruptible_sleep(self, seconds: float) -> None:
        """Sleep for the given duration, but check for pause every 0.5s."""
        remaining = seconds
        while remaining > 0:
            self.pause_controller.wait_if_paused()
            chunk = min(0.5, remaining)
            time.sleep(chunk)
            remaining -= chunk

    def _handle_manual_step(self, idx: int, total: int, step: StepDefinition) -> StepResult:
        """Display instruction and wait for user to press Enter."""
        # Temporarily stop the keyboard listener so input() works cleanly
        self.pause_controller.stop()

        print(f"[{idx}/{total}] ▶ {step.name}")
        print(f"         ┌{'─'*50}┐")
        print(f"         │  📋 MANUAL STEP{' '*35}│")
        print(f"         │{' '*51}│")
        if step.instruction:
            for line in step.instruction.strip().splitlines():
                padded = line[:49].ljust(49)
                print(f"         │  {padded}│")
        print(f"         │{' '*51}│")
        print(f"         └{'─'*50}┘")

        # Print references from previous steps if specified
        if step.print_ref:
            for ref in step.print_ref:
                parts = ref.split(".", 1)
                if len(parts) == 2 and self.store.has(parts[0]):
                    stored = self.store.get_raw(parts[0])
                    value = StepExecutor._get_nested(stored, parts[1])
                    print(f"         📋 {ref} = {value}")

        print("         ⏳ Waiting for you to complete the task...")
        input("         Press Enter to continue ▶ ")

        # Restart the keyboard listener
        self.pause_controller = PauseController()
        self.pause_controller.start()
        self.executor.pause_controller = self.pause_controller

        print("         ✅ Manual step completed")

        # Log the manual step
        self.logger.log(
            LogEntry(
                timestamp=datetime.now(IST).isoformat(),
                step_name=step.name,
                method="MANUAL",
                url="",
                request_headers="{}",
                request_body="",
                status_code=0,
                response_body="MANUAL — completed by user",
                duration_ms=0.0,
            )
        )

        return StepResult(
            step_name=step.name,
            status_code=0,
            response_body="MANUAL — completed by user",
            duration_ms=0.0,
            success=True,
        )
