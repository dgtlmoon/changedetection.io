# used for the notifications, the front-end is using a JS library

import difflib

# like .compare but a little different output
def customSequenceMatcher(before, after, include_equal=False):
    cruncher = difflib.SequenceMatcher(isjunk=lambda x: x in " \\t", a=before, b=after)

    for tag, alo, ahi, blo, bhi in cruncher.get_opcodes():
        if include_equal and tag == 'equal':
            g = before[alo:ahi]
            yield g
        elif tag == 'delete':
            g = "(removed) {}".format(before[alo])
            yield g
        elif tag == 'replace':
            g = ["(changed) {}".format(before[alo]), "(-> into) {}".format(after[blo])]
            yield g
        elif tag == 'insert':
            g = "(added) {}".format(after[blo])
            yield g

# only_differences - only return info about the differences, no context
# line_feed_sep could be "<br/>" or "<li>" or "\n" etc
def render_diff(previous_file, newest_file, include_equal=False, line_feed_sep="\n"):
    with open(newest_file, 'r') as f:
        newest_version_file_contents = f.read()
        newest_version_file_contents = [line.rstrip() for line in newest_version_file_contents.splitlines()]

    if previous_file:
        with open(previous_file, 'r') as f:
            previous_version_file_contents = f.read()
            previous_version_file_contents = [line.rstrip() for line in previous_version_file_contents.splitlines()]
    else:
        previous_version_file_contents = ""

    rendered_diff = customSequenceMatcher(previous_version_file_contents,
                                          newest_version_file_contents,
                                          include_equal)

    # Recursively join lists
    f = lambda L: line_feed_sep.join([f(x) if type(x) is list else x for x in L])
    return f(rendered_diff)
