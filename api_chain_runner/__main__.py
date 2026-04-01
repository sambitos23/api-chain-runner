"""CLI entry point for API Chain Runner.

Usage::

    python -m api_chain_runner example_chain.yaml
    python -m api_chain_runner example_chain.yaml -o results.csv
    python -m api_chain_runner example_chain.yaml -o results.xlsx -f xlsx
    python -m api_chain_runner --ui flow/
"""

from __future__ import annotations
import argparse
import os
import re
import yaml
from api_chain_runner import __version__
from api_chain_runner.logger import ResultLogger
from api_chain_runner.runner import ChainRunner


def _load_env_file(env_path: str = ".env") -> None:
    """Load key=value pairs from a .env file into os.environ.

    Skips blank lines and comments (lines starting with #).
    Strips optional quotes around values.
    Does not override existing environment variables.
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
            # Strip surrounding quotes
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            if key and key not in os.environ:
                os.environ[key] = value


def _substitute_env_vars(obj):
    """Recursively substitute ``${ENV:VAR_NAME}`` placeholders with
    the corresponding environment variable values.

    If the environment variable is not set the placeholder is left as-is
    so the user gets a clear signal that something is missing.
    """
    if isinstance(obj, dict):
        return {k: _substitute_env_vars(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_substitute_env_vars(item) for item in obj]
    if isinstance(obj, str):
        def _replace(match):
            var_name = match.group(1)
            return os.environ.get(var_name, match.group(0))
        return re.sub(r"\$\{ENV:([^}]+)\}", _replace, obj)
    return obj


def _preprocess_config(config_path: str) -> str:
    """Read a YAML config, perform env-var substitution, and write to a
    temporary file so that :class:`ChainRunner` can load it normally.

    Returns the path to the (possibly rewritten) config file.
    """
    with open(config_path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    substituted = _substitute_env_vars(raw)

    # If nothing changed we can just use the original file directly.
    if substituted == raw:
        return config_path

    import tempfile

    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, encoding="utf-8"
    )
    yaml.dump(substituted, tmp, default_flow_style=False)
    tmp.close()
    return tmp.name


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the CLI."""
    parser = argparse.ArgumentParser(
        prog="api_chain_runner",
        description="Execute a chain of API calls defined in a YAML config file.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--ui",
        nargs="?",
        const=".",
        default=None,
        metavar="FLOW_DIR",
        help="Launch the web UI. Optionally specify a directory to scan for YAML flows (default: current dir).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5656,
        help="Port for the web UI server (default: 5656).",
    )
    parser.add_argument(
        "config",
        nargs="?",
        help="Path to the YAML chain configuration file.",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output file path for results (default: <config_stem>_results.csv).",
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=["csv", "xlsx"],
        default="csv",
        help="Output format: csv (default) or xlsx.",
    )
    parser.add_argument(
        "-e",
        "--env",
        default=".env",
        metavar="ENV_FILE",
        help="Path to .env file (default: .env in current directory).",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    """Parse arguments, run the chain, and print a summary."""
    parser = build_parser()
    args = parser.parse_args(argv)

    # Load .env file into os.environ
    _load_env_file(args.env)

    # Launch web UI mode
    if args.ui is not None:
        from api_chain_runner.ui.server import start_server
        start_server(flow_dir=args.ui, port=args.port)
        return

    if not args.config:
        parser.error("config is required when not using --ui")

    try:
        runner = ChainRunner(args.config, env_file=args.env)

        # Override output path / format if the user specified them
        if args.output or args.format != "csv":
            output_path = args.output or runner.logger._output_path
            runner.logger = ResultLogger(str(output_path), fmt=args.format)
            # Re-wire the executor's logger reference
            runner.executor.logger = runner.logger

        result = runner.run()
    except Exception:
        raise

    # Print summary to stdout
    print(
        f"Executed {result.total_steps} steps: "
        f"{result.passed} passed, {result.failed} failed"
    )
    for step_result in result.results:
        status = "\u2713" if step_result.success else "\u2717"
        print(
            f"  {status} {step_result.step_name} \u2014 "
            f"HTTP {step_result.status_code} ({step_result.duration_ms:.0f}ms)"
        )


if __name__ == "__main__":
    main()
