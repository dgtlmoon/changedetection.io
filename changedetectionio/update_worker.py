import threading
import queue
import time

# A single update worker
#
# Requests for checking on a single site(watch) from a queue of watches
# (another process inserts watches into the queue that are time-ready for checking)


class update_worker(threading.Thread):
    current_uuid = None

    def __init__(self, q, notification_q, app, datastore, *args, **kwargs):
        self.q = q
        self.app = app
        self.notification_q = notification_q
        self.datastore = datastore
        super().__init__(*args, **kwargs)

    def run(self):
        from changedetectionio import fetch_site_status

        update_handler = fetch_site_status.perform_site_check(datastore=self.datastore)

        while not self.app.config.exit.is_set():

            try:
                uuid = self.q.get(block=False)
            except queue.Empty:
                pass

            else:
                self.current_uuid = uuid
                from changedetectionio import content_fetcher

                if uuid in list(self.datastore.data['watching'].keys()):

                    changed_detected = False
                    contents = ""
                    update_obj= {}
                    now = time.time()

                    try:

                        changed_detected, update_obj, contents = update_handler.run(uuid)

                        # Re #342
                        # In Python 3, all strings are sequences of Unicode characters. There is a bytes type that holds raw bytes.
                        # We then convert/.decode('utf-8') for the notification etc
                        if not isinstance(contents, (bytes, bytearray)):
                            raise Exception("Error - returned data from the fetch handler SHOULD be bytes")


                    except PermissionError as e:
                        self.app.logger.error("File permission error updating", uuid, str(e))
                    except content_fetcher.EmptyReply as e:
                        # Some kind of custom to-str handler in the exception handler that does this?
                        err_text = "EmptyReply: Status Code {}".format(e.status_code)
                        self.datastore.update_watch(uuid=uuid, update_obj={'last_error': err_text,
                                                                           'last_check_status': e.status_code})
                    except Exception as e:
                        self.app.logger.error("Exception reached processing watch UUID: %s - %s", uuid, str(e))
                        self.datastore.update_watch(uuid=uuid, update_obj={'last_error': str(e)})

                    else:
                        try:
                            watch = self.datastore.data['watching'][uuid]
                            fname = "" # Saved history text filename

                            # For the FIRST time we check a site, or a change detected, save the snapshot.
                            if changed_detected or not watch['last_checked']:
                                # A change was detected
                                fname = self.datastore.save_history_text(watch_uuid=uuid, contents=contents)
                                # Should always be keyed by string(timestamp)
                                self.datastore.update_watch(uuid, {"history": {str(round(time.time())): fname}})

                            # Generally update anything interesting returned
                            self.datastore.update_watch(uuid=uuid, update_obj=update_obj)

                            # A change was detected
                            if changed_detected:
                                n_object = {}
                                print (">> Change detected in UUID {} - {}".format(uuid, watch['url']))

                                # Notifications should only trigger on the second time (first time, we gather the initial snapshot)
                                if len(watch['history']) > 1:

                                    dates = list(watch['history'].keys())
                                    # Convert to int, sort and back to str again
                                    # @todo replace datastore getter that does this automatically
                                    dates = [int(i) for i in dates]
                                    dates.sort(reverse=True)
                                    dates = [str(i) for i in dates]

                                    prev_fname = watch['history'][dates[1]]


                                    # Did it have any notification alerts to hit?
                                    if len(watch['notification_urls']):
                                        print(">>> Notifications queued for UUID from watch {}".format(uuid))
                                        n_object['notification_urls'] = watch['notification_urls']
                                        n_object['notification_title'] = watch['notification_title']
                                        n_object['notification_body'] = watch['notification_body']
                                        n_object['notification_format'] = watch['notification_format']

                                    # No? maybe theres a global setting, queue them all
                                    elif len(self.datastore.data['settings']['application']['notification_urls']):
                                        print(">>> Watch notification URLs were empty, using GLOBAL notifications for UUID: {}".format(uuid))
                                        n_object['notification_urls'] = self.datastore.data['settings']['application']['notification_urls']
                                        n_object['notification_title'] = self.datastore.data['settings']['application']['notification_title']
                                        n_object['notification_body'] = self.datastore.data['settings']['application']['notification_body']
                                        n_object['notification_format'] = self.datastore.data['settings']['application']['notification_format']
                                    else:
                                        print(">>> NO notifications queued, watch and global notification URLs were empty.")

                                    # Only prepare to notify if the rules above matched
                                    if 'notification_urls' in n_object:
                                        # HTML needs linebreak, but MarkDown and Text can use a linefeed
                                        if n_object['notification_format'] == 'HTML':
                                            line_feed_sep = "</br>"
                                        else:
                                            line_feed_sep = "\n"

                                        from changedetectionio import diff
                                        n_object.update({
                                            'watch_url': watch['url'],
                                            'uuid': uuid,
                                            'current_snapshot': contents.decode('utf-8'),
                                            'diff': diff.render_diff(prev_fname, fname, line_feed_sep=line_feed_sep),
                                            'diff_full': diff.render_diff(prev_fname, fname, True, line_feed_sep=line_feed_sep)
                                        })

                                        self.notification_q.put(n_object)

                        except Exception as e:
                            # Catch everything possible here, so that if a worker crashes, we don't lose it until restart!
                            print("!!!! Exception in update_worker !!!\n", e)
                            self.app.logger.error("Exception reached processing watch UUID: %s - %s", uuid, str(e))
                            self.datastore.update_watch(uuid=uuid, update_obj={'last_error': str(e)})

                    finally:
                        # Always record that we atleast tried
                        self.datastore.update_watch(uuid=uuid, update_obj={'fetch_time': round(time.time() - now, 3),
                                                                           'last_checked': round(time.time())})

                self.current_uuid = None  # Done
                self.q.task_done()

                # Give the CPU time to interrupt
                time.sleep(0.1)

            self.app.config.exit.wait(1)
