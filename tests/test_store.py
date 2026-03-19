"""Tests for api_chain_runner.store.ResponseStore."""

import pytest

from api_chain_runner.store import ResponseStore


class TestSaveAndGetFlat:
    """Test save and get with flat (single-segment) key paths."""

    def test_get_flat_string_value(self):
        store = ResponseStore()
        store.save("auth", {"token": "abc123"})
        assert store.get("auth", "token") == "abc123"

    def test_get_flat_integer_value(self):
        store = ResponseStore()
        store.save("step1", {"status": 200})
        assert store.get("step1", "status") == 200

    def test_get_flat_boolean_value(self):
        store = ResponseStore()
        store.save("step1", {"success": True})
        assert store.get("step1", "success") is True

    def test_get_multiple_keys_from_same_step(self):
        store = ResponseStore()
        store.save("auth", {"idToken": "tok", "refreshToken": "ref"})
        assert store.get("auth", "idToken") == "tok"
        assert store.get("auth", "refreshToken") == "ref"


class TestSaveAndGetNested:
    """Test save and get with nested (multi-segment) key paths."""

    def test_get_two_level_nested(self):
        store = ResponseStore()
        store.save("step1", {"data": {"id": 42}})
        assert store.get("step1", "data.id") == 42

    def test_get_three_level_nested(self):
        store = ResponseStore()
        store.save("step1", {"data": {"user": {"id": 99}}})
        assert store.get("step1", "data.user.id") == 99

    def test_get_nested_returns_sub_dict(self):
        store = ResponseStore()
        store.save("step1", {"data": {"user": {"id": 1, "name": "Alice"}}})
        assert store.get("step1", "data.user") == {"id": 1, "name": "Alice"}


class TestHas:
    """Test has() for existing and non-existing steps."""

    def test_has_returns_true_for_saved_step(self):
        store = ResponseStore()
        store.save("auth", {"token": "x"})
        assert store.has("auth") is True

    def test_has_returns_false_for_missing_step(self):
        store = ResponseStore()
        assert store.has("auth") is False

    def test_has_returns_false_after_no_saves(self):
        store = ResponseStore()
        assert store.has("anything") is False

    def test_has_distinguishes_different_step_names(self):
        store = ResponseStore()
        store.save("step_a", {"v": 1})
        assert store.has("step_a") is True
        assert store.has("step_b") is False


class TestErrorMissingStep:
    """Test KeyError raised when step name is not in the store."""

    def test_get_missing_step_raises_key_error(self):
        store = ResponseStore()
        with pytest.raises(KeyError, match="Step 'missing' not found"):
            store.get("missing", "key")

    def test_get_missing_step_after_saving_other(self):
        store = ResponseStore()
        store.save("auth", {"token": "x"})
        with pytest.raises(KeyError, match="Step 'other' not found"):
            store.get("other", "token")


class TestErrorInvalidKeyPath:
    """Test KeyError raised for invalid/missing key paths within a stored response."""

    def test_missing_flat_key(self):
        store = ResponseStore()
        store.save("step1", {"token": "abc"})
        with pytest.raises(KeyError, match="Key path 'missing' not found"):
            store.get("step1", "missing")

    def test_missing_nested_key_at_second_level(self):
        store = ResponseStore()
        store.save("step1", {"data": {"name": "Alice"}})
        with pytest.raises(KeyError, match="Key path 'data.missing' not found"):
            store.get("step1", "data.missing")

    def test_traversal_through_non_dict_value(self):
        store = ResponseStore()
        store.save("step1", {"value": 42})
        with pytest.raises(KeyError, match="Key path 'value.nested' not found"):
            store.get("step1", "value.nested")


class TestGetRaw:
    """Test get_raw() for retrieving full response dicts."""

    def test_get_raw_returns_full_dict(self):
        store = ResponseStore()
        data = {"token": "abc", "status": 200}
        store.save("auth", data)
        assert store.get_raw("auth") == data

    def test_get_raw_missing_step_raises(self):
        store = ResponseStore()
        with pytest.raises(KeyError, match="Step 'missing' not found"):
            store.get_raw("missing")
