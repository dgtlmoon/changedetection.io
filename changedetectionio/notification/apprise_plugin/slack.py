"""
Custom Slack plugin for TicketWatch / changedetection.io
Extends Apprise's Slack plugin to support rich ticket notification formatting.

Features:
- Rich Block Kit formatting with separators and emojis
- Event name, venue, prices, and URL display
- Slack link markup formatting (<URL|text>)
- Color-coded attachments for different alert types
"""
from apprise.plugins.slack import NotifySlack
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

# Slack attachment colors for different change types
SLACK_COLOR_UNCHANGED = "#808080"   # Gray
SLACK_COLOR_REMOVED = "#FF0000"     # Red
SLACK_COLOR_ADDED = "#00FF00"       # Green
SLACK_COLOR_CHANGED = "#FFA500"     # Orange
SLACK_COLOR_CHANGED_INTO = "#5865F2"  # Blue
SLACK_COLOR_WARNING = "#FFFF00"     # Yellow
SLACK_COLOR_INFO = "#36a64f"        # Slack green


def format_slack_link(url: str, text: str = None) -> str:
    """
    Format a URL using Slack's link markup.

    Args:
        url: The URL to link to
        text: Optional display text. If None, URL is shown.

    Returns:
        Slack-formatted link: <URL|text> or <URL>
    """
    if text:
        return f"<{url}|{text}>"
    return f"<{url}>"


def apply_slack_markdown_to_body(n_body: str) -> str:
    """
    Convert changedetection placemarkers to Slack mrkdwn format.

    Slack supports:
    - *bold*
    - ~strikethrough~
    - _italic_
    - `code`
    - ```code block```

    Args:
        n_body: Text containing placemarkers

    Returns:
        Text with Slack mrkdwn formatting
    """
    import re

    # Define the mapping between placeholders and Slack markdown markers
    replacements = [
        (REMOVED_PLACEMARKER_OPEN, '~', REMOVED_PLACEMARKER_CLOSED, '~'),
        (ADDED_PLACEMARKER_OPEN, '*', ADDED_PLACEMARKER_CLOSED, '*'),
        (CHANGED_PLACEMARKER_OPEN, '~', CHANGED_PLACEMARKER_CLOSED, '~'),
        (CHANGED_INTO_PLACEMARKER_OPEN, '*', CHANGED_INTO_PLACEMARKER_CLOSED, '*'),
    ]

    # Apply replacements without whitespace breaking the markdown
    for open_tag, open_md, close_tag, close_md in replacements:
        pattern = re.compile(
            re.escape(open_tag) + r'(\s*)(.*?)?(\s*)' + re.escape(close_tag),
            flags=re.DOTALL
        )
        n_body = pattern.sub(lambda m: f"{m.group(1)}{open_md}{m.group(2)}{close_md}{m.group(3)}", n_body)

    return n_body


