"""
Diff rendering module for change detection.

This module provides functions for rendering differences between text content,
with support for various output formats and tokenization strategies.
"""

import difflib
from typing import List, Iterator, Union
import diff_match_patch as dmp_module
import re

from .tokenizers import TOKENIZERS, tokenize_words_and_html

# Remember! gmail, outlook etc dont support <style> must be inline.
# Gmail: strips <ins> and <del> tags entirely.
# This is for the WHOLE line background style
REMOVED_STYLE = "background-color: #fadad7; color: #b30000;"
ADDED_STYLE = "background-color: #eaf2c2; color: #406619;"
HTML_REMOVED_STYLE = REMOVED_STYLE  # Export alias for handler.py
HTML_ADDED_STYLE = ADDED_STYLE      # Export alias for handler.py

# Darker backgrounds for nested highlighting (changed parts within lines)
REMOVED_INNER_STYLE = "background-color: #ff867a; color: #111;"
ADDED_INNER_STYLE = "background-color: #b2e841; color: #444;"
HTML_CHANGED_STYLE = REMOVED_STYLE
HTML_CHANGED_INTO_STYLE = ADDED_STYLE

# Placemarker constants - these get replaced by apply_service_tweaks() in handler.py
# Something that cant get escaped to HTML by accident
REMOVED_PLACEMARKER_OPEN = '@removed_PLACEMARKER_OPEN'
REMOVED_PLACEMARKER_CLOSED = '@removed_PLACEMARKER_CLOSED'

ADDED_PLACEMARKER_OPEN = '@added_PLACEMARKER_OPEN'
ADDED_PLACEMARKER_CLOSED = '@added_PLACEMARKER_CLOSED'

CHANGED_PLACEMARKER_OPEN = '@changed_PLACEMARKER_OPEN'
CHANGED_PLACEMARKER_CLOSED = '@changed_PLACEMARKER_CLOSED'

CHANGED_INTO_PLACEMARKER_OPEN = '@changed_into_PLACEMARKER_OPEN'
CHANGED_INTO_PLACEMARKER_CLOSED = '@changed_into_PLACEMARKER_CLOSED'

# Compiled regex patterns for performance
WHITESPACE_NORMALIZE_RE = re.compile(r'\s+')


