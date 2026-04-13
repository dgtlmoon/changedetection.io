"""Jinja2 template rendering for transactional emails.

Templates live under ``app/email/templates/``. A template is a pair:

* ``<name>.txt`` — plain-text, required.
* ``<name>.html`` — HTML, optional.

Both are rendered with the same context dict. HTML output is
auto-escaped; text is not (we control the templates, no XSS surface).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, TemplateNotFound, select_autoescape

_TEMPLATES_DIR = Path(__file__).parent / "templates"

_text_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=False,  # text
    keep_trailing_newline=True,
)
_html_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(default=True),
    keep_trailing_newline=True,
)


@dataclass(slots=True, frozen=True)
class RenderedTemplate:
    subject: str
    text_body: str
    html_body: str | None


def render_template(name: str, **context: Any) -> RenderedTemplate:
    """Render ``<name>.txt`` (+ optional ``<name>.html``).

    The first non-blank line of the text template is taken as the
    subject — this keeps subject lines in version control alongside
    their bodies.
    """
    text = _text_env.get_template(f"{name}.txt").render(**context)
    subject, _, text_body = text.partition("\n")
    subject = subject.strip()
    text_body = text_body.lstrip("\n")

    html_body: str | None
    try:
        html_body = _html_env.get_template(f"{name}.html").render(**context)
    except TemplateNotFound:
        html_body = None

    return RenderedTemplate(subject=subject, text_body=text_body, html_body=html_body)
