"""Tokenizer for character-level diffs that keeps HTML markup intact."""

# HTML's raw-text elements must not have their contents interpreted as nested
# markup.  In particular, JavaScript and CSS commonly contain expressions such
# as ``a < b`` which are ordinary text inside the element.
_RAW_TEXT_ELEMENTS = frozenset({'script', 'style', 'textarea', 'title'})
_TAG_NAME_CHARACTERS = frozenset(
    'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789:_-'
)


Markup = tuple[int, str | None, bool, bool]


def _scan_to_tag_end(text: str, start: int) -> int | None:
    """Return the end offset of a quoted-aware ``>``-terminated construct.

    A literal ``<`` outside an attribute quote makes the candidate invalid.
    Rejecting it prevents a stray less-than sign from swallowing the rest of a
    line and becoming one large, non-diffable token.
    """
    quote = None
    for offset in range(start, len(text)):
        char = text[offset]
        if quote:
            if char == quote:
                quote = None
        elif char in ('"', "'"):
            quote = char
        elif char == '<':
            return None
        elif char == '>':
            return offset + 1
    return None


def _parse_special_markup(text: str, start: int) -> Markup | None:
    """Parse comments, declarations, processing instructions, and CDATA."""
    # Comments have their own terminator, which may contain arbitrary ``>``
    # characters.  Treat an unterminated comment as ordinary text.
    if text.startswith('<!--', start):
        comment_end = text.find('-->', start + 4)
        if comment_end == -1:
            return None
        return comment_end + 3, None, False, False

    # XML CDATA is occasionally present in scraped HTML/SVG.  Preserve it as
    # one markup token when it is properly terminated.
    if text.startswith('<![CDATA[', start):
        cdata_end = text.find(']]>', start + 9)
        if cdata_end == -1:
            return None
        return cdata_end + 3, None, False, False

    if start + 1 >= len(text):
        return None

    marker = text[start + 1]
    if marker == '!':
        # Declarations (most commonly ``<!DOCTYPE ...>``).  Avoid treating
        # ``<!`` followed by punctuation/whitespace as a tag-like construct.
        if start + 2 >= len(text) or not text[start + 2].isalpha():
            return None
        end = _scan_to_tag_end(text, start + 2)
        return (end, None, False, False) if end is not None else None

    if marker == '?':
        # Processing instructions are uncommon in HTML but can occur in XML
        # snapshots.  The same quote-aware scanner safely preserves them.
        if start + 2 >= len(text) or text[start + 2].isspace():
            return None
        end = _scan_to_tag_end(text, start + 2)
        return (end, None, False, False) if end is not None else None

    return None


def _parse_standard_tag(text: str, start: int) -> Markup | None:
    """Parse a normal opening, closing, or self-closing HTML tag."""
    cursor = start + 1
    is_closing = False
    if text[cursor] == '/':
        is_closing = True
        cursor += 1

    # HTMLParser uses an ASCII letter as the start of a tag name.  Matching
    # that rule avoids classifying ``<3`` or ``< b>`` as markup.
    if cursor >= len(text) or not ('A' <= text[cursor] <= 'Z' or 'a' <= text[cursor] <= 'z'):
        return None

    name_start = cursor
    cursor += 1
    while cursor < len(text) and text[cursor] in _TAG_NAME_CHARACTERS:
        cursor += 1
    tag_name = text[name_start:cursor].lower()

    # A tag name must be followed by whitespace, ``/`` or ``>``.  This rejects
    # malformed constructs such as ``<tag=value>`` without rejecting ordinary
    # attributes.
    if cursor < len(text) and not (text[cursor].isspace() or text[cursor] in '/>'):
        return None

    end = _scan_to_tag_end(text, cursor)
    if end is None:
        return None
    is_self_closing = text[start:end].rstrip().endswith('/>')
    return end, tag_name, is_closing, is_self_closing


def _parse_markup_at(text: str, start: int) -> Markup | None:
    """Parse markup beginning at ``start``.

    Returns ``(end, tag_name, is_closing_tag, is_self_closing_tag)`` for a
    recognized construct, where ``end`` is exclusive.  ``tag_name`` is
    ``None`` for comments and declarations.  A candidate is accepted only
    when it starts like a real HTML tag; ordinary text such as ``a < b``
    therefore remains character tokenized.
    """
    if start >= len(text) or text[start] != '<':
        return None

    special = _parse_special_markup(text, start)
    if special is not None:
        return special
    return _parse_standard_tag(text, start)


def tokenize_chars_and_html(text: str) -> list[str]:
    """Split text into code points while preserving HTML markup as tokens.

    Tags, comments, declarations, processing instructions, and CDATA sections
    are kept as single tokens so diff markers are never inserted inside markup.
    Text outside markup is split into individual Unicode code points.  Raw-text
    element bodies (for example JavaScript inside ``<script>``) are treated as
    text until their matching closing tag, preventing operators such as ``<``
    from being mistaken for HTML.

    Args:
        text: Input text to tokenize.

    Returns:
        List of character and markup tokens whose concatenation equals ``text``.

    Examples:
        >>> tokenize_chars_and_html("<p>Hi</p>")
        ['<p>', 'H', 'i', '</p>']
        >>> tokenize_chars_and_html("one two")
        ['o', 'n', 'e', ' ', 't', 'w', 'o']
    """
    tokens: list[str] = []
    cursor = 0
    raw_text_element: str | None = None

    while cursor < len(text):
        if raw_text_element is not None:
            # In a raw-text element, only its matching closing tag is markup;
            # every other code point (including a stray ``<``) is text.
            if text[cursor] == '<':
                parsed = _parse_markup_at(text, cursor)
                if parsed and parsed[1] == raw_text_element and parsed[2]:
                    end, _, _, _ = parsed
                    tokens.append(text[cursor:end])
                    cursor = end
                    raw_text_element = None
                    continue
            tokens.append(text[cursor])
            cursor += 1
            continue

        if text[cursor] == '<':
            parsed = _parse_markup_at(text, cursor)
            if parsed:
                end, tag_name, is_closing, is_self_closing = parsed
                tokens.append(text[cursor:end])
                cursor = end
                if tag_name in _RAW_TEXT_ELEMENTS and not is_closing and not is_self_closing:
                    raw_text_element = tag_name
                continue

        tokens.append(text[cursor])
        cursor += 1

    return tokens
