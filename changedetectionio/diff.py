import difflib
from typing import List, Iterator, Union

REMOVED_STYLE = "background-color: #fadad7; color: #b30000;"
ADDED_STYLE = "background-color: #eaf2c2; color: #406619;"

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
    html_colour: bool = False
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

    Yields:
        List[str]: Differences between sequences
    """
    cruncher = difflib.SequenceMatcher(isjunk=lambda x: x in " \t", a=before, b=after)



    for tag, alo, ahi, blo, bhi in cruncher.get_opcodes():
        if include_equal and tag == 'equal':
            yield before[alo:ahi]
        elif include_removed and tag == 'delete':
            if html_colour:
                yield [f'<span style="{REMOVED_STYLE}">{line}</span>' for line in same_slicer(before, alo, ahi)]
            else:
                yield [f"(removed) {line}" for line in same_slicer(before, alo, ahi)] if include_change_type_prefix else same_slicer(before, alo, ahi)
        elif include_replaced and tag == 'replace':
            if html_colour:
                yield [f'<span style="{REMOVED_STYLE}">{line}</span>' for line in same_slicer(before, alo, ahi)] + \
                      [f'<span style="{ADDED_STYLE}">{line}</span>' for line in same_slicer(after, blo, bhi)]
            else:
                yield [f"(changed) {line}" for line in same_slicer(before, alo, ahi)] + \
                      [f"(into) {line}" for line in same_slicer(after, blo, bhi)] if include_change_type_prefix else same_slicer(before, alo, ahi) + same_slicer(after, blo, bhi)
        elif include_added and tag == 'insert':
            if html_colour:
                yield [f'<span style="{ADDED_STYLE}">{line}</span>' for line in same_slicer(after, blo, bhi)]
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
    html_colour: bool = False
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
        html_colour=html_colour
    )

    def flatten(lst: List[Union[str, List[str]]]) -> str:
        return line_feed_sep.join(flatten(x) if isinstance(x, list) else x for x in lst)

    return flatten(rendered_diff)