"""
Tokenizer that preserves HTML tags as atomic units while splitting on whitespace.

This tokenizer is specifically designed for HTML content where:
- HTML tags should remain intact (e.g., '<p>', '<a href="...">')
- Whitespace tokens are preserved for accurate diff reconstruction
- Words are split on whitespace boundaries
"""

from typing import List


def tokenize_words_and_html(text: str) -> List[str]:
    """
    Split text into words and boundaries (spaces, HTML tags).

    This tokenizer preserves HTML tags as atomic units while splitting on whitespace.
    Useful for content that contains HTML markup.

    Args:
        text: Input text to tokenize

    Returns:
        List of tokens (words, spaces, HTML tags)

    Examples:
        >>> tokenize_words_and_html("<p>Hello world</p>")
        ['<p>', 'Hello', ' ', 'world', '</p>']
        >>> tokenize_words_and_html("<a href='test.com'>link</a>")
        ['<a href=\\'test.com\\'>', 'link', '</a>']
    """
    tokens = []
    current = ''
    in_tag = False

    for char in text:
        if char == '<':
            # Start of HTML tag
            if current:
                tokens.append(current)
                current = ''
            current = '<'
            in_tag = True
        elif char == '>' and in_tag:
            # End of HTML tag
            current += '>'
            tokens.append(current)
            current = ''
            in_tag = False
        elif char.isspace() and not in_tag:
            # Space outside of tag
            if current:
                tokens.append(current)
                current = ''
            tokens.append(char)
        else:
            current += char

    if current:
        tokens.append(current)
    return tokens
