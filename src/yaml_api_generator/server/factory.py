import os

from . import build_app, build_raw_app

SPEC_ENV = "YAML_API_SPEC"
SCHEMA_ENV = "YAML_API_SCHEMA"
RAW_ENV = "YAML_API_RAW"


def create_app():
    """Build the app from the spec referenced by environment variables.

    Used as a uvicorn factory under --reload, where the worker subprocess
    re-imports the app and cannot receive the spec path as an argument.
    """
    spec = os.environ[SPEC_ENV]
    schema = os.environ.get(SCHEMA_ENV) or None
    if os.environ.get(RAW_ENV) == "1":
        return build_raw_app(spec, schema)
    return build_app(spec, schema)
