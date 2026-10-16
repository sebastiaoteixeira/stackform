"""Quoting of release values for the files compose and systemd read them from."""

def _line(value) -> str:
    text = str(value)
    if "\n" in text or "\r" in text:
        raise ValueError("a release value must fit on one line")
    return text


def env_file_quote(value) -> str:
    """A double-quoted value that compose's ``.env`` and systemd's ``EnvironmentFile`` both read literally."""
    escaped = _line(value).replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$")
    return f'"{escaped}"'


def unit_escape(value) -> str:
    """A unit file value whose ``%`` systemd does not read as a specifier."""
    return _line(value).replace("%", "%%")


def unit_quote(value) -> str:
    """A double-quoted unit file assignment, such as ``Environment=``, read literally."""
    escaped = unit_escape(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


class FilterModule:
    def filters(self):
        return {"env_file_quote": env_file_quote, "unit_escape": unit_escape, "unit_quote": unit_quote}
