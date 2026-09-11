import uuid

try:
    from uuid import uuid7 as _uuid7
except ImportError:
    from uuid_utils import uuid7 as _uuid7


def generate_id(id_format: str) -> str:
    if id_format == "uuidv7":
        return str(_uuid7())
    if id_format == "uuidv4":
        return str(uuid.uuid4())
    raise ValueError(f"Unsupported id format: {id_format}")