def render_inline_word_diff(before_line: str, after_line: str, ignore_junk: bool = False, markdown_style: str = None, tokenizer: str = 'words_and_html') -> tuple[str, bool]:
    """
    Render word-level differences between two lines inline using diff-match-patch library.

    Args:
        before_line: Original line text
        after_line: Modified line text
        ignore_junk: Ignore whitespace-only changes
        markdown_style: Unused (kept for backwards compatibility)
        tokenizer: Name of tokenizer to use from TOKENIZERS registry (default: 'words_and_html')

    Returns:
        tuple[str, bool]: (diff output with inline word-level highlighting, has_changes flag)
    """
    # Normalize whitespace if ignore_junk is enabled
    if ignore_junk:
        # Normalize whitespace: replace multiple spaces/tabs with single space
        before_normalized = WHITESPACE_NORMALIZE_RE.sub(' ', before_line)
        after_normalized = WHITESPACE_NORMALIZE_RE.sub(' ', after_line)
    else:
        before_normalized = before_line
        after_normalized = after_line

    # Use diff-match-patch with word-level tokenization
    # Strategy: Use linesToChars to treat words as atomic units
    dmp = dmp_module.diff_match_patch()

    # Get the tokenizer function from the registry
    tokenizer_func = TOKENIZERS.get(tokenizer, tokenize_words_and_html)

    # Tokenize both lines using the selected tokenizer
    before_tokens = tokenizer_func(before_normalized)
    after_tokens = tokenizer_func(after_normalized or ' ')

    # Create mappings for linesToChars (using it for word-mode)
    # Join tokens with newline so each "line" is a token
    before_text = '\n'.join(before_tokens)
    after_text = '\n'.join(after_tokens)

    # Use linesToChars for word-mode diffing
    lines_result = dmp.diff_linesToChars(before_text, after_text)
    line_before, line_after, line_array = lines_result

    # Perform diff on the encoded strings
    diffs = dmp.diff_main(line_before, line_after, False)

    # Convert back to original text
    dmp.diff_charsToLines(diffs, line_array)

    # Remove the newlines we added for tokenization
    diffs = [(op, text.replace('\n', '')) for op, text in diffs]

    # DON'T apply semantic cleanup here - it would break token boundaries
    # (e.g., "63" -> "66" would become "6" + "3" vs "6" + "6")
    # We want to preserve the tokenizer's word boundaries

    # Check if there are any changes
    has_changes = any(op != 0 for op, _ in diffs)

    if ignore_junk and not has_changes:
        return after_line, False

    # Check if the whole line is replaced (no unchanged content)
    whole_line_replaced = not any(op == 0 and text.strip() for op, text in diffs)

    # Build the output using placemarkers
    # When whole line is replaced, wrap entire removed content once and entire added content once
    if whole_line_replaced:
        removed_tokens = []
        added_tokens = []

        for op, text in diffs:
            if op == 0:  # Equal (e.g., whitespace tokens in common positions)
                # Include in both removed and added to preserve spacing
                removed_tokens.append(text)
                added_tokens.append(text)
            elif op == -1:  # Deletion
                removed_tokens.append(text)
            elif op == 1:  # Insertion
                added_tokens.append(text)

        # Join all tokens and wrap the entire string once for removed, once for added
        result_parts = []

        if removed_tokens:
            removed_full = ''.join(removed_tokens).rstrip()
            trailing_removed = ''.join(removed_tokens)[len(removed_full):] if len(''.join(removed_tokens)) > len(removed_full) else ''
            result_parts.append(f'{CHANGED_PLACEMARKER_OPEN}{removed_full}{CHANGED_PLACEMARKER_CLOSED}{trailing_removed}')

        if added_tokens:
            if result_parts:  # Add newline between removed and added
                result_parts.append('\n')
            added_full = ''.join(added_tokens).rstrip()
            trailing_added = ''.join(added_tokens)[len(added_full):] if len(''.join(added_tokens)) > len(added_full) else ''
            result_parts.append(f'{CHANGED_INTO_PLACEMARKER_OPEN}{added_full}{CHANGED_INTO_PLACEMARKER_CLOSED}{trailing_added}')

        return ''.join(result_parts), has_changes
    else:
        # Inline changes within the line
        result_parts = []
        for op, text in diffs:
            if op == 0:  # Equal
                result_parts.append(text)
            elif op == 1:  # Insertion
                # Don't wrap empty content (e.g., whitespace-only tokens after rstrip)
                content = text.rstrip()
                trailing = text[len(content):] if len(text) > len(content) else ''
                if content:
                    result_parts.append(f'{ADDED_PLACEMARKER_OPEN}{content}{ADDED_PLACEMARKER_CLOSED}{trailing}')
                else:
                    result_parts.append(trailing)
            elif op == -1:  # Deletion
                # Don't wrap empty content (e.g., whitespace-only tokens after rstrip)
                content = text.rstrip()
                trailing = text[len(content):] if len(text) > len(content) else ''
                if content:
                    result_parts.append(f'{REMOVED_PLACEMARKER_OPEN}{content}{REMOVED_PLACEMARKER_CLOSED}{trailing}')
                else:
                    result_parts.append(trailing)

        return ''.join(result_parts), has_changes


