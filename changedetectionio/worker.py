from blinker import signal
from .processors.exceptions import ProcessorException
import changedetectionio.content_fetchers.exceptions as content_fetchers_exceptions
from changedetectionio.processors.text_json_diff.processor import FilterNotFoundInResponse
from changedetectionio import html_tools
from changedetectionio import worker_pool
from changedetectionio.queuedWatchMetaData import PrioritizedItem
from changedetectionio.pluggy_interface import apply_update_handler_alter, apply_update_finalize

import asyncio
import os
import re
import sys
import time

# Allow alphanumerics, space, and a small set of punctuation that appears in legitimate
# status strings ("Querying AI/LLM (intent)..", "Fetching page.."). Anything that could
# be HTML-active (<, >, &, ", ', =, ;, {, }, `, \) is stripped.
_MINITEXT_STATUS_SAFE_RE = re.compile(r'[^A-Za-z0-9 ().,/:\-]')
_MINITEXT_STATUS_MAX_LEN = 80

from loguru import logger

# Async version of update_worker
# Processes jobs from AsyncSignalPriorityQueue instead of threaded queue

IN_PYTEST = "pytest" in sys.modules or "PYTEST_CURRENT_TEST" in os.environ
DEFER_SLEEP_TIME_ALREADY_QUEUED = 0.3 if IN_PYTEST else 10.0


def set_watch_minitext_status(watch, status):
    """
    Set a transient status line for a watch (e.g. "Fetching page..", "Querying AI/LLM..").

    Writes to watch['__check_status'] so a client reloading the page can render the
    last known status, and fires the realtime signal so already-connected clients
    update live. __-prefixed key is filtered from disk by Watch._get_commit_data().

    Status is sanitized to alphanumerics, space, and safe punctuation only.
    """
    safe_status = _MINITEXT_STATUS_SAFE_RE.sub('', str(status))[:_MINITEXT_STATUS_MAX_LEN]
    watch['__check_status'] = safe_status
    signal('watch_small_status_comment').send(watch_uuid=watch['uuid'], status=safe_status)


