"""Tests for eval_keys, eval_condition, success_message, failure_message, and CSV logging."""

import json
import pytest

from api_chain_runner.executor import StepExecutor
from api_chain_runner.models import StepDefinition, StepResult


# ---------------------------------------------------------------------------
# StepDefinition — new field defaults
# ---------------------------------------------------------------------------

class TestEvalKeysModelDefaults:
    """Verify new fields default to None on StepDefinition."""

    def _make_step(self, **overrides):
        defaults = {
            "name": "test-step",
            "url": "https://example.com",
            "method": "GET",
            "headers": {},
        }
        defaults.update(overrides)
        return StepDefinition(**defaults)

    def test_eval_keys_default_none(self):
        step = self._make_step()
        assert step.eval_keys is None

    def test_eval_condition_default_none(self):
        step = self._make_step()
        assert step.eval_condition is None

    def test_success_message_default_none(self):
        step = self._make_step()
        assert step.success_message is None

    def test_failure_message_default_none(self):
        step = self._make_step()
        assert step.failure_message is None

    def test_eval_keys_custom_value(self):
        step = self._make_step(eval_keys={"score": "features.score"})
        assert step.eval_keys == {"score": "features.score"}

    def test_eval_condition_custom_value(self):
        step = self._make_step(eval_condition="score > 0.5")
        assert step.eval_condition == "score > 0.5"

    def test_success_message_custom_value(self):
        step = self._make_step(success_message="All good")
        assert step.success_message == "All good"

    def test_failure_message_custom_value(self):
        step = self._make_step(failure_message="Something failed")
        assert step.failure_message == "Something failed"

    def test_all_eval_fields_together(self):
        step = self._make_step(
            eval_keys={"a": "path.a", "b": "path.b"},
            eval_condition="a > 0.5 and b > 0.5",
            success_message="Pass",
            failure_message="Fail",
        )
        assert step.eval_keys == {"a": "path.a", "b": "path.b"}
        assert step.eval_condition == "a > 0.5 and b > 0.5"
        assert step.success_message == "Pass"
        assert step.failure_message == "Fail"

    def test_validation_still_passes_with_eval_fields(self):
        step = self._make_step(
            eval_keys={"x": "some.path"},
            eval_condition="x > 1",
            success_message="ok",
            failure_message="nope",
        )
        step.validate()  # should not raise


# ---------------------------------------------------------------------------
# StepResult — eval_result field
# ---------------------------------------------------------------------------

class TestStepResultEvalResult:
    """Verify eval_result field on StepResult."""

    def test_eval_result_default_none(self):
        r = StepResult(step_name="s", status_code=200, response_body={}, duration_ms=0, success=True)
        assert r.eval_result is None

    def test_eval_result_stores_dict(self):
        vals = {"score": 0.9, "_eval_result": "SUCCESS"}
        r = StepResult(step_name="s", status_code=200, response_body={}, duration_ms=0, success=True, eval_result=vals)
        assert r.eval_result == vals
        assert r.eval_result["score"] == 0.9


# ---------------------------------------------------------------------------
# _evaluate_keys — unit tests
# ---------------------------------------------------------------------------

