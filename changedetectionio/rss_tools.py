"""
RSS/Atom feed processing tools for changedetection.io
"""

from loguru import logger
import re


def cdata_in_document_to_text(html_content: str, render_anchor_tag_content=False) -> str:
    """
    Process CDATA sections in HTML/XML content - inline replacement.

    Args:
        html_content: The HTML/XML content to process
        render_anchor_tag_content: Whether to render anchor tag content

    Returns:
        Processed HTML/XML content with CDATA sections replaced inline
    """
    from xml.sax.saxutils import escape as xml_escape
    from .html_tools import html_to_text

    pattern = '<!\[CDATA\[(\s*(?:.(?<!\]\]>)\s*)*)\]\]>'

    def repl(m):
        text = m.group(1)
        return xml_escape(html_to_text(html_content=text, render_anchor_tag_content=render_anchor_tag_content)).strip()

    return re.sub(pattern, repl, html_content)


def format_rss_items(rss_content: str, render_anchor_tag_content=False) -> str:
    """
    Format RSS/Atom feed items in a readable text format using feedparser.

    Converts RSS <item> or Atom <entry> elements to formatted text with:
    - <title> → <h1>Title</h1>
    - <link> → Link: [url]
    - <guid> → Guid: [id]
    - <pubDate> → PubDate: [date]
    - <description> or <content> → Raw HTML content (CDATA and entities automatically handled)

    Args:
        rss_content: The RSS/Atom feed content
        render_anchor_tag_content: Whether to render anchor tag content in descriptions (unused, kept for compatibility)

    Returns:
        Formatted HTML content ready for html_to_text conversion
    """
    try:
        import feedparser
        from xml.sax.saxutils import escape as xml_escape

        # Parse the feed - feedparser handles all RSS/Atom variants, CDATA, entity unescaping, etc.
        feed = feedparser.parse(rss_content)

        formatted_items = []

        # Determine feed type for appropriate labels when fields are missing
        # feedparser sets feed.version to things like 'rss20', 'atom10', etc.
        is_atom = feed.version and 'atom' in feed.version

        for entry in feed.entries:
            item_parts = []

            # Title - feedparser handles CDATA and entity unescaping automatically
            if hasattr(entry, 'title') and entry.title:
                item_parts.append(f'<h1>{xml_escape(entry.title)}</h1>')

            # Link
            if hasattr(entry, 'link') and entry.link:
                item_parts.append(f'Link: {xml_escape(entry.link)}<br>')

            # GUID/ID
            if hasattr(entry, 'id') and entry.id:
                item_parts.append(f'Guid: {xml_escape(entry.id)}<br>')

            # Date - feedparser normalizes all date field names to 'published'
            if hasattr(entry, 'published') and entry.published:
                item_parts.append(f'PubDate: {xml_escape(entry.published)}<br>')

            # Description/Content - feedparser handles CDATA and entity unescaping automatically
            # Only add "Summary:" label for Atom <summary> tags
            content = None
            add_label = False

            if hasattr(entry, 'content') and entry.content:
                # Atom <content> - no label, just content
                content = entry.content[0].value if entry.content[0].value else None
            elif hasattr(entry, 'summary'):
                # Could be RSS <description> or Atom <summary>
                # feedparser maps both to entry.summary
                content = entry.summary if entry.summary else None
                # Only add "Summary:" label for Atom feeds (which use <summary> tag)
                if is_atom:
                    add_label = True

            # Add content with or without label
            if content:
                if add_label:
                    item_parts.append(f'Summary:<br>{content}')
                else:
                    item_parts.append(content)
            else:
                # No content - just show <none>
                item_parts.append('&lt;none&gt;')

            # Join all parts of this item
            if item_parts:
                formatted_items.append('\n'.join(item_parts))

        # Wrap each item in a div with classes (first, last, item-N)
        items_html = []
        total_items = len(formatted_items)
        for idx, item in enumerate(formatted_items):
            classes = ['rss-item']
            if idx == 0:
                classes.append('first')
            if idx == total_items - 1:
                classes.append('last')
            classes.append(f'item-{idx + 1}')

            class_str = ' '.join(classes)
            items_html.append(f'<div class="{class_str}">{item}</div>')
        return '<html><body>\n'+"\n<br><br>".join(items_html)+'\n</body></html>'

    except Exception as e:
        logger.warning(f"Error formatting RSS items: {str(e)}")
        # Fall back to original content
        return rss_content
