# used for the notifications, the front-end is using a JS library

import difflib

# Can go via a nice Jinja2?
# only_differences - only return info about the differences, no context
def render_diff(previous_file, newest_file, only_differences=False):

    with open(newest_file, 'r') as f:
        newest_version_file_contents = f.read()
        newest_version_file_contents = [line.rstrip() for line in newest_version_file_contents.splitlines()]

    with open(previous_file, 'r') as f:
        previous_version_file_contents = f.read()
        previous_version_file_contents = [line.rstrip() for line in previous_version_file_contents.splitlines()]

    rendered_diff = difflib.Differ().compare(previous_version_file_contents,
                                             newest_version_file_contents)

    return rendered_diff