class TestEvaluateKeys:
    """Test StepExecutor._evaluate_keys logic."""

    def _make_executor(self):
        from api_chain_runner.store import ResponseStore
        from api_chain_runner.resolver import ReferenceResolver
        from api_chain_runner.generator import UniqueDataGenerator
        from unittest.mock import MagicMock

        store = ResponseStore()
        resolver = ReferenceResolver(store)
        generator = UniqueDataGenerator()
        logger = MagicMock()
        return StepExecutor(resolver, generator, store, logger)

    def _make_step(self, **overrides):
        defaults = {
            "name": "eval-step",
            "url": "https://example.com",
            "method": "GET",
            "headers": {},
        }
        defaults.update(overrides)
        return StepDefinition(**defaults)

    def test_no_eval_keys_returns_none(self):
        executor = self._make_executor()
        step = self._make_step()
        result = executor._evaluate_keys(step, {"features": {"score": 0.9}})
        assert result is None

    def test_eval_keys_returns_extracted_values(self):
        executor = self._make_executor()
        step = self._make_step(eval_keys={"my_score": "features.score"})
        result = executor._evaluate_keys(step, {"features": {"score": 0.85}})
        assert result["my_score"] == 0.85

    def test_eval_keys_prints_values(self, capsys):
        executor = self._make_executor()
        step = self._make_step(eval_keys={"my_score": "features.score"})
        executor._evaluate_keys(step, {"features": {"score": 0.85}})
        captured = capsys.readouterr()
        assert "my_score = 0.85" in captured.out

    def test_eval_keys_nested_path(self):
        executor = self._make_executor()
        step = self._make_step(eval_keys={"deep": "a.b.c"})
        result = executor._evaluate_keys(step, {"a": {"b": {"c": 42}}})
        assert result["deep"] == 42

    def test_eval_keys_missing_path_returns_none_value(self):
        executor = self._make_executor()
        step = self._make_step(eval_keys={"missing": "does.not.exist"})
        result = executor._evaluate_keys(step, {"features": {"score": 1}})
        assert result["missing"] is None

    def test_eval_condition_success_returns_result(self):
        executor = self._make_executor()
        step = self._make_step(
            eval_keys={"score": "features.score"},
            eval_condition="score > 0.55",
            success_message="Score is above threshold",
            failure_message="Score is below threshold",
        )
        result = executor._evaluate_keys(step, {"features": {"score": 0.9}})
        assert result["_eval_result"] == "SUCCESS"
        assert result["_eval_message"] == "Score is above threshold"

    def test_eval_condition_failure_returns_result(self):
        executor = self._make_executor()
        step = self._make_step(
            eval_keys={"score": "features.score"},
            eval_condition="score > 0.55",
            success_message="Score is above threshold",
            failure_message="Score is below threshold",
        )
        result = executor._evaluate_keys(step, {"features": {"score": 0.3}})
        assert result["_eval_result"] == "FAILURE"
        assert result["_eval_message"] == "Score is below threshold"

    def test_eval_condition_success_prints(self, capsys):
        executor = self._make_executor()
        step = self._make_step(
            eval_keys={"score": "features.score"},
            eval_condition="score > 0.55",
            success_message="Above threshold",
        )
        executor._evaluate_keys(step, {"features": {"score": 0.9}})
        captured = capsys.readouterr()
        assert "SUCCESS" in captured.out
        assert "Above threshold" in captured.out

    def test_eval_condition_failure_prints(self, capsys):
        executor = self._make_executor()
        step = self._make_step(
            eval_keys={"score": "features.score"},
            eval_condition="score > 0.55",
            failure_message="Below threshold",
        )
        executor._evaluate_keys(step, {"features": {"score": 0.3}})
        captured = capsys.readouterr()
        assert "FAILURE" in captured.out
        assert "Below threshold" in captured.out

    def test_eval_condition_multiple_keys_success(self):
        executor = self._make_executor()
        step = self._make_step(
            eval_keys={
                "profile_score": "features.AADHAAR_PROFILE_NAME_MATCH_SCORE",
                "pan_score": "features.AADHAAR_PAN_NAME_MATCH_SCORE",
            },
            eval_condition="profile_score > 0.55 and pan_score > 0.55",
            success_message="Name match - SUCCESS",
            failure_message="Name match - FAILURE",
        )
        body = {"features": {"AADHAAR_PROFILE_NAME_MATCH_SCORE": 1, "AADHAAR_PAN_NAME_MATCH_SCORE": 1}}
        result = executor._evaluate_keys(step, body)
        assert result["_eval_result"] == "SUCCESS"
        assert result["profile_score"] == 1
        assert result["pan_score"] == 1

    def test_eval_condition_multiple_keys_one_fails(self):
        executor = self._make_executor()
        step = self._make_step(
            eval_keys={
                "profile_score": "features.AADHAAR_PROFILE_NAME_MATCH_SCORE",
                "pan_score": "features.AADHAAR_PAN_NAME_MATCH_SCORE",
            },
            eval_condition="profile_score > 0.55 and pan_score > 0.55",
            success_message="Name match - SUCCESS",
            failure_message="Name match - FAILURE",
        )
        body = {"features": {"AADHAAR_PROFILE_NAME_MATCH_SCORE": 1, "AADHAAR_PAN_NAME_MATCH_SCORE": 0.2}}
        result = executor._evaluate_keys(step, body)
        assert result["_eval_result"] == "FAILURE"

    def test_eval_condition_no_messages_no_meta_keys(self):
        executor = self._make_executor()
        step = self._make_step(
            eval_keys={"val": "x"},
            eval_condition="val > 0",
        )
        result = executor._evaluate_keys(step, {"x": 5})
        assert result["val"] == 5
        assert result["_eval_result"] == "SUCCESS"
        assert "_eval_message" not in result

    def test_eval_condition_bad_expression_returns_error(self):
        executor = self._make_executor()
        step = self._make_step(
            eval_keys={"val": "x"},
            eval_condition="val >>> 0",
        )
        result = executor._evaluate_keys(step, {"x": 5})
        assert result["_eval_result"] == "ERROR"
        assert "_eval_message" in result

    def test_eval_keys_without_condition_no_eval_result(self):
        executor = self._make_executor()
        step = self._make_step(eval_keys={"a": "path.a", "b": "path.b"})
        result = executor._evaluate_keys(step, {"path": {"a": 10, "b": 20}})
        assert result["a"] == 10
        assert result["b"] == 20
        assert "_eval_result" not in result

    def test_eval_condition_with_none_value(self):
        executor = self._make_executor()
        step = self._make_step(
            eval_keys={"val": "missing.path"},
            eval_condition="val is not None and val > 0.55",
            success_message="ok",
            failure_message="missing value",
        )
        result = executor._evaluate_keys(step, {"other": 1})
        assert result["_eval_result"] == "FAILURE"
        assert result["_eval_message"] == "missing value"

    def test_eval_condition_equality_check(self):
        executor = self._make_executor()
        step = self._make_step(
            eval_keys={"status": "result.status"},
            eval_condition="status == 'APPROVED'",
            success_message="Approved",
            failure_message="Not approved",
        )
        result = executor._evaluate_keys(step, {"result": {"status": "APPROVED"}})
        assert result["_eval_result"] == "SUCCESS"
        assert result["_eval_message"] == "Approved"

    def test_eval_result_is_json_serializable(self):
        """eval_result dict should be JSON-serializable for CSV logging."""
        executor = self._make_executor()
        step = self._make_step(
            eval_keys={"score": "features.score", "name": "features.name"},
            eval_condition="score > 0.5",
            success_message="ok",
        )
        result = executor._evaluate_keys(step, {"features": {"score": 0.9, "name": "test"}})
        serialized = json.dumps(result)
        parsed = json.loads(serialized)
        assert parsed["score"] == 0.9
        assert parsed["name"] == "test"
        assert parsed["_eval_result"] == "SUCCESS"
