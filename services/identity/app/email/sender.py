"""EmailSender protocol + built-in implementations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx
import structlog

from ..config import get_settings

_log = structlog.get_logger()


@dataclass(slots=True, frozen=True)
class EmailMessage:
    to: str
    subject: str
    text_body: str
    html_body: str | None = None
    tag: str | None = None


class EmailSender(Protocol):
    async def send(self, message: EmailMessage) -> None: ...


class ConsoleSender:
    """Dev backend. Logs the email to stdout so tests can assert on it.

    The last message sent is also retained in :attr:`last_message` so
    integration tests can fish out verification tokens without mocking.
    """

    def __init__(self) -> None:
        self.last_message: EmailMessage | None = None

    async def send(self, message: EmailMessage) -> None:
        self.last_message = message
        _log.info(
            "email.console.sent",
            to=message.to,
            subject=message.subject,
            tag=message.tag,
            # The text body often contains a token; fine in dev, don't
            # do this in prod.
            text_body=message.text_body,
        )


class PostmarkSender:
    """Postmark HTTPS backend.

    Docs: https://postmarkapp.com/developer/api/email-api
    Uses the message-stream API so we can route transactional vs.
    broadcast through different streams.
    """

    def __init__(
        self,
        *,
        server_token: str,
        from_address: str,
        message_stream: str = "outbound",
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._token = server_token
        self._from = from_address
        self._stream = message_stream
        self._client = http_client or httpx.AsyncClient(
            base_url="https://api.postmarkapp.com",
            timeout=httpx.Timeout(10.0, connect=5.0),
        )

    async def send(self, message: EmailMessage) -> None:
        payload = {
            "From": self._from,
            "To": message.to,
            "Subject": message.subject,
            "TextBody": message.text_body,
            "MessageStream": self._stream,
        }
        if message.html_body is not None:
            payload["HtmlBody"] = message.html_body
        if message.tag is not None:
            payload["Tag"] = message.tag

        resp = await self._client.post(
            "/email",
            json=payload,
            headers={
                "X-Postmark-Server-Token": self._token,
                "Accept": "application/json",
            },
        )
        if resp.status_code >= 400:
            # Postmark's error body has an ErrorCode + Message.
            _log.error(
                "email.postmark.error",
                status=resp.status_code,
                body=resp.text,
                to=message.to,
            )
            resp.raise_for_status()
        _log.info("email.postmark.sent", to=message.to, tag=message.tag)


def build_sender() -> EmailSender:
    """Factory. Picks the backend per ``settings.email_backend``."""
    settings = get_settings()
    if settings.email_backend == "postmark":
        if not settings.postmark_server_token:
            raise RuntimeError(
                "POSTMARK_SERVER_TOKEN is required when email_backend=postmark"
            )
        return PostmarkSender(
            server_token=settings.postmark_server_token,
            from_address=settings.email_from,
            message_stream=settings.postmark_message_stream,
        )
    return ConsoleSender()
