"""Tests for api_chain_runner.models."""

import pytest

from api_chain_runner.models import (
    ChainResult,
    ConfigurationError,
    LogEntry,
    StepDefinition,
    StepResult,
    validate_steps,
)


# ---------------------------------------------------------------------------
# StepDefinition validation
# ---------------------------------------------------------------------------

class TestStepDefinitionValidation:
    def _make_step(self, **overrides):
        defaults = {
            "name": "auth",
            "url": "https://example.com/api",
            "method": "POST",
            "headers": {"Content-Type": "application/json"},
        }
        defaults.update(overrides)
        return StepDefinition(**defaults)

    def test_valid_step_passes(self):
        step = self._make_step()
        step.validate()  # should not raise

    @pytest.mark.parametrize("method", ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
    def test_all_valid_http_methods(self, method):
        step = self._make_step(method=method)
        step.validate()

    def test_invalid_method_raises(self):
        step = self._make_step(method="INVALID")
        with pytest.raises(ConfigurationError, match="invalid HTTP method"):
            step.validate()

    def test_empty_name_raises(self):
        step = self._make_step(name="")
        with pytest.raises(ConfigurationError, match="name must be a non-empty"):
            step.validate()

    def test_whitespace_name_raises(self):
        step = self._make_step(name="   ")
        with pytest.raises(ConfigurationError, match="name must be a non-empty"):
            step.validate()

    def test_empty_url_raises(self):
        step = self._make_step(url="")
        with pytest.raises(ConfigurationError, match="url must be a non-empty"):
            step.validate()

    def test_whitespace_url_raises(self):
        step = self._make_step(url="   ")
        with pytest.raises(ConfigurationError, match="url must be a non-empty"):
            step.validate()

    def test_valid_unique_fields(self):
        step = self._make_step(unique_fields={"email_field": "email", "pan_field": "pan", "mobile_field": "mobile"})
        step.validate()

    def test_invalid_generator_type_raises(self):
        step = self._make_step(unique_fields={"field": "unknown"})
        with pytest.raises(ConfigurationError, match="invalid generator type"):
            step.validate()

    def test_defaults(self):
        step = self._make_step()
        assert step.payload is None
        assert step.unique_fields is None
        assert step.extract is None
        assert step.delay == 0
        assert step.print_keys is None
        assert step.continue_on_error is True

    def test_delay_default_is_zero(self):
        step = self._make_step()
        assert step.delay == 0

    def test_delay_custom_value(self):
        step = self._make_step(delay=20)
        assert step.delay == 20

    def test_print_keys_default_is_none(self):
        step = self._make_step()
        assert step.print_keys is None

    def test_print_keys_custom_value(self):
        step = self._make_step(print_keys=["leadId", "userId"])
        assert step.print_keys == ["leadId", "userId"]

    def test_manual_step_valid(self):
        step = StepDefinition(
            name="manual-task", url="", method="", headers={},
            manual=True, instruction="Do something manually",
        )
        step.validate()  # should not raise

    def test_manual_step_without_instruction_raises(self):
        step = StepDefinition(
            name="manual-task", url="", method="", headers={},
            manual=True,
        )
        with pytest.raises(ConfigurationError, match="manual steps must have an 'instruction'"):
            step.validate()

    def test_manual_step_skips_url_method_validation(self):
        step = StepDefinition(
            name="manual-task", url="", method="", headers={},
            manual=True, instruction="Do this",
        )
        step.validate()  # should not raise despite empty url/method

    def test_condition_config_single(self):
        from api_chain_runner.models import ConditionConfig
        cond = ConditionConfig(step="auth", key_path="status", expected_value="ok")
        step = self._make_step(condition=[cond])
        assert len(step.condition) == 1
        assert step.condition[0].step == "auth"
        assert step.condition[0].expected_value == "ok"

    def test_condition_config_multiple(self):
        from api_chain_runner.models import ConditionConfig
        conds = [
            ConditionConfig(step="check-status", key_path="kybRemarks.udyamFetchStatus", expected_value="SUCCESS"),
            ConditionConfig(step="check-status", key_path="kybRemarks.udyamFormFilled", expected_value="SUCCESS"),
        ]
        step = self._make_step(condition=conds)
        assert len(step.condition) == 2
        assert step.condition[0].key_path == "kybRemarks.udyamFetchStatus"
        assert step.condition[1].key_path == "kybRemarks.udyamFormFilled"


# ---------------------------------------------------------------------------
# validate_steps (cross-step uniqueness)
# ---------------------------------------------------------------------------

class TestValidateSteps:
    def test_unique_names_pass(self):
        steps = [
            StepDefinition(name="a", url="https://a.com", method="GET", headers={}),
            StepDefinition(name="b", url="https://b.com", method="POST", headers={}),
        ]
        validate_steps(steps)  # should not raise

    def test_duplicate_names_raise(self):
        steps = [
            StepDefinition(name="auth", url="https://a.com", method="GET", headers={}),
            StepDefinition(name="auth", url="https://b.com", method="POST", headers={}),
        ]
        with pytest.raises(ConfigurationError, match="Duplicate step name"):
            validate_steps(steps)

    def test_empty_list_passes(self):
        validate_steps([])


# ---------------------------------------------------------------------------
# Dataclass construction smoke tests
# ---------------------------------------------------------------------------

class TestDataclassConstruction:
    def test_step_result(self):
        r = StepResult(step_name="auth", status_code=200, response_body={"ok": True}, duration_ms=42.5, success=True)
        assert r.step_name == "auth"
        assert r.error is None

    def test_log_entry(self):
        e = LogEntry(
            timestamp="2024-01-01T00:00:00",
            step_name="auth",
            method="POST",
            url="https://example.com",
            request_headers="{}",
            request_body="{}",
            status_code=200,
            response_body="{}",
            duration_ms=10.0,
        )
        assert e.error is None

    def test_chain_result_defaults(self):
        c = ChainResult(total_steps=2, passed=1, failed=1)
        assert c.results == []

    def test_chain_result_with_results(self):
        r = StepResult(step_name="s", status_code=200, response_body="", duration_ms=0, success=True)
        c = ChainResult(total_steps=1, passed=1, failed=0, results=[r])
        assert len(c.results) == 1
