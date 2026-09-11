"""The failure surface both migration drivers present to the operator.

A migration fails on the operator's own material -- a spec, a revision file, a
handler module -- so the message has to name what is wrong and stop, never
unwind a Python traceback into the terminal.
"""

import click


class MigrationError(click.ClickException):
    """A migration cannot proceed; the message is addressed to the operator."""
