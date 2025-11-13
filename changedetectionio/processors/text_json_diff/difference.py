"""
History/diff rendering for text_json_diff processor.

This module handles the visualization of text/HTML/JSON changes by rendering
a side-by-side or unified diff view with syntax highlighting and change markers.
"""

import os
import time
from loguru import logger
from markupsafe import Markup

from changedetectionio import diff, strtobool
from changedetectionio.diff import (
    REMOVED_STYLE, ADDED_STYLE, REMOVED_INNER_STYLE, ADDED_INNER_STYLE,
    REMOVED_PLACEMARKER_OPEN, REMOVED_PLACEMARKER_CLOSED,
    ADDED_PLACEMARKER_OPEN, ADDED_PLACEMARKER_CLOSED,
    CHANGED_PLACEMARKER_OPEN, CHANGED_PLACEMARKER_CLOSED,
    CHANGED_INTO_PLACEMARKER_OPEN, CHANGED_INTO_PLACEMARKER_CLOSED
)
from changedetectionio.notification.handler import apply_html_color_to_body


# Diff display preferences configuration - single source of truth
DIFF_PREFERENCES_CONFIG = {
    'changesOnly': {'default': True, 'type': 'bool'},
    'ignoreWhitespace': {'default': False, 'type': 'bool'},
    'removed': {'default': True, 'type': 'bool'},
    'added': {'default': True, 'type': 'bool'},
    'replaced': {'default': True, 'type': 'bool'},
    'type': {'default': 'diffLines', 'type': 'value'},
}


def build_diff_cell_visualizer(content, resolution=100):
    """
    Build a visual cell grid for the diff visualizer.

    Analyzes the content for placemarkers indicating changes and creates a
    grid of cells representing the document, with each cell marked as:
    - 'deletion' for removed content
    - 'insertion' for added content
    - 'mixed' for cells containing both deletions and insertions
    - empty string for cells with no changes

    Args:
        content: The diff content with placemarkers
        resolution: Number of cells to create (default 100)

    Returns:
        List of dicts with 'class' key for each cell's CSS class
    """
    if not content:
        return [{'class': ''} for _ in range(resolution)]
    now = time.time()
    # Work with character positions for better accuracy
    content_length = len(content)

    if content_length == 0:
        return [{'class': ''} for _ in range(resolution)]

    chars_per_cell = max(1, content_length / resolution)

    # Track change type for each cell
    cell_data = {}

    # Placemarkers to detect
    change_markers = {
        REMOVED_PLACEMARKER_OPEN: 'deletion',
        ADDED_PLACEMARKER_OPEN: 'insertion',
        CHANGED_PLACEMARKER_OPEN: 'deletion',
        CHANGED_INTO_PLACEMARKER_OPEN: 'insertion',
    }

    # Find all occurrences of each marker
    for marker, change_type in change_markers.items():
        pos = 0
        while True:
            pos = content.find(marker, pos)
            if pos == -1:
                break

            # Calculate which cell this marker falls into
            cell_index = min(int(pos / chars_per_cell), resolution - 1)

            if cell_index not in cell_data:
                cell_data[cell_index] = change_type
            elif cell_data[cell_index] != change_type:
                # Mixed changes in this cell
                cell_data[cell_index] = 'mixed'

            pos += len(marker)

    # Build the cell list
    cells = []
    for i in range(resolution):
        change_type = cell_data.get(i, '')
        cells.append({'class': change_type})

    logger.debug(f"Built diff cell visualizer: {len([c for c in cells if c['class']])} cells with changes out of {resolution} in {time.time() - now:.2f}s")

    return cells