def render_nested_line_diff(before_line: str, after_line: str, ignore_junk: bool = False, tokenizer: str = 'words_and_html') -> tuple[str, str, bool]:
    """
    Render line-level differences with nested highlighting for changed parts.

    Returns two separate lines:
    - Before line: light red background with dark red on removed parts
    - After line: light green background with dark green on added parts

    Args:
        before_line: Original line text
        after_line: Modified line text
        ignore_junk: Ignore whitespace-only changes
        tokenizer: Name of tokenizer to use from TOKENIZERS registry

    Returns:
        tuple[str, str, bool]: (before_with_highlights, after_with_highlights, has_changes)
    """
    # Normalize whitespace if ignore_junk is enabled
    if ignore_junk:
        before_normalized = WHITESPACE_NORMALIZE_RE.sub(' ', before_line)
        after_normalized = WHITESPACE_NORMALIZE_RE.sub(' ', after_line)
    else:
        before_normalized = before_line
        after_normalized = after_line

    # Use diff-match-patch with word-level tokenization
    dmp = dmp_module.diff_match_patch()

    # Get the tokenizer function from the registry
    tokenizer_func = TOKENIZERS.get(tokenizer, tokenize_words_and_html)

    # Tokenize both lines
    before_tokens = tokenizer_func(before_normalized)
    after_tokens = tokenizer_func(after_normalized or ' ')

    # Create mappings for linesToChars
    before_text = '\n'.join(before_tokens)
    after_text = '\n'.join(after_tokens)

    # Use linesToChars for word-mode diffing
    lines_result = dmp.diff_linesToChars(before_text, after_text)
    line_before, line_after, line_array = lines_result

    # Perform diff on the encoded strings
    diffs = dmp.diff_main(line_before, line_after, False)

    # Convert back to original text
    dmp.diff_charsToLines(diffs, line_array)

    # Remove the newlines we added for tokenization
    diffs = [(op, text.replace('\n', '')) for op, text in diffs]

    # DON'T apply semantic cleanup here - it would break token boundaries
    # (e.g., "63" -> "66" would become "6" + "3" vs "6" + "6")
    # We want to preserve the tokenizer's word boundaries

    # Check if there are any changes
    has_changes = any(op != 0 for op, _ in diffs)

    if ignore_junk and not has_changes:
        return before_line, after_line, False

    # Build the before line (with nested highlighting for removed parts)
    before_parts = []
    for op, text in diffs:
        if op == 0:  # Equal
            before_parts.append(text)
        elif op == -1:  # Deletion (in before)
            before_parts.append(f'<span style="{REMOVED_INNER_STYLE}">{text}</span>')
        # Skip insertions (op == 1) for the before line

    before_content = ''.join(before_parts)

    # Build the after line (with nested highlighting for added parts)
    after_parts = []
    for op, text in diffs:
        if op == 0:  # Equal
            after_parts.append(text)
        elif op == 1:  # Insertion (in after)
            after_parts.append(f'<span style="{ADDED_INNER_STYLE}">{text}</span>')
        # Skip deletions (op == -1) for the after line

    after_content = ''.join(after_parts)

    # Wrap content with placemarkers (inner HTML highlighting is preserved)
    before_html = f'{CHANGED_PLACEMARKER_OPEN}{before_content}{CHANGED_PLACEMARKER_CLOSED}'
    after_html = f'{CHANGED_INTO_PLACEMARKER_OPEN}{after_content}{CHANGED_INTO_PLACEMARKER_CLOSED}'

    return before_html, after_html, has_changes


def same_slicer(lst: List[str], start: int, end: int) -> List[str]:
    """Return a slice of the list, or a single element if start == end."""
    return lst[start:end] if start != end else [lst[start]]

