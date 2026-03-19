"""Reference resolver for dynamic ${step.key.path} expressions."""

from __future__ import annotations

import re
from typing import Any

from api_chain_runner.store import ResponseStore


class ReferenceResolver:
    """Resolves ``${step_name.key_path}`` references against a :class:`ResponseStore`.

    Recursively traverses dicts, lists, and strings.  Full-string references
    (where the entire string is a single ``${...}`` expression) preserve the
    original value type; embedded references are substituted as strings.

    The resolver never mutates the original template.
    """

    _REF_PATTERN = re.compile(r"\$\{([^}]+)\}")

    def __init__(self, store: ResponseStore) -> None:
        self._store = store

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(self, template: Any) -> Any:
        """Recursively resolve all ``${step.key}`` references in *template*.

        Args:
            template: A dict, list, string, or primitive value.

        Returns:
            A deep copy of *template* with every ``${step.key.path}``
            expression replaced by the corresponding stored value.

        Raises:
            ReferenceError: If a referenced step or key path does not exist.
        """
        if isinstance(template, dict):
            return {k: self.resolve(v) for k, v in template.items()}

        if isinstance(template, list):
            return [self.resolve(item) for item in template]

        if isinstance(template, str):
            refs = self.find_references(template)
            if not refs:
                return template

            resolved = template
            for ref in refs:
                parts = ref.split(".", 1)
                if len(parts) < 2:
                    raise ReferenceError(
                        f"Invalid reference '${{{ref}}}': expected format '${{step_name.key_path}}'."
                    )
                step_name, key_path = parts[0], parts[1]

                if not self._store.has(step_name):
                    raise ReferenceError(
                        f"Step '{step_name}' not found in store."
                    )

                try:
                    value = self._store.get(step_name, key_path)
                except KeyError as exc:
                    raise ReferenceError(str(exc)) from exc

                # Full-string reference → preserve original type
                if resolved == f"${{{ref}}}":
                    return value

                # Embedded reference → string substitution
                resolved = resolved.replace(f"${{{ref}}}", str(value))

            return resolved

        # Primitives (int, float, bool, None) — pass through unchanged
        return template

    def find_references(self, value: str) -> list[str]:
        """Extract all ``${...}`` reference keys from *value*.

        Args:
            value: A string potentially containing ``${step.key}`` patterns.

        Returns:
            A list of reference keys (without the ``${}`` wrapper).
        """
        return self._REF_PATTERN.findall(value)

    def get_nested_value(self, data: dict, key_path: str) -> Any:
        """Traverse *data* using a dot-separated *key_path*.

        Args:
            data: The dict to traverse.
            key_path: Dot-separated path (e.g. ``"user.address.city"``).

        Returns:
            The value at the end of the path.

        Raises:
            KeyError: If any segment of the path is missing.
        """
        current: Any = data
        segments = key_path.split(".")

        for i, segment in enumerate(segments):
            if not isinstance(current, dict) or segment not in current:
                traversed = ".".join(segments[: i + 1])
                raise KeyError(f"Key path '{traversed}' not found.")
            current = current[segment]

        return current
