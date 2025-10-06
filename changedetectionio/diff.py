import difflib
from typing import List, Iterator, Union
from redlines import Redlines
import re

# Remember! gmail, outlook etc dont support <style> must be inline.
# Gmail: strips <ins> and <del> tags entirely.
REMOVED_STYLE = "background-color: #fadad7; color: #b30000;"
ADDED_STYLE = "background-color: #eaf2c2; color: #406619;"

# Compiled regex patterns for performance
WHITESPACE_NORMALIZE_RE = re.compile(r'\s+')
REDLINES_REMOVED_RE = re.compile(r"<span style='color:red;font-weight:700;text-decoration:line-through;'>([^<]*)</span>")
REDLINES_ADDED_RE = re.compile(r"<span style='color:green;font-weight:700;'>([^<]*)</span>")


def render_inline_word_diff(before_line: str, after_line: str, html_colour: bool = False, ignore_junk: bool = False, markdown_style: str = None) -> str:
    """
    Render word-level differences between two lines inline using redlines library.

    Args:
        before_line: Original line text
        after_line: Modified line text
        html_colour: Use HTML background colors for differences
        ignore_junk: Ignore whitespace-only changes
        markdown_style: Redlines markdown style ("red-green", "none", "red", "ghfm", "bbcode", "streamlit", "custom_css")
                       If None, uses default with custom inline style replacement

    Returns:
        str: Single line with inline word-level highlighting
    """
    # Normalize whitespace if ignore_junk is enabled
    if ignore_junk:
        # Normalize whitespace: replace multiple spaces/tabs with single space
        before_normalized = WHITESPACE_NORMALIZE_RE.sub(' ', before_line)
        after_normalized = WHITESPACE_NORMALIZE_RE.sub(' ', after_line)
    else:
        before_normalized = before_line
        after_normalized = after_line

    # Use redlines for word-level comparison
    if markdown_style:
        redlines = Redlines(before_normalized, after_normalized or ' ', markdown_style=markdown_style)
    else:
        redlines = Redlines(before_normalized, after_normalized or ' ')
    diff_output = redlines.output_markdown

    if html_colour:
        # Replace redlines' default styles with our custom inline styles
        # Strip trailing spaces from content but preserve them outside the span
        def replace_removed(m):
            content = m.group(1).rstrip()
            trailing = m.group(1)[len(content):] if len(m.group(1)) > len(content) else ''
            return f'<span style="{REMOVED_STYLE}" title="Removed">{content}</span>{trailing}'

        def replace_added(m):
            content = m.group(1).rstrip()
            trailing = m.group(1)[len(content):] if len(m.group(1)) > len(content) else ''
            return f'<span style="{ADDED_STYLE}" title="Added">{content}</span>{trailing}'

        diff_output = REDLINES_REMOVED_RE.sub(replace_removed, diff_output)
        diff_output = REDLINES_ADDED_RE.sub(replace_added, diff_output)

        # Handle ignore_junk - check if there are any actual changes
        if ignore_junk and REMOVED_STYLE not in diff_output and ADDED_STYLE not in diff_output:
            return after_line
    else:
        # Convert redlines HTML to plain text markers
        # Strip trailing spaces from content but preserve them outside the markers
        def replace_removed_plain(m):
            content = m.group(1).rstrip()
            trailing = m.group(1)[len(content):] if len(m.group(1)) > len(content) else ''
            return f'[-{content}-]{trailing}'

        def replace_added_plain(m):
            content = m.group(1).rstrip()
            trailing = m.group(1)[len(content):] if len(m.group(1)) > len(content) else ''
            return f'[+{content}+]{trailing}'

        diff_output = REDLINES_REMOVED_RE.sub(replace_removed_plain, diff_output)
        diff_output = REDLINES_ADDED_RE.sub(replace_added_plain, diff_output)

        # Handle ignore_junk - check if there are any actual changes
        if ignore_junk and '[-' not in diff_output and '[+' not in diff_output:
            return after_line

    return diff_output

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
    html_colour: bool = False,
    word_diff: bool = False,
    context_lines: int = 0,
    case_insensitive: bool = False,
    ignore_junk: bool = False
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
        html_colour (bool): Use HTML background colors for differences
        word_diff (bool): Use word-level diffing for replaced lines
        context_lines (int): Number of unchanged lines to show around changes (like grep -C)
        case_insensitive (bool): Perform case-insensitive comparison
        ignore_junk (bool): Ignore whitespace-only changes

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
            if html_colour:
                yield [f'<span style="{REMOVED_STYLE}" title="Removed">{line}</span>' for line in same_slicer(before, alo, ahi)]
            else:
                yield [f"(removed) {line}" for line in same_slicer(before, alo, ahi)] if include_change_type_prefix else same_slicer(before, alo, ahi)
        elif include_replaced and tag == 'replace':
            before_lines = same_slicer(before, alo, ahi)
            after_lines = same_slicer(after, blo, bhi)

            # Use word-level diff for single line replacements when enabled
            if word_diff and len(before_lines) == 1 and len(after_lines) == 1:
                inline_diff = render_inline_word_diff(before_lines[0], after_lines[0], html_colour, ignore_junk)
                # Check if there are any actual changes (not just whitespace when ignore_junk is enabled)
                if ignore_junk:
                    # Check if the output contains any change markers
                    if html_colour:
                        has_changes = '<span style=' in inline_diff
                    else:
                        has_changes = '[-' in inline_diff or '[+' in inline_diff
                    if not has_changes:
                        # No real changes, skip this line
                        continue
                yield [inline_diff]
            else:
                # Fall back to line-level diff for multi-line changes or when word_diff disabled
                if html_colour:
                    yield [f'<span style="{REMOVED_STYLE}" title="Removed">{line}</span>' for line in before_lines] + \
                          [f'<span style="{ADDED_STYLE}" title="Replaced">{line}</span>' for line in after_lines]
                else:
                    yield [f"(changed) {line}" for line in before_lines] + \
                          [f"(into) {line}" for line in after_lines] if include_change_type_prefix else before_lines + after_lines
        elif include_added and tag == 'insert':
            if html_colour:
                yield [f'<span style="{ADDED_STYLE}" title="Inserted">{line}</span>' for line in same_slicer(after, blo, bhi)]
            else:
                yield [f"(added) {line}" for line in same_slicer(after, blo, bhi)] if include_change_type_prefix else same_slicer(after, blo, bhi)

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
    html_colour: bool = False,
    word_diff: bool = True,
    context_lines: int = 0,
    case_insensitive: bool = False,
    ignore_junk: bool = False
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
        html_colour (bool): Use HTML background colors for differences
        word_diff (bool): Use word-level diffing for replaced lines
        context_lines (int): Number of unchanged lines to show around changes (like grep -C)
        case_insensitive (bool): Perform case-insensitive comparison, By default the test_json_diff/process.py is case sensitive, so this follows same logic
        ignore_junk (bool): Ignore whitespace-only changes

    Returns:
        str: Rendered difference
    """
    newest_lines = [line.rstrip() for line in newest_version_file_contents.splitlines()]
    previous_lines = [line.rstrip() for line in previous_version_file_contents.splitlines()] if previous_version_file_contents else []

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
        html_colour=html_colour,
        word_diff=word_diff,
        context_lines=context_lines,
        case_insensitive=case_insensitive,
        ignore_junk=ignore_junk
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