def customSequenceMatcher(
    before: List[str],
    after: List[str],
    include_equal: bool = False,
    include_removed: bool = True,
    include_added: bool = True,
    include_replaced: bool = True,
    include_change_type_prefix: bool = True,
    word_diff: bool = False,
    context_lines: int = 0,
    case_insensitive: bool = False,
    ignore_junk: bool = False,
    tokenizer: str = 'words_and_html'
) -> Iterator[List[str]]:
    """
    Compare two sequences and yield differences based on specified parameters.

    Args:
        before (List[str]): Original sequence
        after (List[str]): Modified sequence
        include_equal (bool): Include unchanged parts
        include_removed (bool): Include removed parts
        include_added (bool): Include added parts
        include_replaced (bool): Include replaced parts
        include_change_type_prefix (bool): Add prefixes to indicate change types
        word_diff (bool): Use word-level diffing for replaced lines (controls inline rendering)
        context_lines (int): Number of unchanged lines to show around changes (like grep -C)
        case_insensitive (bool): Perform case-insensitive comparison
        ignore_junk (bool): Ignore whitespace-only changes
        tokenizer (str): Name of tokenizer to use from TOKENIZERS registry (default: 'words_and_html')

    Yields:
        List[str]: Differences between sequences
    """
    # Prepare sequences for comparison (lowercase if case-insensitive, normalize whitespace if ignore_junk)
    def prepare_line(line):
        if case_insensitive:
            line = line.lower()
        if ignore_junk:
            # Normalize whitespace: replace multiple spaces/tabs with single space
            line = WHITESPACE_NORMALIZE_RE.sub(' ', line)
        return line

    compare_before = [prepare_line(line) for line in before]
    compare_after = [prepare_line(line) for line in after]

    cruncher = difflib.SequenceMatcher(isjunk=lambda x: x in " \t", a=compare_before, b=compare_after)

    # When context_lines is set and include_equal is False, we need to track which equal lines to include
    if context_lines > 0 and not include_equal:
        opcodes = list(cruncher.get_opcodes())
        # Mark equal ranges that should be included based on context
        included_equal_ranges = set()

        for i, (tag, alo, ahi, blo, bhi) in enumerate(opcodes):
            if tag != 'equal':
                # Include context lines before this change
                for j in range(max(0, i - 1), i):
                    if opcodes[j][0] == 'equal':
                        prev_alo, prev_ahi = opcodes[j][1], opcodes[j][2]
                        # Include last N lines of the previous equal block
                        context_start = max(prev_alo, prev_ahi - context_lines)
                        for line_num in range(context_start, prev_ahi):
                            included_equal_ranges.add(line_num)

                # Include context lines after this change
                for j in range(i + 1, min(len(opcodes), i + 2)):
                    if opcodes[j][0] == 'equal':
                        next_alo, next_ahi = opcodes[j][1], opcodes[j][2]
                        # Include first N lines of the next equal block
                        context_end = min(next_ahi, next_alo + context_lines)
                        for line_num in range(next_alo, context_end):
                            included_equal_ranges.add(line_num)

    # Remember! gmail, outlook etc dont support <style> must be inline.
    # Gmail: strips <ins> and <del> tags entirely.
    for tag, alo, ahi, blo, bhi in cruncher.get_opcodes():
        if tag == 'equal':
            if include_equal:
                yield before[alo:ahi]
            elif context_lines > 0:
                # Only include equal lines that are in the context range
                context_lines_to_include = [before[i] for i in range(alo, ahi) if i in included_equal_ranges]
                if context_lines_to_include:
                    yield context_lines_to_include
        elif include_removed and tag == 'delete':
            if include_change_type_prefix:
                yield [f'{REMOVED_PLACEMARKER_OPEN}{line}{REMOVED_PLACEMARKER_CLOSED}' for line in same_slicer(before, alo, ahi)]
            else:
                yield same_slicer(before, alo, ahi)
        elif include_replaced and tag == 'replace':
            before_lines = same_slicer(before, alo, ahi)
            after_lines = same_slicer(after, blo, bhi)

            # Use inline word-level diff for single line replacements when word_diff is enabled
            if word_diff and len(before_lines) == 1 and len(after_lines) == 1:
                inline_diff, has_changes = render_inline_word_diff(before_lines[0], after_lines[0], ignore_junk=ignore_junk, tokenizer=tokenizer)
                # Check if there are any actual changes (not just whitespace when ignore_junk is enabled)
                if ignore_junk and not has_changes:
                    # No real changes, skip this line
                    continue
                yield [inline_diff]
            else:
                # Fall back to line-level diff for multi-line changes
                if include_change_type_prefix:
                    yield [f'{CHANGED_PLACEMARKER_OPEN}{line}{CHANGED_PLACEMARKER_CLOSED}' for line in before_lines] + \
                          [f'{CHANGED_INTO_PLACEMARKER_OPEN}{line}{CHANGED_INTO_PLACEMARKER_CLOSED}' for line in after_lines]
                else:
                    yield before_lines + after_lines
        elif include_added and tag == 'insert':
            if include_change_type_prefix:
                yield [f'{ADDED_PLACEMARKER_OPEN}{line}{ADDED_PLACEMARKER_CLOSED}' for line in same_slicer(after, blo, bhi)]
            else:
                yield same_slicer(after, blo, bhi)

