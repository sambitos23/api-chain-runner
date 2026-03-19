"""API Chain Runner — execute chained API calls with dynamic reference resolution."""

__version__ = "1.0.0"

from api_chain_runner.runner import ChainRunner
from api_chain_runner.models import (
    ChainResult,
    ConfigurationError,
    StepResult,
)

__all__ = [
    "__version__",
    "ChainRunner",
    "ChainResult",
    "ConfigurationError",
    "StepResult",
]
