diff --git a/changedetectionio/content_fetcher.py b/changedetectionio/content_fetcher.py
index 331ef959..ca43edc8 100644
--- a/changedetectionio/content_fetcher.py
+++ b/changedetectionio/content_fetcher.py
@@ -309,7 +309,10 @@ class base_html_playwright(Fetcher):
                 page.set_default_navigation_timeout(90000)
                 page.set_default_timeout(90000)
 
-               # Bug - never set viewport size BEFORE page.goto
+                # Listen for all console events and handle errors
+                page.on("console", lambda msg: print(f"Playwright console: Watch URL: {url} {msg.type}: {msg.text} {msg.args}"))
+
+                # Bug - never set viewport size BEFORE page.goto
 
                 # Waits for the next navigation. Using Python context manager
                 # prevents a race condition between clicking and waiting for a navigation.
