diff --git a/changedetectionio/content_fetcher.py b/changedetectionio/content_fetcher.py
index 1f86cdd0..04646267 100644
--- a/changedetectionio/content_fetcher.py
+++ b/changedetectionio/content_fetcher.py
@@ -286,6 +286,7 @@ class base_html_playwright(Fetcher):
                 proxy=self.proxy,
                 # This is needed to enable JavaScript execution on GitHub and others
                 bypass_csp=True,
+                service_workers='block',
                 # Should never be needed
                 accept_downloads=False
             )
@@ -306,8 +307,7 @@ class base_html_playwright(Fetcher):
 
                 # Waits for the next navigation. Using Python context manager
                 # prevents a race condition between clicking and waiting for a navigation.
-                with self.page.expect_navigation():
-                    response = self.page.goto(url, wait_until='load')
+                response = self.page.goto(url, wait_until='commit', timeout=90000)
                 # Wait_until = commit
                 # - `'commit'` - consider operation to be finished when network response is received and the document started loading.
                 # Better to not use any smarts from Playwright and just wait an arbitrary number of seconds
