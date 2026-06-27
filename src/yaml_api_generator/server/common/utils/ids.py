import uuid


def generate_id(id_format: str) -> str:
    if id_format == "uuidv7":
        uuid7 = getattr(uuid, "uuid7", None)
        if uuid7 is None:
            raise RuntimeError("uuidv7 is not available in this Python runtime")
        return str(uuid7())
    if id_format == "uuidv4":
        return str(uuid.uuid4())
    raise ValueError(f"Unsupported id format: {id_format}")