def render(watch, datastore, request, url_for, render_template, flash, redirect, extract_form=None):
    """
    Render the history/diff view for text/JSON/HTML changes.

    Args:
        watch: The watch object
        datastore: The ChangeDetectionStore instance
        request: Flask request object
        url_for: Flask url_for function
        render_template: Flask render_template function
        flash: Flask flash function
        redirect: Flask redirect function
        extract_form: Optional pre-built extract form (for error cases)

    Returns:
        Rendered HTML response
    """
    from changedetectionio import forms

    uuid = watch.get('uuid')

    extra_stylesheets = [url_for('static_content', group='styles', filename='diff.css')]

    # Use provided form or create a new one
    if extract_form is None:
        extract_form = forms.extractDataForm(formdata=request.form,
                                             data={'extract_regex': request.form.get('extract_regex', '')}
                                             )
    history = watch.history
    dates = list(history.keys())

    # If a "from_version" was requested, then find it (or the closest one)
    # Also set "from version" to be the closest version to the one that was last viewed.

    best_last_viewed_timestamp = watch.get_from_version_based_on_last_viewed
    from_version_timestamp = best_last_viewed_timestamp if best_last_viewed_timestamp else dates[-2]
    from_version = request.args.get('from_version', from_version_timestamp )

    # Use the current one if nothing was specified
    to_version = request.args.get('to_version', str(dates[-1]))

    try:
        to_version_file_contents = watch.get_history_snapshot(timestamp=to_version)
    except Exception as e:
        logger.error(f"Unable to read watch history to-version for version {to_version}: {str(e)}")
        to_version_file_contents = f"Unable to read to-version at {to_version}.\n"

    try:
        from_version_file_contents = watch.get_history_snapshot(timestamp=from_version)
    except Exception as e:
        logger.error(f"Unable to read watch history from-version for version {from_version}: {str(e)}")
        from_version_file_contents = f"Unable to read to-version {from_version}.\n"

    screenshot_url = watch.get_screenshot()

    system_uses_webdriver = datastore.data['settings']['application']['fetch_backend'] == 'html_webdriver'

    is_html_webdriver = False
    if (watch.get('fetch_backend') == 'system' and system_uses_webdriver) or watch.get('fetch_backend') == 'html_webdriver' or watch.get('fetch_backend', '').startswith('extra_browser_'):
        is_html_webdriver = True

    password_enabled_and_share_is_off = False
    if datastore.data['settings']['application'].get('password') or os.getenv("SALTED_PASS", False):
        password_enabled_and_share_is_off = not datastore.data['settings']['application'].get('shared_diff_access')

    datastore.set_last_viewed(uuid, time.time())

    # Parse diff preferences from request using config as single source of truth
    # Check if this is a user submission (any diff pref param exists in query string)
    user_submitted = any(key in request.args for key in DIFF_PREFERENCES_CONFIG.keys())

    diff_prefs = {}
    for key, config in DIFF_PREFERENCES_CONFIG.items():
        if user_submitted:
            # User submitted form - missing checkboxes are explicitly OFF
            if config['type'] == 'bool':
                diff_prefs[key] = strtobool(request.args.get(key, 'off'))
            else:
                diff_prefs[key] = request.args.get(key, config['default'])
        else:
            # Initial load - use defaults from config
            diff_prefs[key] = config['default']

    content = diff.render_diff(previous_version_file_contents=from_version_file_contents,
                               newest_version_file_contents=to_version_file_contents,
                               include_replaced=diff_prefs['replaced'],
                               include_added=diff_prefs['added'],
                               include_removed=diff_prefs['removed'],
                               include_equal=diff_prefs['changesOnly'],
                               ignore_junk=diff_prefs['ignoreWhitespace'],
                               word_diff=diff_prefs['type'] == 'diffWords',
                               )

    # Build cell grid visualizer before applying HTML color (so we can detect placemarkers)
    diff_cell_grid = build_diff_cell_visualizer(content)

    content = apply_html_color_to_body(n_body=content)
    offscreen_content = render_template("diff-offscreen-options.html")

    note = ''
    if str(from_version) != str(dates[-2]) or str(to_version) != str(dates[-1]):
        note = 'Note: You are not viewing the latest changes.'

    output = render_template("diff.html",
                             #initial_scroll_line_number=100,
                             bottom_horizontal_offscreen_contents=offscreen_content,
                             content=content,
                             current_diff_url=watch['url'],
                             diff_cell_grid=diff_cell_grid,
                             diff_prefs=diff_prefs,
                             extra_classes='difference-page',
                             extra_stylesheets=extra_stylesheets,
                             extra_title=f" - {watch.label} - History",
                             extract_form=extract_form,
                             from_version=str(from_version),
                             is_html_webdriver=is_html_webdriver,
                             last_error=watch['last_error'],
                             last_error_screenshot=watch.get_error_snapshot(),
                             last_error_text=watch.get_error_text(),
                             newest=to_version_file_contents,
                             newest_version_timestamp=dates[-1],
                             note=note,
                             password_enabled_and_share_is_off=password_enabled_and_share_is_off,
                             pure_menu_fixed=False,
                             screenshot=screenshot_url,
                             to_version=str(to_version),
                             uuid=uuid,
                             versions=dates,  # All except current/last
                             watch_a=watch,
                             )
    return output
