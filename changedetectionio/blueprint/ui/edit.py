import time
from copy import deepcopy
import os
import importlib.resources
from flask import Blueprint, request, redirect, url_for, flash, render_template, make_response, send_from_directory, abort
from loguru import logger
from jinja2 import Environment, FileSystemLoader

from changedetectionio.store import ChangeDetectionStore
from changedetectionio.auth_decorator import login_optionally_required
from changedetectionio.time_handler import is_within_schedule

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

        # More for testing, possible to return the first/only
        if not datastore.data['watching'].keys():
            flash("No watches to edit", "error")
            return redirect(url_for('watchlist.index'))

        if uuid == 'first':
            uuid = list(datastore.data['watching'].keys()).pop()

        if not uuid in datastore.data['watching']:
            flash("No watch with the UUID %s found." % (uuid), "error")
            return redirect(url_for('watchlist.index'))

        switch_processor = request.args.get('switch_processor')
        if switch_processor:
            for p in processors.available_processors():
                if p[0] == switch_processor:
                    datastore.data['watching'][uuid]['processor'] = switch_processor
                    flash(f"Switched to mode - {p[1]}.")
                    datastore.clear_watch_history(uuid)
                    redirect(url_for('ui_edit.edit_page', uuid=uuid))

        # be sure we update with a copy instead of accidently editing the live object by reference
        default = deepcopy(datastore.data['watching'][uuid])

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
            flash(f"Cannot load the edit form for processor/plugin '{processor_classes[1]}', plugin missing?", 'error')
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

            # If they changed processor, it makes sense to reset it.
            if datastore.data['watching'][uuid].get('processor') != form.data.get('processor'):
                datastore.data['watching'][uuid].clear_watch()
                flash("Reset watch history due to change of processor")

            extra_update_obj = {
                'consecutive_filter_failures': 0,
                'last_error' : False
            }

            if request.args.get('unpause_on_save'):
                extra_update_obj['paused'] = False

            extra_update_obj['time_between_check'] = form.time_between_check.data

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
            flash("Updated watch - unpaused!" if request.args.get('unpause_on_save') else "Updated watch.")

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
                tz_name = datastore.data['settings']['application'].get('timezone', 'UTC')

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
                update_q.put(queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': uuid}))

            # Diff page [edit] link should go back to diff page
            if request.args.get("next") and request.args.get("next") == 'diff':
                return redirect(url_for('ui.ui_views.diff_history_page', uuid=uuid))

            return redirect(url_for('watchlist.index', tag=request.args.get("tag",'')))

        else:
            if request.method == 'POST' and not form.validate():
                flash("An error occurred, please see below.", "error")

            # JQ is difficult to install on windows and must be manually added (outside requirements.txt)
            jq_support = True
            try:
                import jq
            except ModuleNotFoundError:
                jq_support = False

            watch = datastore.data['watching'].get(uuid)

            # if system or watch is configured to need a chrome type browser
            system_uses_webdriver = datastore.data['settings']['application']['fetch_backend'] == 'html_webdriver'
            watch_needs_selenium_or_playwright = False
            if (watch.get('fetch_backend') == 'system' and system_uses_webdriver) or watch.get('fetch_backend') == 'html_webdriver' or watch.get('fetch_backend', '').startswith('extra_browser_'):
                watch_needs_selenium_or_playwright = True


            from zoneinfo import available_timezones

            # Only works reliably with Playwright

            template_args = {
                'available_processors': processors.available_processors(),
                'available_timezones': sorted(available_timezones()),
                'browser_steps_config': browser_step_ui_config,
                'emailprefix': os.getenv('NOTIFICATION_MAIL_BUTTON_PREFIX', False),
                'extra_notification_token_placeholder_info': datastore.get_unique_notification_token_placeholders_available(),
                'extra_processor_config': form.extra_tab_content(),
                'extra_title': f" - Edit - {watch.label}",
                'form': form,
                'has_default_notification_urls': True if len(datastore.data['settings']['application']['notification_urls']) else False,
                'has_extra_headers_file': len(datastore.get_all_headers_in_textfile_for_watch(uuid=uuid)) > 0,
                'has_special_tag_options': _watch_has_tag_options_set(watch=watch),
                'jq_support': jq_support,
                'playwright_enabled': os.getenv('PLAYWRIGHT_DRIVER_URL', False),
                'settings_application': datastore.data['settings']['application'],
                'system_has_playwright_configured': os.getenv('PLAYWRIGHT_DRIVER_URL'),
                'system_has_webdriver_configured': os.getenv('WEBDRIVER_URL'),
                'visual_selector_data_ready': datastore.visualselector_data_is_ready(watch_uuid=uuid),
                'timezone_default_config': datastore.data['settings']['application'].get('timezone'),
                'using_global_webdriver_wait': not default['webdriver_delay'],
                'uuid': uuid,
                'watch': watch,
                'watch_needs_selenium_or_playwright': watch_needs_selenium_or_playwright,
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

        return f"<a href={url_for('ui.ui_views.preview_page', uuid=uuid)}>Click to preview</a>"
    
    return edit_blueprint