def render_diff(
    previous_version_file_contents: str,
    newest_version_file_contents: str,
    include_equal: bool = False,
    include_removed: bool = True,
    include_added: bool = True,
    include_replaced: bool = True,
    line_feed_sep: str = "\n",
    include_change_type_prefix: bool = True,
    patch_format: bool = False,
    word_diff: bool = True,
    context_lines: int = 0,
    case_insensitive: bool = False,
    ignore_junk: bool = False,
    tokenizer: str = 'words_and_html'
) -> str:
    """
    Render the difference between two file contents.

    Args:
        previous_version_file_contents (str): Original file contents
        newest_version_file_contents (str): Modified file contents
        include_equal (bool): Include unchanged parts
        include_removed (bool): Include removed parts
        include_added (bool): Include added parts
        include_replaced (bool): Include replaced parts
        line_feed_sep (str): Separator for lines in output
        include_change_type_prefix (bool): Add prefixes to indicate change types
        patch_format (bool): Use patch format for output
        word_diff (bool): Use word-level diffing for replaced lines (controls inline rendering)
        context_lines (int): Number of unchanged lines to show around changes (like grep -C)
        case_insensitive (bool): Perform case-insensitive comparison, By default the test_json_diff/process.py is case sensitive, so this follows same logic
        ignore_junk (bool): Ignore whitespace-only changes
        tokenizer (str): Name of tokenizer to use from TOKENIZERS registry (default: 'words_and_html')

    Returns:
        str: Rendered difference
    """
    newest_lines = [line.rstrip() for line in newest_version_file_contents.splitlines()]
    previous_lines = [line.rstrip() for line in previous_version_file_contents.splitlines()] if previous_version_file_contents else []

    if newest_lines == previous_lines:
        x=1

    if patch_format:
        patch = difflib.unified_diff(previous_lines, newest_lines)
        return line_feed_sep.join(patch)

    rendered_diff = customSequenceMatcher(
        before=previous_lines,
        after=newest_lines,
        include_equal=include_equal,
        include_removed=include_removed,
        include_added=include_added,
        include_replaced=include_replaced,
        include_change_type_prefix=include_change_type_prefix,
        word_diff=word_diff,
        context_lines=context_lines,
        case_insensitive=case_insensitive,
        ignore_junk=ignore_junk,
        tokenizer=tokenizer
    )

    def flatten(lst: List[Union[str, List[str]]]) -> str:
        result = []
        for x in lst:
            if isinstance(x, list):
                result.extend(x)
            else:
                result.append(x)
        return line_feed_sep.join(result)

    return flatten(rendered_diff)


# Export main public API
__all__ = [
    'render_diff',
    'customSequenceMatcher',
    'render_inline_word_diff',
    'render_nested_line_diff',
    'TOKENIZERS',
    'REMOVED_STYLE',
    'ADDED_STYLE',
    'REMOVED_INNER_STYLE',
    'ADDED_INNER_STYLE',
]
