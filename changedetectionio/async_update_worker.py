from .processors.exceptions import ProcessorException
import changedetectionio.content_fetchers.exceptions as content_fetchers_exceptions
from changedetectionio.processors.text_json_diff.processor import FilterNotFoundInResponse
from changedetectionio import html_tools
from changedetectionio.flask_app import watch_check_update

import asyncio
import importlib
import os
import time

from loguru import logger

# Async version of update_worker
# Processes jobs from AsyncSignalPriorityQueue instead of threaded queue

async def async_update_worker(worker_id, q, notification_q, app, datastore):
    """
    Async worker function that processes watch check jobs from the queue.
    
    Args:
        worker_id: Unique identifier for this worker
        q: AsyncSignalPriorityQueue containing jobs to process
        notification_q: Standard queue for notifications
        app: Flask application instance
        datastore: Application datastore
    """
    # Set a descriptive name for this task
    task = asyncio.current_task()
    if task:
        task.set_name(f"async-worker-{worker_id}")
    
    logger.info(f"Starting async worker {worker_id}")
    
    while not app.config.exit.is_set():
        update_handler = None
        watch = None

        try:
            # Use asyncio wait_for to make queue.get() cancellable
            queued_item_data = await asyncio.wait_for(q.get(), timeout=1.0)
        except asyncio.TimeoutError:
            # No jobs available, continue loop
            continue
        except Exception as e:
            logger.error(f"Worker {worker_id} error getting queue item: {e}")
            await asyncio.sleep(0.1)
            continue
        
        uuid = queued_item_data.item.get('uuid')
        fetch_start_time = round(time.time())
        
        # Mark this UUID as being processed
        from changedetectionio import worker_handler
        worker_handler.set_uuid_processing(uuid, processing=True)
        
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
                    watch_check_update.send(watch_uuid=uuid)

                    # Processor is what we are using for detecting the "Change"
                    processor = watch.get('processor', 'text_json_diff')

                    # Init a new 'difference_detection_processor'
                    processor_module_name = f"changedetectionio.processors.{processor}.processor"
                    try:
                        processor_module = importlib.import_module(processor_module_name)
                    except ModuleNotFoundError as e:
                        print(f"Processor module '{processor}' not found.")
                        raise e

                    update_handler = processor_module.perform_site_check(datastore=datastore,
                                                                         watch_uuid=uuid)

                    # All fetchers are now async, so call directly
                    await update_handler.call_browser()

                    # Run change detection (this is synchronous)
                    changed_detected, update_obj, contents = update_handler.run_changedetection(watch=watch)

                except PermissionError as e:
                    logger.critical(f"File permission error updating file, watch: {uuid}")
                    logger.critical(str(e))
                    process_changedetection_results = False

                except ProcessorException as e:
                    if e.screenshot:
                        watch.save_screenshot(screenshot=e.screenshot)
                    if e.xpath_data:
                        watch.save_xpath_data(data=e.xpath_data)
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

                    if e.xpath_data:
                        watch.save_xpath_data(data=e.xpath_data)
                        
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
                    if e.xpath_data:
                        watch.save_xpath_data(data=e.xpath_data, as_error=True)
                    if e.page_text:
                        watch.save_error_text(contents=e.page_text)

                    datastore.update_watch(uuid=uuid, update_obj={'last_error': err_text})
                    process_changedetection_results = False

                except FilterNotFoundInResponse as e:
                    if not datastore.data['watching'].get(uuid):
                        continue

                    err_text = "Warning, no filters were found, no change detection ran - Did the page change layout? update your Visual Filter if necessary."
                    datastore.update_watch(uuid=uuid, update_obj={'last_error': err_text})

                    # Filter wasnt found, but we should still update the visual selector so that they can have a chance to set it up again
                    if e.screenshot:
                        watch.save_screenshot(screenshot=e.screenshot)

                    if e.xpath_data:
                        watch.save_xpath_data(data=e.xpath_data)

                    # Only when enabled, send the notification
                    if watch.get('filter_failure_notification_send', False):
                        c = watch.get('consecutive_filter_failures', 0)
                        c += 1
                        # Send notification if we reached the threshold?
                        threshold = datastore.data['settings']['application'].get('filter_failure_notification_threshold_attempts', 0)
                        logger.debug(f"Filter for {uuid} not found, consecutive_filter_failures: {c} of threshold {threshold}")
                        if c >= threshold:
                            if not watch.get('notification_muted'):
                                logger.debug(f"Sending filter failed notification for {uuid}")
                                await send_filter_failure_notification(uuid, notification_q, datastore)
                            c = 0
                            logger.debug(f"Reset filter failure count back to zero")

                        datastore.update_watch(uuid=uuid, update_obj={'consecutive_filter_failures': c})
                    else:
                        logger.trace(f"{uuid} - filter_failure_notification_send not enabled, skipping")

                    process_changedetection_results = False

                except content_fetchers_exceptions.checksumFromPreviousCheckWasTheSame as e:
                    # Yes fine, so nothing todo, don't continue to process.
                    process_changedetection_results = False
                    changed_detected = False
                    
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
                    datastore.update_watch(uuid=uuid, update_obj={'last_error': err_text,
                                                                'last_check_status': e.status_code})
                    process_changedetection_results = False
                    
                except content_fetchers_exceptions.PageUnloadable as e:
                    err_text = "Page request from server didnt respond correctly"
                    if e.message:
                        err_text = "{} - {}".format(err_text, e.message)

                    if e.screenshot:
                        watch.save_screenshot(screenshot=e.screenshot, as_error=True)

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
                    logger.error(f"Worker {worker_id} exception processing watch UUID: {uuid}")
                    logger.error(str(e))
                    datastore.update_watch(uuid=uuid, update_obj={'last_error': "Exception: " + str(e)})
                    process_changedetection_results = False

                else:
                    if not datastore.data['watching'].get(uuid):
                        continue

                    update_obj['content-type'] = update_handler.fetcher.get_all_headers().get('content-type', '').lower()

                    if not watch.get('ignore_status_codes'):
                        update_obj['consecutive_filter_failures'] = 0

                    update_obj['last_error'] = False
                    cleanup_error_artifacts(uuid, datastore)

                if not datastore.data['watching'].get(uuid):
                    continue

                if process_changedetection_results:
                    # Extract title if needed
                    if datastore.data['settings']['application'].get('extract_title_as_title') or watch['extract_title_as_title']:
                        if not watch['title'] or not len(watch['title']):
                            try:
                                update_obj['title'] = html_tools.extract_element(find='title', html_content=update_handler.fetcher.content)
                                logger.info(f"UUID: {uuid} Extract <title> updated title to '{update_obj['title']}")
                            except Exception as e:
                                logger.warning(f"UUID: {uuid} Extract <title> as watch title was enabled, but couldn't find a <title>.")

                    try:
                        datastore.update_watch(uuid=uuid, update_obj=update_obj)

                        if changed_detected or not watch.history_n:
                            if update_handler.screenshot:
                                watch.save_screenshot(screenshot=update_handler.screenshot)

                            if update_handler.xpath_data:
                                watch.save_xpath_data(data=update_handler.xpath_data)

                            # Ensure unique timestamp for history
                            if watch.newest_history_key and int(fetch_start_time) == int(watch.newest_history_key):
                                logger.warning(f"Timestamp {fetch_start_time} already exists, waiting 1 seconds")
                                fetch_start_time += 1
                                await asyncio.sleep(1)

                            watch.save_history_text(contents=contents,
                                                    timestamp=int(fetch_start_time),
                                                    snapshot_id=update_obj.get('previous_md5', 'none'))

                            empty_pages_are_a_change = datastore.data['settings']['application'].get('empty_pages_are_a_change', False)
                            if update_handler.fetcher.content or (not update_handler.fetcher.content and empty_pages_are_a_change):
                                watch.save_last_fetched_html(contents=update_handler.fetcher.content, timestamp=int(fetch_start_time))

                            # Send notifications on second+ check
                            if watch.history_n >= 2:
                                logger.info(f"Change detected in UUID {uuid} - {watch['url']}")
                                if not watch.get('notification_muted'):
                                    await send_content_changed_notification(uuid, notification_q, datastore)

                    except Exception as e:
                        logger.critical(f"Worker {worker_id} exception in process_changedetection_results")
                        logger.critical(str(e))
                        datastore.update_watch(uuid=uuid, update_obj={'last_error': str(e)})

                # Always record attempt count
                count = watch.get('check_count', 0) + 1

                # Record server header
                try:
                    server_header = update_handler.fetcher.headers.get('server', '').strip().lower()[:255]
                    datastore.update_watch(uuid=uuid, update_obj={'remote_server_reply': server_header})
                except Exception as e:
                    pass

                datastore.update_watch(uuid=uuid, update_obj={'fetch_time': round(time.time() - fetch_start_time, 3),
                                                               'check_count': count})

        except Exception as e:
            logger.error(f"Worker {worker_id} unexpected error processing {uuid}: {e}")
            logger.error(f"Worker {worker_id} traceback:", exc_info=True)
            
            # Also update the watch with error information
            if datastore and uuid in datastore.data['watching']:
                datastore.update_watch(uuid=uuid, update_obj={'last_error': f"Worker error: {str(e)}"})
        
        finally:
            # Always cleanup - this runs whether there was an exception or not
            if uuid:
                try:
                    # Mark UUID as no longer being processed
                    worker_handler.set_uuid_processing(uuid, processing=False)
                    
                    # Send completion signal
                    if watch:
                        #logger.info(f"Worker {worker_id} sending completion signal for UUID {watch['uuid']}")
                        watch_check_update.send(watch_uuid=watch['uuid'])

                    update_handler = None
                    logger.debug(f"Worker {worker_id} completed watch {uuid} in {time.time()-fetch_start_time:.2f}s")
                except Exception as cleanup_error:
                    logger.error(f"Worker {worker_id} error during cleanup: {cleanup_error}")
            
            # Brief pause before continuing to avoid tight error loops (only on error)
            if 'e' in locals():
                await asyncio.sleep(1.0)
            else:
                # Small yield for normal completion
                await asyncio.sleep(0.01)

        # Check if we should exit
        if app.config.exit.is_set():
            break

    # Check if we're in pytest environment - if so, be more gentle with logging
    import sys
    in_pytest = "pytest" in sys.modules or "PYTEST_CURRENT_TEST" in os.environ
    
    if not in_pytest:
        logger.info(f"Worker {worker_id} shutting down")


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