async def async_update_worker(worker_id, q, notification_q, app, datastore, executor=None):
    """
    Async worker function that processes watch check jobs from the queue.

    Args:
        worker_id: Unique identifier for this worker
        q: AsyncSignalPriorityQueue containing jobs to process
        notification_q: Standard queue for notifications
        app: Flask application instance
        datastore: Application datastore
        executor: ThreadPoolExecutor for queue operations (optional)

    Returns:
        "restart" if worker should restart, "shutdown" for clean exit
    """
    # Set a descriptive name for this task
    task = asyncio.current_task()
    if task:
        task.set_name(f"async-worker-{worker_id}")

    # Read restart policy from environment
    max_jobs = int(os.getenv("WORKER_MAX_JOBS", "10"))
    max_runtime_seconds = int(os.getenv("WORKER_MAX_RUNTIME", "3600"))  # 1 hour default

    jobs_processed = 0
    start_time = time.time()

    # Log thread name for debugging
    import threading
    thread_name = threading.current_thread().name
    logger.info(f"Starting async worker {worker_id} on thread '{thread_name}' (max_jobs={max_jobs}, max_runtime={max_runtime_seconds}s)")

    while not app.config.exit.is_set():
        update_handler = None
        watch = None
        processing_exception = None  # Reset at start of each iteration to prevent state bleeding

        try:
            # Efficient blocking via run_in_executor (no polling overhead!)
            # Worker blocks in threading.Queue.get() which uses Condition.wait()
            # Executor must be sized to match worker count (see worker_pool.py: 50 threads default)
            # Single timeout (no double-timeout wrapper) = no race condition
            queued_item_data = await q.async_get(executor=executor, timeout=1.0)

            # CRITICAL: Claim UUID immediately after getting from queue to prevent race condition
            # in wait_for_all_checks() which checks qsize() and running_uuids separately
            uuid = queued_item_data.item.get('uuid')
            if not worker_pool.claim_uuid_for_processing(uuid, worker_id):
                # Already being processed - re-queue and continue
                logger.trace(f"Worker {worker_id} detected UUID {uuid} already processing during claim - deferring")
                await asyncio.sleep(DEFER_SLEEP_TIME_ALREADY_QUEUED)
                deferred_priority = max(1000, queued_item_data.priority * 10)
                deferred_item = PrioritizedItem(priority=deferred_priority, item=queued_item_data.item)
                worker_pool.queue_item_async_safe(q, deferred_item, silent=True)
                continue

        except asyncio.TimeoutError:
            # No jobs available - check if we should restart based on time while idle
            runtime = time.time() - start_time
            if runtime >= max_runtime_seconds:
                logger.info(f"Worker {worker_id} idle and reached max runtime ({runtime:.0f}s), restarting")
                return "restart"
            continue
        except RuntimeError as e:
            # Handle executor shutdown gracefully - this is expected during shutdown
            if "cannot schedule new futures after shutdown" in str(e):
                # Executor shut down - exit gracefully without logging in pytest
                if not IN_PYTEST:
                    logger.debug(f"Worker {worker_id} detected executor shutdown, exiting")
                break
            # Other RuntimeError - log and continue
            logger.error(f"Worker {worker_id} runtime error: {e}")
            await asyncio.sleep(0.1)
            continue
        except Exception as e:
            # Handle expected Empty exception from queue timeout
            import queue
            if isinstance(e, queue.Empty):
                # Queue is empty, normal behavior - just continue
                continue

            # Unexpected exception - log as critical
            logger.critical(f"CRITICAL: Worker {worker_id} failed to get queue item: {type(e).__name__}: {e}")

            # Log queue health for debugging
            try:
                queue_size = q.qsize()
                is_empty = q.empty()
                logger.critical(f"CRITICAL: Worker {worker_id} queue health - size: {queue_size}, empty: {is_empty}")
            except Exception as health_e:
                logger.critical(f"CRITICAL: Worker {worker_id} queue health check failed: {health_e}")

            await asyncio.sleep(0.1)
            continue

        # UUID already claimed above immediately after getting from queue
        # to prevent race condition with wait_for_all_checks()

        fetch_start_time = round(time.time())

        try:
            if uuid in list(datastore.data['watching'].keys()) and datastore.data['watching'][uuid].get('url'):
                changed_detected = False
                contents = b''
                process_changedetection_results = True
                update_obj = {}

                # Clear last errors
                datastore.data['watching'][uuid]['browser_steps_last_error_step'] = None
                datastore.data['watching'][uuid]['last_checked'] = fetch_start_time

                watch = datastore.data['watching'].get(uuid)

                logger.info(f"Worker {worker_id} processing watch UUID {uuid} Priority {queued_item_data.priority} URL {watch['url']}")

                try:
                    # Retrieve signal by name to ensure thread-safe access across worker threads
                    watch_check_update = signal('watch_check_update')
                    watch_check_update.send(watch_uuid=uuid)

                    # Processor is what we are using for detecting the "Change"
                    processor = watch.get('processor', 'text_json_diff')

                    # Init a new 'difference_detection_processor'
                    # Use get_processor_module() to support both built-in and plugin processors
                    from changedetectionio.processors import get_processor_module
                    processor_module = get_processor_module(processor)

                    if not processor_module:
                        error_msg = f"Processor module '{processor}' not found."
                        logger.error(error_msg)
                        raise ModuleNotFoundError(error_msg)

                    update_handler = processor_module.perform_site_check(datastore=datastore,
                                                                         watch_uuid=uuid)

                    # Allow plugins to modify/wrap the update_handler
                    update_handler = apply_update_handler_alter(update_handler, watch, datastore)

                    set_watch_minitext_status(watch, "Fetching page..")

                    # All fetchers are now async, so call directly
                    await update_handler.call_browser()

                    # Run change detection in executor to avoid blocking event loop
                    # This includes CPU-intensive operations like HTML parsing (lxml/inscriptis)
                    # which can take 2-10ms and cause GIL contention across workers
                    loop = asyncio.get_event_loop()
                    changed_detected, update_obj, contents = await loop.run_in_executor(
                        executor,
                        lambda: update_handler.run_changedetection(watch=watch)
                    )

                except PermissionError as e:
                    logger.critical(f"File permission error updating file, watch: {uuid}")
                    logger.critical(str(e))
                    process_changedetection_results = False

                except ProcessorException as e:
                    if e.screenshot:
                        watch.save_screenshot(screenshot=e.screenshot)
                        e.screenshot = None  # Free memory immediately
                    if e.xpath_data:
                        watch.save_xpath_data(data=e.xpath_data)
                        e.xpath_data = None  # Free memory immediately
                    datastore.update_watch(uuid=uuid, update_obj={'last_error': e.message})
                    process_changedetection_results = False

                except content_fetchers_exceptions.ReplyWithContentButNoText as e:
                    extra_help = ""
                    if e.has_filters:
                        has_img = html_tools.include_filters(include_filters='img',
                                                             html_content=e.html_content)
                        if has_img:
                            extra_help = ", it's possible that the filters you have give an empty result or contain only an image."
                        else:
                            extra_help = ", it's possible that the filters were found, but contained no usable text."

                    datastore.update_watch(uuid=uuid, update_obj={
                        'last_error': f"Got HTML content but no text found (With {e.status_code} reply code){extra_help}"
                    })

                    if e.screenshot:
                        watch.save_screenshot(screenshot=e.screenshot, as_error=True)
                        e.screenshot = None  # Free memory immediately

                    if e.xpath_data:
                        watch.save_xpath_data(data=e.xpath_data)
                        e.xpath_data = None  # Free memory immediately
                        
                    process_changedetection_results = False

                except content_fetchers_exceptions.Non200ErrorCodeReceived as e:
                    if e.status_code == 403:
                        err_text = "Error - 403 (Access denied) received"
                    elif e.status_code == 404:
                        err_text = "Error - 404 (Page not found) received"
                    elif e.status_code == 407:
                        err_text = "Error - 407 (Proxy authentication required) received, did you need a username and password for the proxy?"
                    elif e.status_code == 500:
                        err_text = "Error - 500 (Internal server error) received from the web site"
                    else:
                        extra = ' (Access denied or blocked)' if str(e.status_code).startswith('4') else ''
                        err_text = f"Error - Request returned a HTTP error code {e.status_code}{extra}"

                    if e.screenshot:
                        watch.save_screenshot(screenshot=e.screenshot, as_error=True)
                        e.screenshot = None  # Free memory immediately
                    if e.xpath_data:
                        watch.save_xpath_data(data=e.xpath_data, as_error=True)
                        e.xpath_data = None  # Free memory immediately
                    if e.page_text:
                        watch.save_error_text(contents=e.page_text)

                    datastore.update_watch(uuid=uuid, update_obj={'last_error': err_text})
                    process_changedetection_results = False

                except FilterNotFoundInResponse as e:
                    if not datastore.data['watching'].get(uuid):
                        continue
                    logger.debug(f"Received FilterNotFoundInResponse exception for {uuid}")

                    err_text = "Warning, no filters were found, no change detection ran - Did the page change layout? update your Visual Filter if necessary."
                    datastore.update_watch(uuid=uuid, update_obj={'last_error': err_text})

                    # Filter wasnt found, but we should still update the visual selector so that they can have a chance to set it up again
                    if e.screenshot:
                        watch.save_screenshot(screenshot=e.screenshot)
                        e.screenshot = None  # Free memory immediately

                    if e.xpath_data:
                        watch.save_xpath_data(data=e.xpath_data)
                        e.xpath_data = None  # Free memory immediately

                    # Only when enabled, send the notification
                    if watch.get('filter_failure_notification_send', False):
                        c = watch.get('consecutive_filter_failures', 0)
                        c += 1
                        # Send notification if we reached the threshold?
                        threshold = datastore.data['settings']['application'].get('filter_failure_notification_threshold_attempts', 0)
                        logger.debug(f"FilterNotFoundInResponse - Filter for {uuid} not found, consecutive_filter_failures: {c} of threshold {threshold}")
                        if c >= threshold:
                            if not watch.get('notification_muted'):
                                logger.debug(f"FilterNotFoundInResponse - Sending filter failed notification for {uuid}")
                                await send_filter_failure_notification(uuid, notification_q, datastore)
                            c = 0
                            logger.debug(f"FilterNotFoundInResponse - Reset filter failure count back to zero")
                        else:
                            logger.debug(f"FilterNotFoundInResponse - {c} of threshold {threshold}..")

                        datastore.update_watch(uuid=uuid, update_obj={'consecutive_filter_failures': c})
                    else:
                        logger.trace(f"FilterNotFoundInResponse - {uuid} - filter_failure_notification_send not enabled, skipping")

                    process_changedetection_results = False

                except content_fetchers_exceptions.checksumFromPreviousCheckWasTheSame as e:
                    # Yes fine, so nothing todo, don't continue to process.
                    process_changedetection_results = False
                    changed_detected = False
                    logger.debug(f'[{uuid}] - checksumFromPreviousCheckWasTheSame - Checksum from previous check was the same, nothing todo here.')
                    # Reset the edited flag since we successfully completed the check
                    watch.reset_watch_edited_flag()
                    # Page was fetched successfully - clear any previous error state
                    datastore.update_watch(uuid=uuid, update_obj={'last_error': False})
                    cleanup_error_artifacts(uuid, datastore)
                    
                except content_fetchers_exceptions.BrowserConnectError as e:
                    datastore.update_watch(uuid=uuid,
                                         update_obj={'last_error': e.msg})
                    process_changedetection_results = False
                    
                except content_fetchers_exceptions.BrowserFetchTimedOut as e:
                    datastore.update_watch(uuid=uuid,
                                         update_obj={'last_error': e.msg})
                    process_changedetection_results = False
                    
                except content_fetchers_exceptions.BrowserStepsStepException as e:
                    if not datastore.data['watching'].get(uuid):
                        continue

                    error_step = e.step_n + 1
                    from playwright._impl._errors import TimeoutError, Error

                    # Generally enough info for TimeoutError (couldnt locate the element after default seconds)
                    err_text = f"Browser step at position {error_step} could not run, check the watch, add a delay if necessary, view Browser Steps to see screenshot at that step."

                    if e.original_e.name == "TimeoutError":
                        # Just the first line is enough, the rest is the stack trace
                        err_text += " Could not find the target."
                    else:
                        # Other Error, more info is good.
                        err_text += " " + str(e.original_e).splitlines()[0]

                    logger.debug(f"BrowserSteps exception at step {error_step} {str(e.original_e)}")

                    datastore.update_watch(uuid=uuid,
                                         update_obj={'last_error': err_text,
                                                   'browser_steps_last_error_step': error_step})

                    if watch.get('filter_failure_notification_send', False):
                        c = watch.get('consecutive_filter_failures', 0)
                        c += 1
                        # Send notification if we reached the threshold?
                        threshold = datastore.data['settings']['application'].get('filter_failure_notification_threshold_attempts', 0)
                        logger.error(f"Step for {uuid} not found, consecutive_filter_failures: {c}")
                        if threshold > 0 and c >= threshold:
                            if not watch.get('notification_muted'):
                                await send_step_failure_notification(watch_uuid=uuid, step_n=e.step_n, notification_q=notification_q, datastore=datastore)
                            c = 0

                        datastore.update_watch(uuid=uuid, update_obj={'consecutive_filter_failures': c})

                    process_changedetection_results = False

                except content_fetchers_exceptions.EmptyReply as e:
                    # Some kind of custom to-str handler in the exception handler that does this?
                    err_text = "EmptyReply - try increasing 'Wait seconds before extracting text', Status Code {}".format(e.status_code)
                    datastore.update_watch(uuid=uuid, update_obj={'last_error': err_text,
                                                                'last_check_status': e.status_code})
                    process_changedetection_results = False
                    
                except content_fetchers_exceptions.ScreenshotUnavailable as e:
                    err_text = "Screenshot unavailable, page did not render fully in the expected time or page was too long - try increasing 'Wait seconds before extracting text'"
                    datastore.update_watch(uuid=uuid, update_obj={'last_error': err_text,
                                                                'last_check_status': e.status_code})
                    process_changedetection_results = False
                    
                except content_fetchers_exceptions.JSActionExceptions as e:
                    err_text = "Error running JS Actions - Page request - "+e.message
                    if e.screenshot:
                        watch.save_screenshot(screenshot=e.screenshot, as_error=True)
                        e.screenshot = None  # Free memory immediately
                    datastore.update_watch(uuid=uuid, update_obj={'last_error': err_text,
                                                                'last_check_status': e.status_code})
                    process_changedetection_results = False
                    
                except content_fetchers_exceptions.PageUnloadable as e:
                    err_text = "Page request from server didnt respond correctly"
                    if e.message:
                        err_text = "{} - {}".format(err_text, e.message)

                    if e.screenshot:
                        watch.save_screenshot(screenshot=e.screenshot, as_error=True)
                        e.screenshot = None  # Free memory immediately

                    datastore.update_watch(uuid=uuid, update_obj={'last_error': err_text,
                                                                'last_check_status': e.status_code,
                                                                'has_ldjson_price_data': None})
                    process_changedetection_results = False
                    
                except content_fetchers_exceptions.BrowserStepsInUnsupportedFetcher as e:
                    err_text = "This watch has Browser Steps configured and so it cannot run with the 'Basic fast Plaintext/HTTP Client', either remove the Browser Steps or select a Chrome fetcher."
                    datastore.update_watch(uuid=uuid, update_obj={'last_error': err_text})
                    process_changedetection_results = False
                    logger.error(f"Exception (BrowserStepsInUnsupportedFetcher) reached processing watch UUID: {uuid}")

                except Exception as e:
                    import traceback
                    logger.error(f"Worker {worker_id} exception processing watch UUID: {uuid}")
                    logger.exception(f"Worker {worker_id} full exception details:")
                    datastore.update_watch(uuid=uuid, update_obj={'last_error': "Exception: " + str(e)})
                    process_changedetection_results = False

                else:
                    if not datastore.data['watching'].get(uuid):
                        continue

                    update_obj['content-type'] = str(update_handler.fetcher.get_all_headers().get('content-type', '') or "").lower()

                    if not watch.get('ignore_status_codes'):
                        update_obj['consecutive_filter_failures'] = 0

                    update_obj['last_error'] = False
                    cleanup_error_artifacts(uuid, datastore)

                if not datastore.data['watching'].get(uuid):
                    continue

                logger.debug(f"Processing watch UUID: {uuid} - xpath_data length returned {len(update_handler.xpath_data) if update_handler and update_handler.xpath_data else 'empty.'}")
                if update_handler and process_changedetection_results:
                    try:
                        # Reset the edited flag BEFORE update_watch (which calls watch.update() and would set it again)
                        watch.reset_watch_edited_flag()

                        # LLM evaluation — intent filtering + change summary
                        update_obj['_llm_result'] = None
                        update_obj['_llm_intent'] = ''
                        update_obj['_llm_change_summary'] = ''
                        # skip_check: when budget exceeded, don't run LLM or the check
                        _llm_budget_action = datastore.data['settings']['application'].get('llm_budget_action', 'skip_llm')
                        if _llm_budget_action == 'skip_check':
                            from changedetectionio.llm.evaluator import is_global_token_budget_exceeded
                            if is_global_token_budget_exceeded(datastore):
                                logger.info(f"LLM monthly budget exceeded — skipping check for {uuid} (budget_action=skip_check)")
                                changed_detected = False

                        if changed_detected:
                            try:
                                from changedetectionio.llm.evaluator import (
                                    evaluate_change, resolve_intent, resolve_llm_field,
                                    summarise_change, get_llm_config,
                                )
                                _llm_cfg = get_llm_config(datastore)
                                if _llm_cfg:
                                    # Compute unified diff once — used by both intent and summary
                                    _watch_dates = list(watch.history.keys())
                                    # Capture from_version before new snapshot is added
                                    _llm_from_version = _watch_dates[-1] if _watch_dates else None
                                    if _watch_dates:
                                        _prev_text = watch.get_history_snapshot(timestamp=_watch_dates[-1]) or ''
                                        from difflib import unified_diff as _unified_diff
                                        _diff_lines = list(_unified_diff(
                                            _prev_text.splitlines(keepends=True),
                                            contents.splitlines(keepends=True),
                                            lineterm='',
                                            n=3
                                        ))
                                        _diff_text = ''.join(_diff_lines) if _diff_lines else contents
                                    else:
                                        _diff_text = contents

                                    # Step 1: AI Change Intent — may suppress notification
                                    _llm_intent, _llm_intent_source = resolve_intent(watch, datastore)
                                    if _llm_intent:
                                        set_watch_minitext_status(watch, "AI/LLM (rules)..")
                                        _llm_result = await loop.run_in_executor(
                                            executor,
                                            lambda diff=_diff_text, snap=contents: evaluate_change(
                                                watch, datastore, diff=diff, current_snapshot=snap
                                            )
                                        )
                                        update_obj['_llm_result'] = _llm_result
                                        update_obj['_llm_intent'] = _llm_intent

                                        if _llm_result and not _llm_result.get('important', True):
                                            changed_detected = False
                                            logger.info(
                                                f"LLM filtered out change for {uuid} "
                                                f"(intent from {_llm_intent_source}): "
                                                f"{_llm_result.get('summary', '')[:80]}"
                                            )

                                    # Step 2: AI Change Summary — runs for any LLM-configured watch with a change
                                    if changed_detected:
                                        set_watch_minitext_status(watch, "AI/LLM (summary)..")
                                        _change_summary = await loop.run_in_executor(
                                            executor,
                                            lambda diff=_diff_text, snap=contents: summarise_change(
                                                watch, datastore, diff=diff, current_snapshot=snap
                                            )
                                        )
                                        if _change_summary:
                                            update_obj['_llm_change_summary'] = _change_summary
                            except Exception as e:
                                logger.warning(f"LLM evaluation error for {uuid}: {e}")

                        datastore.update_watch(uuid=uuid, update_obj=update_obj)

                        if changed_detected or not watch.history_n:
                            if update_handler.screenshot:
                                watch.save_screenshot(screenshot=update_handler.screenshot)
                                # Free screenshot memory immediately after saving
                                update_handler.screenshot = None
                                if hasattr(update_handler, 'fetcher') and hasattr(update_handler.fetcher, 'screenshot'):
                                    update_handler.fetcher.screenshot = None

                            if update_handler.xpath_data:
                                watch.save_xpath_data(data=update_handler.xpath_data)
                                # Free xpath data memory
                                update_handler.xpath_data = None
                                if hasattr(update_handler, 'fetcher') and hasattr(update_handler.fetcher, 'xpath_data'):
                                    update_handler.fetcher.xpath_data = None

                            # Ensure unique timestamp for history
                            if watch.newest_history_key and int(fetch_start_time) == int(watch.newest_history_key):
                                logger.warning(f"Timestamp {fetch_start_time} already exists, waiting 1 seconds")
                                fetch_start_time += 1
                                await asyncio.sleep(1)

                            watch.save_history_blob(contents=contents,
                                                    timestamp=int(fetch_start_time),
                                                    snapshot_id=update_obj.get('previous_md5', 'none'))

                            # Save AI summary file now that the new snapshot is committed —
                            # watch.history.keys()[-1] now reflects the just-saved version,
                            # so the cache filename matches what the UI will later look up.
                            # Cache key must use build_summary_cache_prompt() with UI defaults so
                            # the worker write and the UI read hash to the same prompt_hash.
                            if update_obj.get('_llm_change_summary') and _llm_from_version:
                                try:
                                    from changedetectionio.llm.evaluator import (
                                        get_effective_summary_prompt, build_summary_cache_prompt,
                                    )
                                    _llm_to_version = list(watch.history.keys())[-1]
                                    _llm_max_summary_tokens = datastore.data['settings']['application'].get('llm_max_summary_tokens', 3000)
                                    _llm_model = (datastore.data['settings']['application'].get('llm') or {}).get('model', '')
                                    _llm_cache_prompt = build_summary_cache_prompt(
                                        effective_prompt=get_effective_summary_prompt(watch, datastore),
                                        max_summary_tokens=_llm_max_summary_tokens,
                                        model=_llm_model,
                                    )
                                    watch.save_llm_diff_summary(
                                        update_obj['_llm_change_summary'],
                                        _llm_from_version,
                                        _llm_to_version,
                                        prompt=_llm_cache_prompt,
                                    )
                                except Exception as _fe:
                                    logger.warning(f"Could not write change-summary file for {uuid}: {_fe}")

                            empty_pages_are_a_change = datastore.data['settings']['application'].get('empty_pages_are_a_change', False)
                            if update_handler.fetcher.content or (not update_handler.fetcher.content and empty_pages_are_a_change):
                                watch.save_last_fetched_html(contents=update_handler.fetcher.content, timestamp=int(fetch_start_time))

                            # Explicitly delete large content variables to free memory IMMEDIATELY after saving
                            # These are no longer needed after being saved to history
                            del contents

                            # Send notifications on second+ check
                            if watch.history_n >= 2:
                                logger.info(f"Change detected in UUID {uuid} - {watch['url']}")
                                if not watch.get('notification_muted'):
                                    await send_content_changed_notification(uuid, notification_q, datastore)

                    except Exception as e:

                        logger.critical(f"Worker {worker_id} exception in process_changedetection_results")
                        logger.exception(f"Worker {worker_id} full exception details:")
                        datastore.update_watch(uuid=uuid, update_obj={'last_error': str(e)})


                # Always record attempt count
                count = watch.get('check_count', 0) + 1

                final_updates = {'fetch_time': round(time.time() - fetch_start_time, 3),
                                                                  'check_count': count,
                                                                  }
                # Record server header
                try:
                    server_header = str(update_handler.fetcher.get_all_headers().get('server', '') or "").strip().lower()[:255]
                    if server_header:
                        final_updates['remote_server_reply'] = server_header
                except Exception as e:
                    server_header = None
                    pass

                if update_handler: # Could be none or empty if the processor was not found
                    # Always record page title (used in notifications, and can change even when the content is the same)
                    if update_obj.get('content-type') and 'html' in update_obj.get('content-type'):
                        try:
                            page_title = html_tools.extract_title(data=update_handler.fetcher.content)
                            if page_title:
                                page_title = page_title.strip()[:2000]
                                logger.debug(f"UUID: {uuid} Page <title> is '{page_title}'")
                                final_updates['page_title'] = page_title
                        except Exception as e:
                            logger.exception(f"Worker {worker_id} full exception details:")
                            logger.warning(f"UUID: {uuid} Exception when extracting <title> - {str(e)}")

                    # Store favicon if necessary
                    if update_handler.fetcher.favicon_blob and update_handler.fetcher.favicon_blob.get('base64'):
                        watch.bump_favicon(url=update_handler.fetcher.favicon_blob.get('url'),
                                           favicon_base_64=update_handler.fetcher.favicon_blob.get('base64'),
                                           mime_type=update_handler.fetcher.favicon_blob.get('mime_type')
                                           )

                    datastore.update_watch(uuid=uuid, update_obj=final_updates)

                    # NOW clear fetcher content - after all processing is complete
                    # This is the last point where we need the fetcher data
                    if update_handler and hasattr(update_handler, 'fetcher') and update_handler.fetcher:
                        update_handler.fetcher.clear_content()

                    # Explicitly delete update_handler to free all references
                    if update_handler:
                        del update_handler
                        update_handler = None

                # Force garbage collection
                import gc
                gc.collect()

        except Exception as e:
            # Store the processing exception for plugin finalization hook
            processing_exception = e

            logger.error(f"Worker {worker_id} unexpected error processing {uuid}: {e}")
            logger.exception(f"Worker {worker_id} full exception details:")

            # Also update the watch with error information
            if datastore and uuid in datastore.data['watching']:
                datastore.update_watch(uuid=uuid, update_obj={'last_error': f"Worker error: {str(e)}"})
        
        finally:
            # Always cleanup - this runs whether there was an exception or not
            if uuid:
                # Capture references for plugin finalize hook BEFORE cleanup
                # (cleanup may delete these variables, but plugins need the original references)
                finalize_handler = update_handler  # Capture now, before cleanup deletes it
                finalize_watch = watch              # Capture now, before any modifications

                # Call quit() as backup (Puppeteer/Playwright have internal cleanup, but this acts as safety net)
                try:
                    if update_handler and hasattr(update_handler, 'fetcher') and update_handler.fetcher:
                        await update_handler.fetcher.quit(watch=watch)
                except Exception as e:
                    logger.error(f"Exception while cleaning/quit after calling browser: {e}")
                    logger.exception(f"Worker {worker_id} full exception details:")

                try:

                    # Clean up all memory references BEFORE garbage collection
                    if update_handler:
                        if hasattr(update_handler, 'fetcher') and update_handler.fetcher:
                            update_handler.fetcher.clear_content()
                        if hasattr(update_handler, 'content_processor'):
                            update_handler.content_processor = None
                        del update_handler
                        update_handler = None

                    # Clear large content variables
                    if 'contents' in locals():
                        del contents

                    # Force garbage collection after all references are cleared
                    import gc
                    gc.collect()

                    logger.debug(f"Worker {worker_id} completed watch {uuid} in {time.time()-fetch_start_time:.2f}s")
                except Exception as cleanup_error:
                    logger.error(f"Worker {worker_id} error during cleanup: {cleanup_error}")
                    logger.exception(f"Worker {worker_id} full exception details:")

                # Call plugin finalization hook after all cleanup is done
                # Use captured references from before cleanup
                try:
                    apply_update_finalize(
                        update_handler=finalize_handler,
                        watch=finalize_watch,
                        datastore=datastore,
                        processing_exception=processing_exception
                    )
                except Exception as finalize_error:
                    logger.error(f"Worker {worker_id} error in finalize hook: {finalize_error}")
                    logger.exception(f"Worker {worker_id} full exception details:")
                finally:
                    # Clean up captured references to allow immediate garbage collection
                    del finalize_handler
                    del finalize_watch

                # Release UUID from processing AFTER all cleanup and hooks complete (thread-safe)
                # This ensures wait_for_all_checks() waits for finalize hooks to complete
                try:
                    worker_pool.release_uuid_from_processing(uuid, worker_id=worker_id)
                except Exception as release_error:
                    logger.error(f"Worker {worker_id} error releasing UUID: {release_error}")
                    logger.exception(f"Worker {worker_id} full exception details:")
                finally:
                    # Send completion signal - retrieve by name to ensure thread-safe access
                    if watch:
                        # Clear transient in-memory status — check is done
                        watch.pop('__check_status', None)
                        watch_check_update = signal('watch_check_update')
                        watch_check_update.send(watch_uuid=watch['uuid'])

            del (uuid)

            # Brief pause before continuing to avoid tight error loops (only on error)
            if 'e' in locals():
                await asyncio.sleep(1.0)
            else:
                # Small yield for normal completion
                await asyncio.sleep(0.01)

            # Job completed - increment counter and check restart conditions
            jobs_processed += 1
            runtime = time.time() - start_time

            # Check if we should restart (only when idle, between jobs)
            should_restart_jobs = jobs_processed >= max_jobs
            should_restart_time = runtime >= max_runtime_seconds

            if should_restart_jobs or should_restart_time:
                reason = f"{jobs_processed} jobs" if should_restart_jobs else f"{runtime:.0f}s runtime"
                logger.info(f"Worker {worker_id} restarting after {reason} ({jobs_processed} jobs, {runtime:.0f}s runtime)")
                return "restart"

        # Check if we should exit
        if app.config.exit.is_set():
            break

    # Check if we're in pytest environment - if so, be more gentle with logging
    import sys
    in_pytest = "pytest" in sys.modules or "PYTEST_CURRENT_TEST" in os.environ

    if not in_pytest:
        logger.info(f"Worker {worker_id} shutting down")

    return "shutdown"


