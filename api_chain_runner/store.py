"""In-memory response store for cross-step reference resolution."""

from __future__ import annotations

from typing import Any


class ResponseStore:
    """Stores API step responses keyed by step name.

    Supports dot-notation key path traversal for accessing nested values
    within stored response dicts.
    """

    def __init__(self) -> None:
        self._data: dict[str, dict] = {}

    def save(self, step_name: str, response_data: dict) -> None:
        """Store a response dict under the given step name.

        Args:
            step_name: Unique identifier for the step.
            response_data: The response dict to store.
        """
        self._data[step_name] = response_data

    def get(self, step_name: str, key_path: str) -> Any:
        """Retrieve a value from a stored response using dot-notation traversal.

        Args:
            step_name: The step whose response to look up.
            key_path: Dot-separated path into the response dict
                      (e.g. ``"data.user.id"``).

        Returns:
            The value found at the given key path.

        Raises:
            KeyError: If *step_name* has no stored response or any segment
                      of *key_path* is missing.
        """
        if step_name not in self._data:
            raise KeyError(
                f"Step '{step_name}' not found in response store."
            )

        current: Any = self._data[step_name]
        segments = key_path.split(".")

        for i, segment in enumerate(segments):
            if not isinstance(current, dict) or segment not in current:
                traversed = ".".join(segments[: i + 1])
                raise KeyError(
                    f"Key path '{traversed}' not found in response for step '{step_name}'."
                )
            current = current[segment]

        return current

    def has(self, step_name: str) -> bool:
        """Check whether a response exists for the given step name."""
        return step_name in self._data

    def get_raw(self, step_name: str) -> dict:
        """Return the full stored response dict for a step.

        Args:
            step_name: The step whose response to retrieve.

        Returns:
            The full response dict.

        Raises:
            KeyError: If *step_name* has no stored response.
        """
        if step_name not in self._data:
            raise KeyError(
                f"Step '{step_name}' not found in response store."
            )
        return self._data[step_name]
