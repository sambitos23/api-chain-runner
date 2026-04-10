"""Data models and validation for API Chain Runner."""

from __future__ import annotations

from dataclasses import dataclass, field


VALID_HTTP_METHODS = frozenset(
    {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}
)

VALID_GENERATOR_TYPES = frozenset({"email", "pan", "mobile", "udyam"})


class ConfigurationError(Exception):
    """Raised when chain configuration is invalid."""


@dataclass
class PollingConfig:
    """Polling configuration for a step that needs to wait for a specific value.

    If ``key_path`` and ``expected_values`` are omitted, polling retries until
    the endpoint returns a successful HTTP response (2xx).
    """

    interval: int  # retry interval in seconds (e.g. 5)
    max_timeout: int = 120  # max total polling time in seconds
    key_path: str | None = None  # dot-notation path in response to check (e.g. "status")
    expected_values: list[str] | None = None  # list of acceptable values (e.g. ["APPROVED", "COMPLETED"])


@dataclass
class ConditionConfig:
    """Condition to check before executing a step."""

    step: str  # name of the previous step whose response to check
    key_path: str  # dot-notation path in that step's response
    expected_value: str  # value that must match for this step to run


# Default retry: 3 attempts on timeout/connection/5xx errors
DEFAULT_RETRY_ON = ["timeout", "connection", "5xx"]


@dataclass
class RetryConfig:
    """Retry configuration for a step that may fail transiently.

    ``retry_on`` controls which error types trigger a retry:
    - ``"timeout"`` — request timed out
    - ``"connection"`` — connection refused / DNS failure
    - ``"5xx"`` — server returned 500-599
    - ``"4xx"`` — server returned 400-499 (use with caution)
    """

    max_attempts: int = 3
    delay: int = 5  # seconds between retries
    retry_on: list[str] = field(default_factory=lambda: list(DEFAULT_RETRY_ON))


@dataclass
class StepDefinition:
    """A single step in an API chain."""

    name: str
    url: str
    method: str
    headers: dict[str, str]
    payload: dict | None = None
    files: dict[str, str] | None = None  # field_name -> file_path for multipart uploads
    unique_fields: dict[str, str] | None = None
    extract: dict[str, str] | None = None
    polling: PollingConfig | None = None
    delay: int = 0  # seconds to wait before executing this step
    print_keys: list[str] | None = None  # response key paths to print after execution
    manual: bool = False  # if True, this is a manual step (no HTTP call)
    instruction: str | None = None  # instruction text shown for manual steps
    print_ref: list[str] | None = None  # references to print from previous steps (e.g. "step.key")
    condition: list[ConditionConfig] | None = None  # conditional execution (all must pass)
    continue_on_error: bool = True
    retry: RetryConfig | None | bool = None  # None=use default, False=disable, RetryConfig=custom
    eval_keys: dict[str, str] | None = None  # key alias -> dot-notation path for evaluation
    eval_condition: str | None = None  # Python expression to evaluate using eval_keys values
    success_message: str | None = None  # message to print on success condition
    failure_message: str | None = None  # message to print on failure condition

    def validate(self) -> None:
        """Validate this step definition.

        Raises:
            ConfigurationError: If any field is invalid.
        """
        if not self.name or not self.name.strip():
            raise ConfigurationError("Step name must be a non-empty string.")

        # Manual steps don't need url/method
        if self.manual:
            if not self.instruction:
                raise ConfigurationError(
                    f"Step '{self.name}': manual steps must have an 'instruction' field."
                )
            return

        if not self.url or not self.url.strip():
            raise ConfigurationError(
                f"Step '{self.name}': url must be a non-empty string."
            )

        method_upper = self.method.upper() if self.method else ""
        if method_upper not in VALID_HTTP_METHODS:
            raise ConfigurationError(
                f"Step '{self.name}': invalid HTTP method '{self.method}'. "
                f"Must be one of {sorted(VALID_HTTP_METHODS)}."
            )

        if self.unique_fields:
            for field_path, gen_type in self.unique_fields.items():
                # Allow pan-p, pan-c etc. to control PAN's 4th character
                is_pan_with_char = gen_type.startswith("pan-") and len(gen_type) == 5
                if gen_type not in VALID_GENERATOR_TYPES and not is_pan_with_char:
                    raise ConfigurationError(
                        f"Step '{self.name}': invalid generator type '{gen_type}' "
                        f"for field '{field_path}'. "
                        f"Must be one of {sorted(VALID_GENERATOR_TYPES)} or pan-[PCHFAT]."
                    )


@dataclass
class StepResult:
    """Result of executing a single API step."""

    step_name: str
    status_code: int
    response_body: dict | str
    duration_ms: float
    success: bool
    error: str | None = None
    eval_result: dict | None = None  # extracted eval_keys values (logged to CSV instead of full response)


@dataclass
class LogEntry:
    """A single log row capturing full request/response data."""

    timestamp: str
    step_name: str
    method: str
    url: str
    request_headers: str  # JSON-serialized
    request_body: str  # JSON-serialized
    status_code: int
    response_body: str  # JSON-serialized
    duration_ms: float
    error: str | None = None


@dataclass
class ChainResult:
    """Summary of an entire chain execution."""

    total_steps: int
    passed: int
    failed: int
    results: list[StepResult] = field(default_factory=list)


def validate_steps(steps: list[StepDefinition]) -> None:
    """Validate a list of step definitions, including cross-step uniqueness.

    Raises:
        ConfigurationError: If any step is invalid or names are duplicated.
    """
    seen_names: set[str] = set()
    for step in steps:
        step.validate()
        if step.name in seen_names:
            raise ConfigurationError(
                f"Duplicate step name '{step.name}'. Step names must be unique."
            )
        seen_names.add(step.name)