class NotifySlackCustom(NotifySlack):
    """
    Custom Slack notification handler for TicketWatch.

    Provides rich ticket-specific formatting with:
    - Event name and venue display
    - Price information with change highlighting
    - Direct links to ticket pages
    - Color-coded sections for different change types
    """

    def send(self, body, title="", notify_type=None, attach=None, **kwargs):
        """
        Override send method to create rich Slack notifications.

        When diff placeholders are present, creates color-coded attachments.
        Otherwise, falls back to default behavior with enhanced formatting.
        """
        # Check if body contains our diff placeholders
        has_removed = REMOVED_PLACEMARKER_OPEN in body
        has_added = ADDED_PLACEMARKER_OPEN in body
        has_changed = CHANGED_PLACEMARKER_OPEN in body
        has_changed_into = CHANGED_INTO_PLACEMARKER_OPEN in body

        # If we have diff placeholders, create rich attachments
        if has_removed or has_added or has_changed or has_changed_into:
            return self._send_with_rich_formatting(body, title, notify_type, attach, **kwargs)

        # Otherwise, apply basic Slack formatting and use parent
        body = self._enhance_body_formatting(body)
        return super().send(body, title, notify_type, attach, **kwargs)

    def _enhance_body_formatting(self, body: str) -> str:
        """
        Enhance the notification body with Slack-specific formatting.

        - Converts URLs to Slack link format
        - Adds visual separators
        - Applies mrkdwn formatting
        """
        import re

        # Convert plain URLs to Slack links (but not already formatted ones)
        url_pattern = r'(?<![<])(https?://[^\s<>]+)(?![>|])'
        body = re.sub(url_pattern, r'<\1>', body)

        # Convert markdown horizontal rules to Slack dividers
        body = body.replace('---', '--------')

        return body

    def _send_with_rich_formatting(self, body, title, notify_type, attach, **kwargs):
        """
        Send Slack message with rich attachments showing color-coded diffs.

        Creates separate attachments for:
        - Removed content (red sidebar)
        - Added content (green sidebar)
        - Changed content (orange/blue sidebar)
        """
        # Parse the body into chunks
        chunks = self._parse_body_into_chunks(body)

        # Build attachments array
        attachments = []

        # Slack limits
        max_attachments = 20  # Slack's limit
        max_text_length = 3000  # Per attachment

        for chunk_type, content in chunks:
            if not content.strip():
                continue

            # Truncate if needed
            if len(content) > max_text_length:
                content = content[:max_text_length - 3] + "..."

            # Check attachment limit
            if len(attachments) >= max_attachments - 1:
                attachments.append({
                    "color": SLACK_COLOR_WARNING,
                    "text": ":warning: Content truncated (Slack attachment limit reached)",
                    "mrkdwn_in": ["text"]
                })
                break

            # Determine color and prefix based on chunk type
            if chunk_type == "removed":
                color = SLACK_COLOR_REMOVED
                prefix = ":x: *Removed:*\n"
            elif chunk_type == "added":
                color = SLACK_COLOR_ADDED
                prefix = ":white_check_mark: *Added:*\n"
            elif chunk_type == "changed":
                color = SLACK_COLOR_CHANGED
                prefix = ":arrows_counterclockwise: *Changed from:*\n"
            elif chunk_type == "changed_into":
                color = SLACK_COLOR_CHANGED_INTO
                prefix = ":arrow_right: *Changed to:*\n"
            else:  # unchanged
                color = SLACK_COLOR_UNCHANGED
                prefix = ""

            # Enhance content with Slack formatting
            content = self._enhance_body_formatting(content)

            attachments.append({
                "color": color,
                "text": prefix + content,
                "mrkdwn_in": ["text"]
            })

        # Create the message payload
        # The parent class will handle the actual sending
        # We need to set up the attachments for the notification

        # Store original values
        original_body = body

        # Apply Slack markdown to any remaining placeholders in the body
        body = apply_slack_markdown_to_body(body)
        body = self._enhance_body_formatting(body)

        # For Slack, we'll use the attachments API
        # This requires modifying how we call the parent
        try:
            # Build a rich message with title and attachments
            if attachments:
                # Use blocks for better formatting
                blocks = []

                # Header block with title
                if title:
                    blocks.append({
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": title[:150],  # Slack header limit
                            "emoji": True
                        }
                    })

                    # Add a divider after header
                    blocks.append({"type": "divider"})

                # Store blocks and attachments for the send
                self._custom_blocks = blocks
                self._custom_attachments = attachments

                # Call parent with modified body (blocks will be added in _send)
                result = super().send(
                    body="",  # Empty body since we're using attachments
                    title=title,
                    notify_type=notify_type,
                    attach=attach,
                    **kwargs
                )

                # Clean up
                self._custom_blocks = None
                self._custom_attachments = None

                return result
            else:
                return super().send(body, title, notify_type, attach, **kwargs)

        except Exception as e:
            logger.error(f"Error sending rich Slack notification: {e}")
            # Fallback to simple send
            return super().send(body, title, notify_type, attach, **kwargs)

    def _parse_body_into_chunks(self, body: str):
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

            # Check if no more markers
            if next_removed == -1 and next_added == -1 and next_changed == -1 and next_changed_into == -1:
                if position < len(body):
                    chunks.append(("unchanged", body[position:]))
                break

            # Find the earliest marker
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
            else:
                break

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


