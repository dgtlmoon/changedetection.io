from flask import Blueprint, request, url_for, flash, render_template, redirect
from flask_babel import gettext
import time
from loguru import logger

from changedetectionio.store import ChangeDetectionStore
from changedetectionio.auth_decorator import login_optionally_required
from changedetectionio import html_tools

def construct_blueprint(datastore: ChangeDetectionStore):
    preview_blueprint = Blueprint('ui_preview', __name__, template_folder="../ui/templates")

    @preview_blueprint.route("/preview/<string:uuid>", methods=['GET'])
    @login_optionally_required
    def preview_page(uuid):
        """
        Render the preview page for a watch.

        This route is processor-aware: it delegates rendering to the processor's
        preview.py module, allowing different processor types to provide
        custom visualizations:
        - text_json_diff: Text preview with syntax highlighting
        - image_ssim_diff: Image preview with proper rendering
        - restock_diff: Could show latest price/stock data

        Each processor implements processors/{type}/preview.py::render()
        If a processor doesn't have a preview module, falls back to default text preview.
        """
        # More for testing, possible to return the first/only
        if uuid == 'first':
            uuid = list(datastore.data['watching'].keys()).pop()

        try:
            watch = datastore.data['watching'][uuid]
        except KeyError:
            flash(gettext("No history found for the specified link, bad link?"), "error")
            return redirect(url_for('watchlist.index'))

        # Get the processor type for this watch
        processor_name = watch.get('processor', 'text_json_diff')

        try:
            # Try to import the processor's preview module
            import importlib
            processor_module = importlib.import_module(f'changedetectionio.processors.{processor_name}.preview')

            # Call the processor's render() function
            if hasattr(processor_module, 'render'):
                return processor_module.render(
                    watch=watch,
                    datastore=datastore,
                    request=request,
                    url_for=url_for,
                    render_template=render_template,
                    flash=flash,
                    redirect=redirect
                )
        except (ImportError, ModuleNotFoundError) as e:
            logger.debug(f"Processor {processor_name} does not have a preview module, using default preview: {e}")

        # Fallback: if processor doesn't have preview module, use default text preview
        content = []
        versions = []
        timestamp = None

        system_uses_webdriver = datastore.data['settings']['application']['fetch_backend'] == 'html_webdriver'
        extra_stylesheets = [url_for('static_content', group='styles', filename='diff.css')]

        is_html_webdriver = False
        if (watch.get('fetch_backend') == 'system' and system_uses_webdriver) or watch.get('fetch_backend') == 'html_webdriver' or watch.get('fetch_backend', '').startswith('extra_browser_'):
            is_html_webdriver = True

        triggered_line_numbers = []
        ignored_line_numbers = []
        blocked_line_numbers = []
        block_words_line_numbers = []
        trigger_words_line_numbers = []

        if datastore.data['watching'][uuid].history_n == 0 and (watch.get_error_text() or watch.get_error_snapshot()):
            flash(gettext("Preview unavailable - No fetch/check completed or triggers not reached"), "error")
        else:
            # So prepare the latest preview or not
            preferred_version = request.args.get('version')
            versions = list(watch.history.keys())
            timestamp = versions[-1]
            if preferred_version and preferred_version in versions:
                timestamp = preferred_version

            try:
                versions = list(watch.history.keys())
                content = watch.get_history_snapshot(timestamp=timestamp)

                triggered_line_numbers = html_tools.strip_ignore_text(content=content,
                                                                      wordlist=watch.get('trigger_text'),
                                                                      mode='line numbers'
                                                                      )
                ignored_line_numbers = html_tools.strip_ignore_text(content=content,
                                                                      wordlist=watch.get('ignore_text'),
                                                                      mode='line numbers'
                                                                      )
                blocked_line_numbers = html_tools.strip_ignore_text(content=content,
                                                                      wordlist=watch.get("text_should_not_be_present"),
                                                                      mode='line numbers'
                                                                      )
                # Watch words highlighting
                block_words_line_numbers = html_tools.strip_ignore_text(content=content,
                                                                      wordlist=watch.get('block_words'),
                                                                      mode='line numbers'
                                                                      )
                trigger_words_line_numbers = html_tools.strip_ignore_text(content=content,
                                                                      wordlist=watch.get('trigger_words'),
                                                                      mode='line numbers'
                                                                      )
            except Exception as e:
                content.append({'line': f"File doesnt exist or unable to read timestamp {timestamp}", 'classes': ''})

        from changedetectionio.pluggy_interface import get_fetcher_capabilities
        capabilities = get_fetcher_capabilities(watch, datastore)

        output = render_template("preview.html",
                                 capabilities=capabilities,
                                 content=content,
                                 current_diff_url=watch['url'],
                                 current_version=timestamp,
                                 extra_stylesheets=extra_stylesheets,
                                 extra_title=f" - Diff - {watch.label} @ {timestamp}",
                                 highlight_ignored_line_numbers=ignored_line_numbers,
                                 highlight_triggered_line_numbers=triggered_line_numbers,
                                 highlight_blocked_line_numbers=blocked_line_numbers,
                                 highlight_block_words_line_numbers=block_words_line_numbers,
                                 highlight_trigger_words_line_numbers=trigger_words_line_numbers,
                                 history_n=watch.history_n,
                                 is_html_webdriver=is_html_webdriver,
                                 last_error=watch['last_error'],
                                 last_error_screenshot=watch.get_error_snapshot(),
                                 last_error_text=watch.get_error_text(),
                                 screenshot=watch.get_screenshot(),
                                 uuid=uuid,
                                 versions=versions,
                                 watch=watch,
                                 )

        return output

    @preview_blueprint.route("/preview/<string:uuid>/processor-asset/<string:asset_name>", methods=['GET'])
    @login_optionally_required
    def processor_asset(uuid, asset_name):
        """
        Serve processor-specific binary assets for preview (images, files, etc.).

        This route is processor-aware: it delegates to the processor's
        preview.py module, allowing different processor types to serve
        custom assets without embedding them as base64 in templates.

        This solves memory issues with large binary data by streaming them
        as separate HTTP responses instead of embedding in the HTML template.

        Each processor implements processors/{type}/preview.py::get_asset()
        which returns (binary_data, content_type, cache_control_header).

        Example URLs:
        - /preview/{uuid}/processor-asset/screenshot?version=123456789
        """
        from flask import make_response

        # More for testing, possible to return the first/only
        if uuid == 'first':
            uuid = list(datastore.data['watching'].keys()).pop()

        try:
            watch = datastore.data['watching'][uuid]
        except KeyError:
            flash(gettext("No history found for the specified link, bad link?"), "error")
            return redirect(url_for('watchlist.index'))

        # Get the processor type for this watch
        processor_name = watch.get('processor', 'text_json_diff')

        try:
            # Try to import the processor's preview module
            import importlib
            processor_module = importlib.import_module(f'changedetectionio.processors.{processor_name}.preview')

            # Call the processor's get_asset() function
            if hasattr(processor_module, 'get_asset'):
                result = processor_module.get_asset(
                    asset_name=asset_name,
                    watch=watch,
                    datastore=datastore,
                    request=request
                )

                if result is None:
                    from flask import abort
                    abort(404, description=f"Asset '{asset_name}' not found")

                binary_data, content_type, cache_control = result

                response = make_response(binary_data)
                response.headers['Content-Type'] = content_type
                if cache_control:
                    response.headers['Cache-Control'] = cache_control
                return response
            else:
                logger.warning(f"Processor {processor_name} does not implement get_asset()")
                from flask import abort
                abort(404, description=f"Processor '{processor_name}' does not support assets")

        except (ImportError, ModuleNotFoundError) as e:
            logger.warning(f"Processor {processor_name} does not have a preview module: {e}")
            from flask import abort
            abort(404, description=f"Processor '{processor_name}' not found")

    return preview_blueprint
