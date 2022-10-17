diff --git a/changedetectionio/__init__.py b/changedetectionio/__init__.py
index c745dd3e..19873cce 100644
--- a/changedetectionio/__init__.py
+++ b/changedetectionio/__init__.py
@@ -819,8 +819,8 @@ def changedetection_app(config=None, datastore_o=None):
         # Read as binary and force decode as UTF-8
         # Windows may fail decode in python if we just use 'r' mode (chardet decode exception)
         try:
-            with open(newest_file, 'rb') as f:
-                newest_version_file_contents = f.read().decode('utf-8')
+            with open(newest_file, 'r', encoding='utf-8', errors='ignore') as f:
+                newest_version_file_contents = f.read()
         except Exception as e:
             newest_version_file_contents = "Unable to read {}.\n".format(newest_file)
 
@@ -832,8 +832,8 @@ def changedetection_app(config=None, datastore_o=None):
             previous_file = history[dates[-2]]
 
         try:
-            with open(previous_file, 'rb') as f:
-                previous_version_file_contents = f.read().decode('utf-8')
+            with open(previous_file, 'r', encoding='utf-8', errors='ignore') as f:
+                previous_version_file_contents = f.read()
         except Exception as e:
             previous_version_file_contents = "Unable to read {}.\n".format(previous_file)
 
@@ -909,7 +909,7 @@ def changedetection_app(config=None, datastore_o=None):
         timestamp = list(watch.history.keys())[-1]
         filename = watch.history[timestamp]
         try:
-            with open(filename, 'r') as f:
+            with open(filename, 'r', encoding='utf-8', errors='ignore') as f:
                 tmp = f.readlines()
 
                 # Get what needs to be highlighted
diff --git a/changedetectionio/model/Watch.py b/changedetectionio/model/Watch.py
index 9a87ad71..566eb88e 100644
--- a/changedetectionio/model/Watch.py
+++ b/changedetectionio/model/Watch.py
@@ -158,7 +158,8 @@ class model(dict):
 
         logging.debug("Saving history text {}".format(snapshot_fname))
 
-        # in /diff/ we are going to assume for now that it's UTF-8 when reading
+        # in /diff/ and /preview/ we are going to assume for now that it's UTF-8 when reading
+        # most sites are utf-8 and some are even broken utf-8
         with open(snapshot_fname, 'wb') as f:
             f.write(contents)
             f.close()
