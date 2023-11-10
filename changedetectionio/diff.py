# used for the notifications, the front-end is using a JS library

import difflib


def same_slicer(l, a, b):
    if a == b:
        return [l[a]]
    else:
        return l[a:b]

# like .compare but a little different output
def customSequenceMatcher(before, after, include_equal=False, include_removed=True, include_added=True, include_replaced=True, include_change_type_prefix=True):
    cruncher = difflib.SequenceMatcher(isjunk=lambda x: x in " \\t", a=before, b=after)

    # @todo Line-by-line mode instead of buncghed, including `after` that is not in `before` (maybe unset?)
    for tag, alo, ahi, blo, bhi in cruncher.get_opcodes():
        if include_equal and tag == 'equal':
            g = before[alo:ahi]
            yield g
        elif include_removed and tag == 'delete':
            row_prefix = "(removed) " if include_change_type_prefix else ''
            g = [ row_prefix + i for i in same_slicer(before, alo, ahi)]
            yield g
        elif include_replaced and tag == 'replace':
            row_prefix = "(changed) " if include_change_type_prefix else ''
            g = [row_prefix + i for i in same_slicer(before, alo, ahi)]
            row_prefix = "(into) " if include_change_type_prefix else ''
            g += [row_prefix + i for i in same_slicer(after, blo, bhi)]
            yield g
        elif include_added and tag == 'insert':
            row_prefix = "(added) " if include_change_type_prefix else ''
            g = [row_prefix + i for i in same_slicer(after, blo, bhi)]
            yield g

# only_differences - only return info about the differences, no context
# line_feed_sep could be "<br>" or "<li>" or "\n" etc
def render_diff(previous_version_file_contents, newest_version_file_contents, include_equal=False, include_removed=True, include_added=True, include_replaced=True, line_feed_sep="\n", include_change_type_prefix=True, patch_format=False):

    newest_version_file_contents = [line.rstrip() for line in newest_version_file_contents.splitlines()]

    if previous_version_file_contents:
        previous_version_file_contents = [line.rstrip() for line in previous_version_file_contents.splitlines()]
    else:
        previous_version_file_contents = ""

    if patch_format:
        patch = difflib.unified_diff(previous_version_file_contents, newest_version_file_contents)
        return line_feed_sep.join(patch)

    rendered_diff = customSequenceMatcher(before=previous_version_file_contents,
                                          after=newest_version_file_contents,
                                          include_equal=include_equal,
                                          include_removed=include_removed,
                                          include_added=include_added,
                                          include_replaced=include_replaced,
                                          include_change_type_prefix=include_change_type_prefix)

    # Recursively join lists
    f = lambda L: line_feed_sep.join([f(x) if type(x) is list else x for x in L])
    p= f(rendered_diff)
    return p
