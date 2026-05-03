"""Error handling utilities for CLI commands.

Provides centralized error formatting and reporting for consistent
user experience across all CLI commands.
"""

import json
import sys
from typing import NoReturn

from ...parsers.yaml_parser import ConfigErrors


def handle_config_errors(error: ConfigErrors) -> NoReturn:
    """Format and report configuration errors, then exit.

    Args:
        error: Configuration errors from YAML parsing/validation
    """
    payload = [item.to_dict() for item in error.errors]
    sys.stderr.write(json.dumps(payload, indent=2) + "\n")
    raise SystemExit(1)


def handle_generic_error(error: Exception) -> NoReturn:
    """Format and report generic errors, then exit.

    Args:
        error: Any exception raised during command execution
    """
    sys.stderr.write(f"Error: {error}\n")
    raise SystemExit(1)
