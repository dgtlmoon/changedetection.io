import threading
import queue
import time

# Requests for checking on the site use a pool of thread Workers managed by a Queue.
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

                    try:
                        now = time.time()
                        changed_detected, update_obj, contents = update_handler.run(uuid)

                        # Always record that we atleast tried
                        self.datastore.update_watch(uuid=uuid, update_obj={'fetch_time': round(time.time() - now, 3)})

                    except PermissionError as e:
                        self.app.logger.error("File permission error updating", uuid, str(e))
                    except content_fetcher.EmptyReply as e:
                        self.datastore.update_watch(uuid=uuid, update_obj={'last_error':str(e)})

                    except Exception as e:
                        self.app.logger.error("Exception reached processing watch UUID:%s - %s", uuid, str(e))
                        self.datastore.update_watch(uuid=uuid, update_obj={'last_error': str(e)})

                    else:
                        if update_obj:
                            try:
                                self.datastore.update_watch(uuid=uuid, update_obj=update_obj)
                                if changed_detected:

                                    # A change was detected
                                    newest_version_file_contents = ""
                                    fname = self.datastore.save_history_text(watch_uuid=uuid, contents=contents)

                                    # Update history with the stripped text for future reference, this will also mean we save the first
                                    # Should always be keyed by string(timestamp)
                                    self.datastore.update_watch(uuid, {"history": {str(update_obj["last_checked"]): fname}})

                                    watch = self.datastore.data['watching'][uuid]

                                    print (">> Change detected in UUID {} - {}".format(uuid, watch['url']))

                                    # Get the newest snapshot data to be possibily used in a notification
                                    newest_key = self.datastore.get_newest_history_key(uuid)
                                    if newest_key:
                                        with open(watch['history'][newest_key], 'r') as f:
                                            newest_version_file_contents = f.read().strip()

                                    n_object = {
                                        'watch_url': watch['url'],
                                        'uuid': uuid,
                                        'current_snapshot': newest_version_file_contents
                                    }

                                    # Did it have any notification alerts to hit?
                                    if len(watch['notification_urls']):
                                        print(">>> Notifications queued for UUID from watch {}".format(uuid))
                                        n_object['notification_urls'] = watch['notification_urls']
                                        n_object['notification_title'] = watch['notification_title']
                                        n_object['notification_body'] = watch['notification_body']
                                        n_object['notification_format'] = watch['notification_format']
                                        self.notification_q.put(n_object)

                                    # No? maybe theres a global setting, queue them all
                                    elif len(self.datastore.data['settings']['application']['notification_urls']):
                                        print(">>> Watch notification URLs were empty, using GLOBAL notifications for UUID: {}".format(uuid))
                                        n_object['notification_urls'] = self.datastore.data['settings']['application']['notification_urls']
                                        n_object['notification_title'] = self.datastore.data['settings']['application']['notification_title']
                                        n_object['notification_body'] = self.datastore.data['settings']['application']['notification_body']
                                        n_object['notification_format'] = self.datastore.data['settings']['application']['notification_format']
                                        self.notification_q.put(n_object)
                                    else:
                                        print(">>> NO notifications queued, watch and global notification URLs were empty.")

                            except Exception as e:
                                print("!!!! Exception in update_worker !!!\n", e)

                self.current_uuid = None  # Done
                self.q.task_done()

            self.app.config.exit.wait(1)
