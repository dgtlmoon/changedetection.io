"""
Simple word tokenizer using whitespace boundaries.

This is a simpler tokenizer that treats all whitespace as token boundaries
without special handling for HTML tags or other markup.
"""

from typing import List


def tokenize_words(text: str) -> List[str]:
    """
    Split text into words using simple whitespace boundaries.

    This is a simpler tokenizer that treats all whitespace as token boundaries
    without special handling for HTML tags.

    Args:
        text: Input text to tokenize

    Returns:
        List of tokens (words and whitespace)

    Examples:
        >>> tokenize_words("Hello world")
        ['Hello', ' ', 'world']
        >>> tokenize_words("one  two")
        ['one', ' ', ' ', 'two']
    """
    tokens = []
    current = ''

    for char in text:
        if char.isspace():
            if current:
                tokens.append(current)
                current = ''
            tokens.append(char)
        else:
            current += char

    if current:
        tokens.append(current)
    return tokens
