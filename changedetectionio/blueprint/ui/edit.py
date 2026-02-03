from copy import deepcopy
import os
import importlib.resources
from flask import Blueprint, request, redirect, url_for, flash, render_template, abort
from flask_babel import gettext
from loguru import logger
from jinja2 import Environment, FileSystemLoader

from changedetectionio.store import ChangeDetectionStore
from changedetectionio.auth_decorator import login_optionally_required
from changedetectionio.time_handler import is_within_schedule
from changedetectionio import worker_pool

def construct_blueprint(datastore: ChangeDetectionStore, update_q, queuedWatchMetaData):
    edit_blueprint = Blueprint('ui_edit', __name__, template_folder="../ui/templates")
    
    def _watch_has_tag_options_set(watch):
        """This should be fixed better so that Tag is some proper Model, a tag is just a Watch also"""
        for tag_uuid, tag in datastore.data['settings']['application'].get('tags', {}).items():
            if tag_uuid in watch.get('tags', []) and (tag.get('include_filters') or tag.get('subtractive_selectors')):
                return True

    @edit_blueprint.route("/edit/<string:uuid>", methods=['GET', 'POST'])
    @login_optionally_required
    # https://stackoverflow.com/questions/42984453/wtforms-populate-form-with-data-if-data-exists
    # https://wtforms.readthedocs.io/en/3.0.x/forms/#wtforms.form.Form.populate_obj ?
    def edit_page(uuid):
        from changedetectionio import forms
        from changedetectionio.blueprint.browser_steps.browser_steps import browser_step_ui_config
        from changedetectionio import processors
        import importlib

        if uuid == 'first':
            uuid = list(datastore.data['watching'].keys()).pop()
        # More for testing, possible to return the first/only
        if not datastore.data['watching'].keys():
            flash(gettext("No watches to edit"), "error")
            return redirect(url_for('watchlist.index'))

        if not uuid in datastore.data['watching']:
            flash(gettext("No watch with the UUID {} found.").format(uuid), "error")
            return redirect(url_for('watchlist.index'))

        switch_processor = request.args.get('switch_processor')
        if switch_processor:
            for p in processors.available_processors():
                if p[0] == switch_processor:
                    datastore.data['watching'][uuid]['processor'] = switch_processor
                    flash(gettext("Switched to mode - {}.").format(p[1]))
                    datastore.clear_watch_history(uuid)
                    redirect(url_for('ui_edit.edit_page', uuid=uuid))

        # be sure we update with a copy instead of accidently editing the live object by reference
        default = None
        while not default:
            try:
                default = deepcopy(datastore.data['watching'][uuid])
            except RuntimeError as e:
                # Dictionary changed
                continue

        # Defaults for proxy choice
        if datastore.proxy_list is not None:  # When enabled
            # @todo
            # Radio needs '' not None, or incase that the chosen one no longer exists
            if default['proxy'] is None or not any(default['proxy'] in tup for tup in datastore.proxy_list):
                default['proxy'] = ''
        # proxy_override set to the json/text list of the items

        # Does it use some custom form? does one exist?
        processor_name = datastore.data['watching'][uuid].get('processor', '')
        processor_classes = next((tpl for tpl in processors.find_processors() if tpl[1] == processor_name), None)
        if not processor_classes:
            flash(gettext("Could not load '{}' processor, processor plugin might be missing. Please select a different processor.").format(processor_name), 'error')
            # Fall back to default processor so user can still edit and change processor
            processor_classes = next((tpl for tpl in processors.find_processors() if tpl[1] == 'text_json_diff'), None)
            if not processor_classes:
                # If even text_json_diff is missing, something is very wrong
                flash(gettext("Could not load '{}' processor, processor plugin might be missing.").format(processor_name), 'error')
                return redirect(url_for('watchlist.index'))

        parent_module = processors.get_parent_module(processor_classes[0])

        try:
            # Get the parent of the "processor.py" go up one, get the form (kinda spaghetti but its reusing existing code)
            forms_module = importlib.import_module(f"{parent_module.__name__}.forms")
            # Access the 'processor_settings_form' class from the 'forms' module
            form_class = getattr(forms_module, 'processor_settings_form')
        except ModuleNotFoundError as e:
            # .forms didnt exist
            form_class = forms.processor_text_json_diff_form
        except AttributeError as e:
            # .forms exists but no useful form
            form_class = forms.processor_text_json_diff_form

        form = form_class(formdata=request.form if request.method == 'POST' else None,
                          data=default,
                          extra_notification_tokens=default.extra_notification_token_values(),
                          default_system_settings=datastore.data['settings']
                          )

        # For the form widget tag UUID back to "string name" for the field
        form.tags.datastore = datastore

        # Used by some forms that need to dig deeper
        form.datastore = datastore
        form.watch = default

        # Load processor-specific config from JSON file for GET requests
        if request.method == 'GET' and processor_name:
            try:
                from changedetectionio.processors.base import difference_detection_processor
                # Create a processor instance to access config methods
                processor_instance = difference_detection_processor(datastore, uuid)
                # Use processor name as filename so each processor keeps its own config
                config_filename = f'{processor_name}.json'
                processor_config = processor_instance.get_extra_watch_config(config_filename)

                if processor_config:
                    # Populate processor-config-* fields from JSON
                    for config_key, config_value in processor_config.items():
                        field_name = f'processor_config_{config_key}'
                        if hasattr(form, field_name):
                            getattr(form, field_name).data = config_value
                            logger.debug(f"Loaded processor config from {config_filename}: {field_name} = {config_value}")
            except Exception as e:
                logger.warning(f"Failed to load processor config: {e}")

        for p in datastore.extra_browsers:
            form.fetch_backend.choices.append(p)

        form.fetch_backend.choices.append(("system", 'System settings default'))

        # form.browser_steps[0] can be assumed that we 'goto url' first

        if datastore.proxy_list is None:
            # @todo - Couldn't get setattr() etc dynamic addition working, so remove it instead
            del form.proxy
        else:
            form.proxy.choices = [('', 'Default')]
            for p in datastore.proxy_list:
                form.proxy.choices.append(tuple((p, datastore.proxy_list[p]['label'])))


        if request.method == 'POST' and form.validate():

            extra_update_obj = {
                'consecutive_filter_failures': 0,
                'last_error' : False
            }

            if request.args.get('unpause_on_save'):
                extra_update_obj['paused'] = False

            extra_update_obj['time_between_check'] = form.time_between_check.data

            # Handle processor-config-* fields separately (save to JSON, not datastore)
            # IMPORTANT: These must NOT be saved to url-watches.json, only to the processor-specific JSON file
            processor_config_data = processors.extract_processor_config_from_form_data(form.data)
            processors.save_processor_config(datastore, uuid, processor_config_data)

            # Ignore text
            form_ignore_text = form.ignore_text.data
            datastore.data['watching'][uuid]['ignore_text'] = form_ignore_text

            # Be sure proxy value is None
            if datastore.proxy_list is not None and form.data['proxy'] == '':
                extra_update_obj['proxy'] = None

            # Unsetting all filter_text methods should make it go back to default
            # This particularly affects tests running
            if 'filter_text_added' in form.data and not form.data.get('filter_text_added') \
                    and 'filter_text_replaced' in form.data and not form.data.get('filter_text_replaced') \
                    and 'filter_text_removed' in form.data and not form.data.get('filter_text_removed'):
                extra_update_obj['filter_text_added'] = True
                extra_update_obj['filter_text_replaced'] = True
                extra_update_obj['filter_text_removed'] = True

            # Because wtforms doesn't support accessing other data in process_ , but we convert the CSV list of tags back to a list of UUIDs
            tag_uuids = []
            if form.data.get('tags'):
                # Sometimes in testing this can be list, dont know why
                if type(form.data.get('tags')) == list:
                    extra_update_obj['tags'] = form.data.get('tags')
                else:
                    for t in form.data.get('tags').split(','):
                        tag_uuids.append(datastore.add_tag(title=t))
                    extra_update_obj['tags'] = tag_uuids

            datastore.data['watching'][uuid].update(form.data)
            datastore.data['watching'][uuid].update(extra_update_obj)

            if not datastore.data['watching'][uuid].get('tags'):
                # Force it to be a list, because form.data['tags'] will be string if nothing found
                # And del(form.data['tags'] ) wont work either for some reason
                datastore.data['watching'][uuid]['tags'] = []

            # Recast it if need be to right data Watch handler
            watch_class = processors.get_custom_watch_obj_for_processor(form.data.get('processor'))
            datastore.data['watching'][uuid] = watch_class(datastore_path=datastore.datastore_path, default=datastore.data['watching'][uuid])
            flash(gettext("Updated watch - unpaused!") if request.args.get('unpause_on_save') else gettext("Updated watch."))

            # Cleanup any browsersteps session for this watch
            try:
                from changedetectionio.blueprint.browser_steps import cleanup_session_for_watch
                cleanup_session_for_watch(uuid)
            except Exception as e:
                logger.debug(f"Error cleaning up browsersteps session: {e}")

            # Re #286 - We wait for syncing new data to disk in another thread every 60 seconds
            # But in the case something is added we should save straight away
            datastore.needs_write_urgent = True

            # Do not queue on edit if its not within the time range

            # @todo maybe it should never queue anyway on edit...
            is_in_schedule = True
            watch = datastore.data['watching'].get(uuid)

            if watch.get('time_between_check_use_default'):
                time_schedule_limit = datastore.data['settings']['requests'].get('time_schedule_limit', {})
            else:
                time_schedule_limit = watch.get('time_schedule_limit')

            tz_name = time_schedule_limit.get('timezone')
            if not tz_name:
                tz_name = datastore.data['settings']['application'].get('scheduler_timezone_default', os.getenv('TZ', 'UTC').strip())

            if time_schedule_limit and time_schedule_limit.get('enabled'):
                try:
                    is_in_schedule = is_within_schedule(time_schedule_limit=time_schedule_limit,
                                                      default_tz=tz_name
                                                      )
                except Exception as e:
                    logger.error(
                        f"{uuid} - Recheck scheduler, error handling timezone, check skipped - TZ name '{tz_name}' - {str(e)}")
                    return False

            #############################
            if not datastore.data['watching'][uuid].get('paused') and is_in_schedule:
                # Queue the watch for immediate recheck, with a higher priority
                worker_pool.queue_item_async_safe(update_q, queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': uuid}))

            # Diff page [edit] link should go back to diff page
            if request.args.get("next") and request.args.get("next") == 'diff':
                return redirect(url_for('ui.ui_diff.diff_history_page', uuid=uuid))

            return redirect(url_for('watchlist.index', tag=request.args.get("tag",'')))

        else:
            if request.method == 'POST' and not form.validate():
                flash(gettext("An error occurred, please see below."), "error")

            # JQ is difficult to install on windows and must be manually added (outside requirements.txt)
            jq_support = True
            try:
                import jq
            except ModuleNotFoundError:
                jq_support = False

            watch = datastore.data['watching'].get(uuid)

            from zoneinfo import available_timezones

            # Import the global plugin system
            from changedetectionio.pluggy_interface import collect_ui_edit_stats_extras, get_fetcher_capabilities

            # Get fetcher capabilities instead of hardcoded logic
            capabilities = get_fetcher_capabilities(watch, datastore)
            app_rss_token = datastore.data['settings']['application'].get('rss_access_token'),

            c = [f"processor-{watch.get('processor')}"]
            if worker_pool.is_watch_running(uuid):
                c.append('checking-now')

            template_args = {
                'available_processors': processors.available_processors(),
                'available_timezones': sorted(available_timezones()),
                'browser_steps_config': browser_step_ui_config,
                'emailprefix': os.getenv('NOTIFICATION_MAIL_BUTTON_PREFIX', False),
                'extra_classes': ' '.join(c),
                'extra_notification_token_placeholder_info': datastore.get_unique_notification_token_placeholders_available(),
                'extra_processor_config': form.extra_tab_content(),
                'extra_title': f" - Edit - {watch.label}",
                'form': form,
                'has_default_notification_urls': True if len(datastore.data['settings']['application']['notification_urls']) else False,
                'has_extra_headers_file': len(datastore.get_all_headers_in_textfile_for_watch(uuid=uuid)) > 0,
                'has_special_tag_options': _watch_has_tag_options_set(watch=watch),
                'jq_support': jq_support,
                'playwright_enabled': os.getenv('PLAYWRIGHT_DRIVER_URL', False),
                'app_rss_token': app_rss_token,
                'rss_uuid_feed' : {
                    'label': watch.label,
                    'url': url_for('rss.rss_single_watch', uuid=watch['uuid'], token=app_rss_token)
                },
                'settings_application': datastore.data['settings']['application'],
                'ui_edit_stats_extras': collect_ui_edit_stats_extras(watch),
                'visual_selector_data_ready': datastore.visualselector_data_is_ready(watch_uuid=uuid),
                'timezone_default_config': datastore.data['settings']['application'].get('scheduler_timezone_default'),
                'using_global_webdriver_wait': not default['webdriver_delay'],
                'uuid': uuid,
                'watch': watch,
                'capabilities': capabilities
            }

            included_content = None
            if form.extra_form_content():
                # So that the extra panels can access _helpers.html etc, we set the environment to load from templates/
                # And then render the code from the module
                templates_dir = str(importlib.resources.files("changedetectionio").joinpath('templates'))
                env = Environment(loader=FileSystemLoader(templates_dir))
                template = env.from_string(form.extra_form_content())
                included_content = template.render(**template_args)

            output = render_template("edit.html",
                                     extra_tab_content=form.extra_tab_content() if form.extra_tab_content() else None,
                                     extra_form_content=included_content,
                                     **template_args
                                     )

        return output

    @edit_blueprint.route("/edit/<string:uuid>/get-html", methods=['GET'])
    @login_optionally_required
    def watch_get_latest_html(uuid):
        from io import BytesIO
        from flask import send_file
        import brotli

        if uuid == 'first':
            uuid = list(datastore.data['watching'].keys()).pop()
        watch = datastore.data['watching'].get(uuid)
        if watch and watch.history.keys() and os.path.isdir(watch.watch_data_dir):
            latest_filename = list(watch.history.keys())[-1]
            html_fname = os.path.join(watch.watch_data_dir, f"{latest_filename}.html.br")
            with open(html_fname, 'rb') as f:
                if html_fname.endswith('.br'):
                    # Read and decompress the Brotli file
                    decompressed_data = brotli.decompress(f.read())
                else:
                    decompressed_data = f.read()

            buffer = BytesIO(decompressed_data)

            return send_file(buffer, as_attachment=True, download_name=f"{latest_filename}.html", mimetype='text/html')

        # Return a 500 error
        abort(500)

    # Ajax callback
    @edit_blueprint.route("/edit/<string:uuid>/preview-rendered", methods=['POST'])
    @login_optionally_required
    def watch_get_preview_rendered(uuid):
        '''For when viewing the "preview" of the rendered text from inside of Edit'''
        from flask import jsonify

        if uuid == 'first':
            uuid = list(datastore.data['watching'].keys()).pop()
        from changedetectionio.processors.text_json_diff import prepare_filter_prevew
        result = prepare_filter_prevew(watch_uuid=uuid, form_data=request.form, datastore=datastore)
        return jsonify(result)

    @edit_blueprint.route("/highlight_submit_ignore_url", methods=['POST'])
    @login_optionally_required
    def highlight_submit_ignore_url():
        import re
        mode = request.form.get('mode')
        selection = request.form.get('selection')

        uuid = request.args.get('uuid','')
        if datastore.data["watching"].get(uuid):
            if mode == 'exact':
                for l in selection.splitlines():
                    datastore.data["watching"][uuid]['ignore_text'].append(l.strip())
            elif mode == 'digit-regex':
                for l in selection.splitlines():
                    # Replace any series of numbers with a regex
                    s = re.escape(l.strip())
                    s = re.sub(r'[0-9]+', r'\\d+', s)
                    datastore.data["watching"][uuid]['ignore_text'].append('/' + s + '/')

        return f"<a href={url_for('ui.ui_preview.preview_page', uuid=uuid)}>Click to preview</a>"
    
    return edit_blueprint