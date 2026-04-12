"""
Custom Discord plugin for changedetection.io
Extends Apprise's Discord plugin to support custom colored embeds for removed/added content
"""
from apprise.plugins.discord import NotifyDiscord
from apprise.decorators import notify
from apprise.common import NotifyFormat
from loguru import logger

# Import placeholders from changedetection's diff module
from ...diff import (
    REMOVED_PLACEMARKER_OPEN,
    REMOVED_PLACEMARKER_CLOSED,
    ADDED_PLACEMARKER_OPEN,
    ADDED_PLACEMARKER_CLOSED,
    CHANGED_PLACEMARKER_OPEN,
    CHANGED_PLACEMARKER_CLOSED,
    CHANGED_INTO_PLACEMARKER_OPEN,
    CHANGED_INTO_PLACEMARKER_CLOSED,
)

# Discord embed sidebar colors for different change types
DISCORD_COLOR_UNCHANGED = 8421504   # Gray (#808080)
DISCORD_COLOR_REMOVED = 16711680    # Red (#FF0000)
DISCORD_COLOR_ADDED = 65280         # Green (#00FF00)
DISCORD_COLOR_CHANGED = 16753920    # Orange (#FFA500)
DISCORD_COLOR_CHANGED_INTO = 3447003  # Blue (#5865F2 - Discord blue)
DISCORD_COLOR_WARNING = 16776960    # Yellow (#FFFF00)


