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
    Format RSS/Atom feed items in a readable text format.

    Converts RSS <item> or Atom <entry> elements to formatted text with:
    - <title> → <h1>Title</h1>
    - <link> → Link: [url]
    - <guid> → Guid: [id]
    - <pubDate> → PubDate: [date]
    - <description> or <content> → Full html_to_text conversion

    Args:
        rss_content: The RSS/Atom feed content
        render_anchor_tag_content: Whether to render anchor tag content in descriptions

    Returns:
        Formatted HTML content ready for html_to_text conversion
    """
    from lxml import etree
    from xml.sax.saxutils import escape as xml_escape

    try:
        # Parse with XMLParser to preserve CDATA
        parser = etree.XMLParser(strip_cdata=False)
        root = etree.fromstring(rss_content.encode('utf-8'), parser=parser)

        formatted_items = []

        # Handle both RSS (<item>) and Atom (<entry>) formats
        items = root.xpath('//item | //entry')

        for item in items:
            item_parts = []

            # Extract title
            title_elem = item.find('title')
            if title_elem is not None and title_elem.text:
                # Convert CDATA in title if present
                title_text = etree.tostring(title_elem, encoding='unicode', method='html')
                title_text = cdata_in_document_to_text(title_text)
                # Strip the title tags and get just the content
                title_clean = re.sub(r'</?title[^>]*>', '', title_text).strip()
                if title_clean:
                    item_parts.append(f'<h1>{xml_escape(title_clean)}</h1>')

            # Extract link
            link_elem = item.find('link')
            if link_elem is not None:
                link_text = link_elem.text if link_elem.text else link_elem.get('href', '')
                if link_text:
                    item_parts.append(f'Link: {xml_escape(link_text.strip())}')

            # Extract guid/id
            guid_elem = item.find('guid')
            if guid_elem is None:
                guid_elem = item.find('id')
            if guid_elem is not None and guid_elem.text:
                item_parts.append(f'Guid: {xml_escape(guid_elem.text.strip())}')

            # Extract pubDate/published/updated
            date_elem = item.find('pubDate')
            if date_elem is None:
                date_elem = item.find('published')
            if date_elem is None:
                date_elem = item.find('updated')
            if date_elem is not None and date_elem.text:
                item_parts.append(f'PubDate: {xml_escape(date_elem.text.strip())}')

            # Extract description/content/summary
            desc_elem = item.find('description')
            if desc_elem is None:
                desc_elem = item.find('content')
            if desc_elem is None:
                desc_elem = item.find('summary')
            if desc_elem is not None:
                # Get the full element as string to preserve CDATA and nested HTML
                desc_html = etree.tostring(desc_elem, encoding='unicode', method='html')

                # First process CDATA sections
                desc_processed = cdata_in_document_to_text(desc_html, render_anchor_tag_content=render_anchor_tag_content)

                # Strip the outer description/content/summary tags
                desc_processed = re.sub(r'^<(description|content|summary)[^>]*>', '', desc_processed)
                desc_processed = re.sub(r'</(description|content|summary)>$', '', desc_processed)

                if desc_processed.strip():
                    item_parts.append(desc_processed)

            # Join all parts of this item
            if item_parts:
                formatted_items.append('\n'.join(item_parts))

        # Join all items with <br><br><hr>
        return '<br><br><hr>'.join(formatted_items)

    except Exception as e:
        logger.warning(f"Error formatting RSS items: {str(e)}")
        # Fall back to original content
        return rss_content
