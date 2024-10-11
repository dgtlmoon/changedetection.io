
from loguru import logger



def _task(watch, update_handler):
    from changedetectionio.content_fetchers.exceptions import ReplyWithContentButNoText
    from changedetectionio.processors.text_json_diff.processor import FilterNotFoundInResponse

    text_after_filter = ''

    try:
        # The slow process (we run 2 of these in parallel)
        changed_detected, update_obj, text_after_filter = update_handler.run_changedetection(watch=watch)
    except FilterNotFoundInResponse as e:
        text_after_filter = f"Filter not found in HTML: {str(e)}"
    except ReplyWithContentButNoText as e:
        text_after_filter = f"Filter found but no text (empty result)"
    except Exception as e:
        text_after_filter = f"Error: {str(e)}"

    if not text_after_filter.strip():
        text_after_filter = 'Empty content'

    # because run_changedetection always returns bytes due to saving the snapshots etc
    text_after_filter = text_after_filter.decode('utf-8') if isinstance(text_after_filter, bytes) else text_after_filter

    return text_after_filter


def prepare_filter_prevew(datastore, watch_uuid):
    '''Used by @app.route("/edit/<string:uuid>/preview-rendered", methods=['POST'])'''
    from changedetectionio import forms, html_tools
    from changedetectionio.model.Watch import model as watch_model
    from concurrent.futures import ProcessPoolExecutor
    from copy import deepcopy
    from flask import request, jsonify
    import brotli
    import importlib
    import os
    import time
    now = time.time()

    text_after_filter = ''
    text_before_filter = ''
    trigger_line_numbers = []
    ignore_line_numbers = []

    tmp_watch = deepcopy(datastore.data['watching'].get(watch_uuid))

    if tmp_watch and tmp_watch.history and os.path.isdir(tmp_watch.watch_data_dir):
        # Splice in the temporary stuff from the form
        form = forms.processor_text_json_diff_form(formdata=request.form if request.method == 'POST' else None,
                                                   data=request.form
                                                   )

        # Only update vars that came in via the AJAX post
        p = {k: v for k, v in form.data.items() if k in request.form.keys()}
        tmp_watch.update(p)
        blank_watch_no_filters = watch_model()
        blank_watch_no_filters['url'] = tmp_watch.get('url')

        latest_filename = next(reversed(tmp_watch.history))
        html_fname = os.path.join(tmp_watch.watch_data_dir, f"{latest_filename}.html.br")
        with open(html_fname, 'rb') as f:
            decompressed_data = brotli.decompress(f.read()).decode('utf-8') if html_fname.endswith('.br') else f.read().decode('utf-8')

            # Just like a normal change detection except provide a fake "watch" object and dont call .call_browser()
            processor_module = importlib.import_module("changedetectionio.processors.text_json_diff.processor")
            update_handler = processor_module.perform_site_check(datastore=datastore,
                                                                 watch_uuid=tmp_watch.get('uuid')  # probably not needed anymore anyway?
                                                                 )
            # Use the last loaded HTML as the input
            update_handler.datastore = datastore
            update_handler.fetcher.content = str(decompressed_data) # str() because playwright/puppeteer/requests return string
            update_handler.fetcher.headers['content-type'] = tmp_watch.get('content-type')

            # Process our watch with filters and the HTML from disk, and also a blank watch with no filters but also with the same HTML from disk
            # Do this as a parallel process because it could take some time
            with ProcessPoolExecutor(max_workers=2) as executor:
                future1 = executor.submit(_task, tmp_watch, update_handler)
                future2 = executor.submit(_task, blank_watch_no_filters, update_handler)

                text_after_filter = future1.result()
                text_before_filter = future2.result()

    try:
        trigger_line_numbers = html_tools.strip_ignore_text(content=text_after_filter,
                                                            wordlist=tmp_watch['trigger_text'],
                                                            mode='line numbers'
                                                            )
    except Exception as e:
        text_before_filter = f"Error: {str(e)}"

    try:
        text_to_ignore = tmp_watch.get('ignore_text', []) + datastore.data['settings']['application'].get('global_ignore_text', [])
        ignore_line_numbers = html_tools.strip_ignore_text(content=text_after_filter,
                                                           wordlist=text_to_ignore,
                                                           mode='line numbers'
                                                           )
    except Exception as e:
        text_before_filter = f"Error: {str(e)}"

    logger.trace(f"Parsed in {time.time() - now:.3f}s")

    return jsonify(
        {
            'after_filter': text_after_filter,
            'before_filter': text_before_filter.decode('utf-8') if isinstance(text_before_filter, bytes) else text_before_filter,
            'duration': time.time() - now,
            'trigger_line_numbers': trigger_line_numbers,
            'ignore_line_numbers': ignore_line_numbers,
        }
    )