def cleanup_error_artifacts(uuid, datastore):
    """Helper function to clean up error artifacts"""
    cleanup_files = ["last-error-screenshot.png", "last-error.txt"]
    for f in cleanup_files:
        full_path = os.path.join(datastore.datastore_path, uuid, f)
        if os.path.isfile(full_path):
            os.unlink(full_path)



async def send_content_changed_notification(watch_uuid, notification_q, datastore):
    """Helper function to queue notifications using the new notification service"""
    try:
        from changedetectionio.notification_service import create_notification_service
        
        # Create notification service instance
        notification_service = create_notification_service(datastore, notification_q)
        
        notification_service.send_content_changed_notification(watch_uuid)
    except Exception as e:
        logger.error(f"Error sending notification for {watch_uuid}: {e}")


async def send_filter_failure_notification(watch_uuid, notification_q, datastore):
    """Helper function to send filter failure notifications using the new notification service"""
    try:
        from changedetectionio.notification_service import create_notification_service
        
        # Create notification service instance
        notification_service = create_notification_service(datastore, notification_q)
        
        notification_service.send_filter_failure_notification(watch_uuid)
    except Exception as e:
        logger.error(f"Error sending filter failure notification for {watch_uuid}: {e}")


async def send_step_failure_notification(watch_uuid, step_n, notification_q, datastore):
    """Helper function to send step failure notifications using the new notification service"""
    try:
        from changedetectionio.notification_service import create_notification_service
        
        # Create notification service instance
        notification_service = create_notification_service(datastore, notification_q)
        
        notification_service.send_step_failure_notification(watch_uuid, step_n)
    except Exception as e:
        logger.error(f"Error sending step failure notification for {watch_uuid}: {e}")