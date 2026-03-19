"""Tests for api_chain_runner.executor._get_nested (array indexing and nested traversal)."""

import pytest

from api_chain_runner.executor import StepExecutor


class TestGetNestedPositiveIndex:
    """Test _get_nested with positive array indices."""

    def test_first_element(self):
        data = {"items": [{"id": 1}, {"id": 2}, {"id": 3}]}
        assert StepExecutor._get_nested(data, "items.0.id") == 1

    def test_middle_element(self):
        data = {"items": [{"id": 1}, {"id": 2}, {"id": 3}]}
        assert StepExecutor._get_nested(data, "items.1.id") == 2

    def test_out_of_bounds_returns_none(self):
        data = {"items": [{"id": 1}]}
        assert StepExecutor._get_nested(data, "items.5.id") is None


class TestGetNestedNegativeIndex:
    """Test _get_nested with negative array indices."""

    def test_last_element(self):
        data = {"applications": [{"status": "OLD"}, {"status": "LATEST"}]}
        assert StepExecutor._get_nested(data, "applications.-1.status") == "LATEST"

    def test_second_to_last_element(self):
        data = {"applications": [{"status": "FIRST"}, {"status": "SECOND"}, {"status": "THIRD"}]}
        assert StepExecutor._get_nested(data, "applications.-2.status") == "SECOND"

    def test_negative_index_single_element(self):
        data = {"items": [{"val": "only"}]}
        assert StepExecutor._get_nested(data, "items.-1.val") == "only"

    def test_negative_index_out_of_bounds_returns_none(self):
        data = {"items": [{"val": "a"}]}
        assert StepExecutor._get_nested(data, "items.-2.val") is None

    def test_negative_index_on_nested_array(self):
        data = {"data": {"results": [10, 20, 30]}}
        assert StepExecutor._get_nested(data, "data.results.-1") == 30


class TestGetNestedDictTraversal:
    """Test _get_nested with plain dict key paths (no arrays)."""

    def test_flat_key(self):
        data = {"token": "abc123"}
        assert StepExecutor._get_nested(data, "token") == "abc123"

    def test_nested_key(self):
        data = {"data": {"user": {"name": "Alice"}}}
        assert StepExecutor._get_nested(data, "data.user.name") == "Alice"

    def test_missing_key_returns_none(self):
        data = {"token": "abc"}
        assert StepExecutor._get_nested(data, "missing") is None

    def test_missing_nested_key_returns_none(self):
        data = {"data": {"user": "Alice"}}
        assert StepExecutor._get_nested(data, "data.missing") is None

    def test_traversal_through_non_dict_returns_none(self):
        data = {"value": 42}
        assert StepExecutor._get_nested(data, "value.nested") is None
