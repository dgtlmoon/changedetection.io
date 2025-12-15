"""
Base data extraction module for all processors.

This module handles extracting data from watch history using regex patterns
and exporting to CSV format. This is the default extractor that all processors
(text_json_diff, restock_diff, etc.) can use by default or override.
"""

import os
from loguru import logger


def render_form(watch, datastore, request, url_for, render_template, flash, redirect, extract_form=None):
    """
    Render the data extraction form.

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
        Rendered HTML response with the extraction form
    """
    from changedetectionio import forms

    uuid = watch.get('uuid')

    # Use provided form or create a new one
    if extract_form is None:
        extract_form = forms.extractDataForm(
            formdata=request.form,
            data={'extract_regex': request.form.get('extract_regex', '')}
        )

    # Get error information for the template
    screenshot_url = watch.get_screenshot()

    system_uses_webdriver = datastore.data['settings']['application']['fetch_backend'] == 'html_webdriver'
    is_html_webdriver = False
    if (watch.get('fetch_backend') == 'system' and system_uses_webdriver) or watch.get('fetch_backend') == 'html_webdriver' or watch.get('fetch_backend', '').startswith('extra_browser_'):
        is_html_webdriver = True

    password_enabled_and_share_is_off = False
    if datastore.data['settings']['application'].get('password') or os.getenv("SALTED_PASS", False):
        password_enabled_and_share_is_off = not datastore.data['settings']['application'].get('shared_diff_access')

    # Use the shared default template from processors/templates/
    # Processors can override this by creating their own extract.py with custom template logic
    output = render_template(
        "extract.html",
        uuid=uuid,
        extract_form=extract_form,
        watch_a=watch,
        last_error=watch['last_error'],
        last_error_screenshot=watch.get_error_snapshot(),
        last_error_text=watch.get_error_text(),
        screenshot=screenshot_url,
        is_html_webdriver=is_html_webdriver,
        password_enabled_and_share_is_off=password_enabled_and_share_is_off,
        extra_title=f" - {watch.label} - Extract Data",
        extra_stylesheets=[url_for('static_content', group='styles', filename='diff.css')],
        pure_menu_fixed=False
    )

    return output


def process_extraction(watch, datastore, request, url_for, make_response, send_from_directory, flash, redirect, extract_form=None):
    """
    Process the data extraction request and return CSV file.

    Args:
        watch: The watch object
        datastore: The ChangeDetectionStore instance
        request: Flask request object
        url_for: Flask url_for function
        make_response: Flask make_response function
        send_from_directory: Flask send_from_directory function
        flash: Flask flash function
        redirect: Flask redirect function
        extract_form: Optional pre-built extract form

    Returns:
        CSV file download response or redirect to form on error
    """
    from changedetectionio import forms

    uuid = watch.get('uuid')

    # Use provided form or create a new one
    if extract_form is None:
        extract_form = forms.extractDataForm(
            formdata=request.form,
            data={'extract_regex': request.form.get('extract_regex', '')}
        )

    if not extract_form.validate():
        flash("An error occurred, please see below.", "error")
        # render_template needs to be imported from Flask for this to work
        from flask import render_template as flask_render_template
        return render_form(
            watch=watch,
            datastore=datastore,
            request=request,
            url_for=url_for,
            render_template=flask_render_template,
            flash=flash,
            redirect=redirect,
            extract_form=extract_form
        )

    extract_regex = request.form.get('extract_regex', '').strip()
    output = watch.extract_regex_from_all_history(extract_regex)

    if output:
        watch_dir = os.path.join(datastore.datastore_path, uuid)
        response = make_response(send_from_directory(directory=watch_dir, path=output, as_attachment=True))
        response.headers['Content-type'] = 'text/csv'
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = "0"
        return response

    flash('No matches found while scanning all of the watch history for that RegEx.', 'error')
    return redirect(url_for('ui.ui_diff.diff_history_page_extract_GET', uuid=uuid))