class NotifyDiscordCustom(NotifyDiscord):
    """
    Custom Discord notification handler that supports multiple colored embeds
    for showing removed (red) and added (green) content separately.
    """

    def send(self, body, title="", notify_type=None, attach=None, **kwargs):
        """
        Override send method to create custom embeds with red/green colors
        for removed/added content when placeholders are present.
        """

        # Check if body contains our diff placeholders
        has_removed = REMOVED_PLACEMARKER_OPEN in body
        has_added = ADDED_PLACEMARKER_OPEN in body
        has_changed = CHANGED_PLACEMARKER_OPEN in body
        has_changed_into = CHANGED_INTO_PLACEMARKER_OPEN in body

        # If we have diff placeholders and we're in markdown/html format, create custom embeds
        if (has_removed or has_added or has_changed or has_changed_into) and self.notify_format in (NotifyFormat.MARKDOWN, NotifyFormat.HTML):
            return self._send_with_colored_embeds(body, title, notify_type, attach, **kwargs)

        # Otherwise, use the parent class's default behavior
        return super().send(body, title, notify_type, attach, **kwargs)

    def _send_with_colored_embeds(self, body, title, notify_type, attach, **kwargs):
        """
        Send Discord message with embeds in the original diff order.
        Preserves the sequence: unchanged -> removed -> added -> unchanged, etc.
        """
        from datetime import datetime, timezone

        payload = {
            "tts": self.tts,
            "wait": self.tts is False,
        }

        if self.flags:
            payload["flags"] = self.flags

        # Acquire image_url
        image_url = self.image_url(notify_type)

        if self.avatar and (image_url or self.avatar_url):
            payload["avatar_url"] = self.avatar_url if self.avatar_url else image_url

        if self.user:
            payload["username"] = self.user

        # Associate our thread_id with our message
        params = {"thread_id": self.thread_id} if self.thread_id else None

        # Build embeds array preserving order
        embeds = []

        # Add title as plain bold text in message content (not an embed)
        if title:
            payload["content"] = f"**{title}**"

        # Parse the body into ordered chunks
        chunks = self._parse_body_into_chunks(body)

        # Discord limits:
        # - Max 10 embeds per message
        # - Max 6000 characters total across all embeds
        # - Max 4096 characters per embed description
        max_embeds = 10
        max_total_chars = 6000
        max_embed_description = 4096

        # All 10 embed slots are available for content
        max_content_embeds = max_embeds

        # Start character count
        total_chars = 0

        # Create embeds from chunks in order (no titles, just color coding)
        for chunk_type, content in chunks:
            if not content.strip():
                continue

            # Truncate individual embed description if needed
            if len(content) > max_embed_description:
                content = content[:max_embed_description - 3] + "..."

            # Check if we're approaching the embed count limit
            # We need room for the warning embed, so stop at max_content_embeds - 1
            current_content_embeds = len(embeds)
            if current_content_embeds >= max_content_embeds - 1:
                # Add a truncation notice (this will be the 10th embed)
                embeds.append({
                    "description": "⚠️ Content truncated (Discord 10 embed limit reached) - Tip: Select 'Plain Text' or 'HTML' format for longer diffs",
                    "color": DISCORD_COLOR_WARNING,
                })
                break

            # Check if adding this embed would exceed total character limit
            if total_chars + len(content) > max_total_chars:
                # Add a truncation notice
                remaining_chars = max_total_chars - total_chars
                if remaining_chars > 100:
                    # Add partial content if we have room
                    truncated_content = content[:remaining_chars - 100] + "..."
                    embeds.append({
                        "description": truncated_content,
                        "color": (DISCORD_COLOR_UNCHANGED if chunk_type == "unchanged"
                                 else DISCORD_COLOR_REMOVED if chunk_type == "removed"
                                 else DISCORD_COLOR_ADDED),
                    })
                embeds.append({
                    "description": "⚠️ Content truncated (Discord 6000 char limit reached)\nTip: Select 'Plain Text' or 'HTML' format for longer diffs",
                    "color": DISCORD_COLOR_WARNING,
                })
                break

            if chunk_type == "unchanged":
                embeds.append({
                    "description": content,
                    "color": DISCORD_COLOR_UNCHANGED,
                })
            elif chunk_type == "removed":
                embeds.append({
                    "description": content,
                    "color": DISCORD_COLOR_REMOVED,
                })
            elif chunk_type == "added":
                embeds.append({
                    "description": content,
                    "color": DISCORD_COLOR_ADDED,
                })
            elif chunk_type == "changed":
                # Changed (old value) - use orange to distinguish from pure removal
                embeds.append({
                    "description": content,
                    "color": DISCORD_COLOR_CHANGED,
                })
            elif chunk_type == "changed_into":
                # Changed into (new value) - use blue to distinguish from pure addition
                embeds.append({
                    "description": content,
                    "color": DISCORD_COLOR_CHANGED_INTO,
                })

            total_chars += len(content)

        if embeds:
            payload["embeds"] = embeds

        # Send the payload using parent's _send method
        if not self._send(payload, params=params):
            return False

        # Handle attachments if present
        if attach and self.attachment_support:
            payload.update({
                "tts": False,
                "wait": True,
            })
            payload.pop("embeds", None)
            payload.pop("content", None)
            payload.pop("allow_mentions", None)

            for attachment in attach:
                self.logger.info(f"Posting Discord Attachment {attachment.name}")
                if not self._send(payload, params=params, attach=attachment):
                    return False

        return True

    def _parse_body_into_chunks(self, body):
        """
        Parse the body into ordered chunks of (type, content) tuples.
        Types: "unchanged", "removed", "added", "changed", "changed_into"
        Preserves the original order of the diff.
        """
        chunks = []
        position = 0

        while position < len(body):
            # Find the next marker
            next_removed = body.find(REMOVED_PLACEMARKER_OPEN, position)
            next_added = body.find(ADDED_PLACEMARKER_OPEN, position)
            next_changed = body.find(CHANGED_PLACEMARKER_OPEN, position)
            next_changed_into = body.find(CHANGED_INTO_PLACEMARKER_OPEN, position)

            # Determine which marker comes first
            if next_removed == -1 and next_added == -1 and next_changed == -1 and next_changed_into == -1:
                # No more markers, rest is unchanged
                if position < len(body):
                    chunks.append(("unchanged", body[position:]))
                break

            # Find the earliest marker
            next_marker_pos = None
            next_marker_type = None

            # Compare all marker positions to find the earliest
            markers = []
            if next_removed != -1:
                markers.append((next_removed, "removed"))
            if next_added != -1:
                markers.append((next_added, "added"))
            if next_changed != -1:
                markers.append((next_changed, "changed"))
            if next_changed_into != -1:
                markers.append((next_changed_into, "changed_into"))

            if markers:
                next_marker_pos, next_marker_type = min(markers, key=lambda x: x[0])

            # Add unchanged content before the marker
            if next_marker_pos > position:
                chunks.append(("unchanged", body[position:next_marker_pos]))

            # Find the closing marker
            if next_marker_type == "removed":
                open_marker = REMOVED_PLACEMARKER_OPEN
                close_marker = REMOVED_PLACEMARKER_CLOSED
            elif next_marker_type == "added":
                open_marker = ADDED_PLACEMARKER_OPEN
                close_marker = ADDED_PLACEMARKER_CLOSED
            elif next_marker_type == "changed":
                open_marker = CHANGED_PLACEMARKER_OPEN
                close_marker = CHANGED_PLACEMARKER_CLOSED
            else:  # changed_into
                open_marker = CHANGED_INTO_PLACEMARKER_OPEN
                close_marker = CHANGED_INTO_PLACEMARKER_CLOSED

            close_pos = body.find(close_marker, next_marker_pos)

            if close_pos == -1:
                # No closing marker, take rest as this type
                content = body[next_marker_pos + len(open_marker):]
                chunks.append((next_marker_type, content))
                break
            else:
                # Extract content between markers
                content = body[next_marker_pos + len(open_marker):close_pos]
                chunks.append((next_marker_type, content))
                position = close_pos + len(close_marker)

        return chunks


# Register the custom Discord handler with Apprise
# This will override the built-in discord:// handler
@notify(on="discord")
def discord_custom_wrapper(body, title, notify_type, meta, body_format=None, *args, **kwargs):
    """
    Wrapper function to make the custom Discord handler work with Apprise's decorator system.
    Note: This decorator approach may not work for overriding built-in plugins.
    The class-based approach above is the proper way to extend NotifyDiscord.
    """
    logger.info("Custom Discord handler called")
    # This is here for potential future use with decorator-based registration
    return True
