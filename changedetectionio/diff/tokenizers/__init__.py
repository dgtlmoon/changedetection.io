"""
Tokenizers for diff operations.

This module provides various tokenization strategies for use with the diff system.
New tokenizers can be easily added by:
1. Creating a new module in this directory
2. Importing and registering it in the TOKENIZERS dictionary below
"""

from .natural_text import tokenize_words
from .words_and_html import tokenize_words_and_html

# Tokenizer registry - maps tokenizer names to functions
TOKENIZERS = {
    'words': tokenize_words,
    'words_and_html': tokenize_words_and_html,
    'html_tags': tokenize_words_and_html,  # Alias for backwards compatibility
}

__all__ = [
    'tokenize_words',
    'tokenize_words_and_html',
    'TOKENIZERS',
]
