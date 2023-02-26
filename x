diff --git a/changedetectionio/update_worker.py b/changedetectionio/update_worker.py
index 4da06f44..ddc83775 100644
--- a/changedetectionio/update_worker.py
+++ b/changedetectionio/update_worker.py
@@ -169,10 +169,8 @@ class update_worker(threading.Thread):
                 if uuid in list(self.datastore.data['watching'].keys()):
                     changed_detected = False
                     contents = b''
-                    screenshot = False
-                    update_obj= {}
-                    xpath_data = False
                     process_changedetection_results = True
+                    update_obj= {}
                     print("> Processing UUID {} Priority {} URL {}".format(uuid, queued_item_data.priority, self.datastore.data['watching'][uuid]['url']))
                     now = time.time()
 
@@ -274,6 +272,7 @@ class update_worker(threading.Thread):
                         err_text = "EmptyReply - try increasing 'Wait seconds before extracting text', Status Code {}".format(e.status_code)
                         self.datastore.update_watch(uuid=uuid, update_obj={'last_error': err_text,
                                                                            'last_check_status': e.status_code})
+                        process_changedetection_results = False
                     except content_fetcher.ScreenshotUnavailable as e:
                         err_text = "Screenshot unavailable, page did not render fully in the expected time - try increasing 'Wait seconds before extracting text'"
                         self.datastore.update_watch(uuid=uuid, update_obj={'last_error': err_text,
@@ -285,6 +284,7 @@ class update_worker(threading.Thread):
                             self.datastore.save_screenshot(watch_uuid=uuid, screenshot=e.screenshot, as_error=True)
                         self.datastore.update_watch(uuid=uuid, update_obj={'last_error': err_text,
                                                                            'last_check_status': e.status_code})
+                        process_changedetection_results = False
                     except content_fetcher.PageUnloadable as e:
                         err_text = "Page request from server didnt respond correctly"
                         if e.message:
