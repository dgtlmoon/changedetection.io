import threading
import queue

# Requests for checking on the site use a pool of thread Workers managed by a Queue.
class update_worker(threading.Thread):
    current_uuid = None

    def __init__(self, q, app, datastore, *args, **kwargs):
        self.q = q
        self.app = app
        self.datastore = datastore
        super().__init__(*args, **kwargs)

    def run(self):
        from backend import fetch_site_status

        update_handler = fetch_site_status.perform_site_check(datastore=self.datastore)

        while not self.app.config.exit.is_set():

            try:
                uuid = self.q.get(block=False)
            except queue.Empty:
                pass

            else:
                self.current_uuid = uuid

                if uuid in list(self.datastore.data['watching'].keys()):
                    try:
                        changed_detected, result, contents = update_handler.run(uuid)

                    except PermissionError as s:
                        self.app.logger.error("File permission error updating", uuid, str(s))
                    else:
                        if result:
                            self.datastore.update_watch(uuid=uuid, update_obj=result)
                            if changed_detected:
                                # A change was detected
                                self.datastore.save_history_text(uuid=uuid, contents=contents, result_obj=result)

                self.current_uuid = None  # Done
                self.q.task_done()

            self.app.config.exit.wait(1)
