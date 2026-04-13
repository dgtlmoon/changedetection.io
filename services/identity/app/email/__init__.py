"""Transactional email — protocol + implementations.

The rest of the app depends on :class:`EmailSender`; a concrete backend
is chosen at startup from ``settings.email_backend``:

* ``"console"`` — :class:`ConsoleSender`. Prints to stdout. Dev default.
* ``"postmark"`` — :class:`PostmarkSender`. HTTPS POST to Postmark.
"""

from .renderer import render_template
from .sender import ConsoleSender, EmailMessage, EmailSender, build_sender

__all__ = [
    "ConsoleSender",
    "EmailMessage",
    "EmailSender",
    "build_sender",
    "render_template",
]