def create_ticket_notification(
    event_name: str,
    venue: str = None,
    prices: list = None,
    url: str = None,
    availability: str = None,
    change_type: str = "update"
) -> dict:
    """
    Create a rich Slack notification payload for ticket events.

    This function creates a Block Kit formatted message specifically
    designed for ticket monitoring alerts.

    Args:
        event_name: Name of the event/show
        venue: Venue name (optional)
        prices: List of price dictionaries with 'price' and optional 'currency' keys
        url: Direct link to the ticket page
        availability: Availability status (in_stock, out_of_stock, limited, unknown)
        change_type: Type of change (new, price_change, sellout, restock, update)

    Returns:
        dict: Slack Block Kit payload ready for sending
    """
    blocks = []

    # Determine emoji and header based on change type
    emoji_map = {
        "new": ":ticket:",
        "price_change": ":moneybag:",
        "sellout": ":x:",
        "restock": ":tada:",
        "update": ":bell:"
    }

    header_map = {
        "new": "New Listing",
        "price_change": "Price Change",
        "sellout": "Sold Out",
        "restock": "Back in Stock!",
        "update": "Listing Updated"
    }

    emoji = emoji_map.get(change_type, ":bell:")
    header_text = header_map.get(change_type, "Update")

    # Header block
    blocks.append({
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": f"{emoji} {header_text}: {event_name[:100]}",
            "emoji": True
        }
    })

    # Divider
    blocks.append({"type": "divider"})

    # Event details section
    fields = []

    if venue:
        fields.append({
            "type": "mrkdwn",
            "text": f":round_pushpin: *Venue:*\n{venue}"
        })

    if availability:
        availability_emoji = {
            "in_stock": ":white_check_mark:",
            "out_of_stock": ":no_entry:",
            "limited": ":warning:",
            "unknown": ":question:"
        }.get(availability, ":question:")

        availability_text = {
            "in_stock": "Available",
            "out_of_stock": "Sold Out",
            "limited": "Limited",
            "unknown": "Unknown"
        }.get(availability, availability)

        fields.append({
            "type": "mrkdwn",
            "text": f"{availability_emoji} *Status:*\n{availability_text}"
        })

    if fields:
        blocks.append({
            "type": "section",
            "fields": fields
        })

    # Prices section
    if prices:
        price_lines = []
        for price_info in prices:
            if isinstance(price_info, dict):
                price = price_info.get('price', price_info.get('value', '?'))
                currency = price_info.get('currency', 'USD')
                label = price_info.get('label', '')

                if label:
                    price_lines.append(f"• {label}: {currency} {price}")
                else:
                    price_lines.append(f"• {currency} {price}")
            else:
                price_lines.append(f"• {price_info}")

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":money_with_wings: *Prices:*\n" + "\n".join(price_lines)
            }
        })

    # Divider before link
    blocks.append({"type": "divider"})

    # Link button
    if url:
        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": ":link: View Tickets",
                        "emoji": True
                    },
                    "url": url,
                    "style": "primary"
                }
            ]
        })

    # Context footer
    from datetime import datetime
    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": f":robot_face: TicketWatch | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            }
        ]
    })

    return {"blocks": blocks}


def format_ticket_message_text(
    event_name: str,
    venue: str = None,
    prices: list = None,
    url: str = None,
    availability: str = None,
    change_type: str = "update"
) -> str:
    """
    Create a formatted text message for Slack notifications.

    This is a simpler alternative to Block Kit that works with
    all Slack notification methods.

    Args:
        event_name: Name of the event/show
        venue: Venue name (optional)
        prices: List of price dictionaries or strings
        url: Direct link to the ticket page
        availability: Availability status
        change_type: Type of change

    Returns:
        str: Formatted message text with Slack mrkdwn
    """
    lines = []

    # Emoji and header
    emoji_map = {
        "new": ":ticket:",
        "price_change": ":moneybag:",
        "sellout": ":x:",
        "restock": ":tada:",
        "update": ":bell:"
    }

    header_map = {
        "new": "New Listing",
        "price_change": "Price Change",
        "sellout": "SOLD OUT",
        "restock": "Back in Stock!",
        "update": "Listing Updated"
    }

    emoji = emoji_map.get(change_type, ":bell:")
    header = header_map.get(change_type, "Update")

    # Header line
    lines.append(f"{emoji} *{header}*")
    lines.append("----------------------------------------")

    # Event name
    lines.append(f":star: *Event:* {event_name}")

    # Venue
    if venue:
        lines.append(f":round_pushpin: *Venue:* {venue}")

    # Availability
    if availability:
        availability_emoji = {
            "in_stock": ":white_check_mark:",
            "out_of_stock": ":no_entry:",
            "limited": ":warning:",
            "unknown": ":question:"
        }.get(availability, ":question:")

        availability_text = {
            "in_stock": "Available",
            "out_of_stock": "Sold Out",
            "limited": "Limited Availability",
            "unknown": "Unknown"
        }.get(availability, availability)

        lines.append(f"{availability_emoji} *Status:* {availability_text}")

    # Prices
    if prices:
        lines.append("")
        lines.append(":money_with_wings: *Prices:*")
        for price_info in prices:
            if isinstance(price_info, dict):
                price = price_info.get('price', price_info.get('value', '?'))
                currency = price_info.get('currency', 'USD')
                label = price_info.get('label', '')

                if label:
                    lines.append(f"  • {label}: {currency} {price}")
                else:
                    lines.append(f"  • {currency} {price}")
            else:
                lines.append(f"  • {price_info}")

    # Separator
    lines.append("----------------------------------------")

    # URL
    if url:
        lines.append(f":link: {format_slack_link(url, 'View Tickets')}")

    return "\n".join(lines)
