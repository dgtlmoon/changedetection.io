diff --git a/changedetectionio/__init__.py b/changedetectionio/__init__.py
index aa9c810..d6e2d01 100644
--- a/changedetectionio/__init__.py
+++ b/changedetectionio/__init__.py
@@ -541,14 +541,16 @@ def changedetection_app(config=None, datastore_o=None):
             # probably there should be a nice little handler for this.
             if datastore.data['watching'][uuid]['fetch_backend'] is None:
                 form.fetch_backend.data = datastore.data['settings']['application']['fetch_backend']
-            if datastore.data['watching'][uuid]['minutes_between_check'] is None:
-                form.minutes_between_check.data = datastore.data['settings']['requests']['minutes_between_check']
+
+#            if datastore.data['watching'][uuid].has_empty_checktime:
+#                form.time_between_check.data = dict(datastore.data['settings']['requests']['time_between_check'])
 
         if request.method == 'POST' and form.validate():
 
             # Re #110, if they submit the same as the default value, set it to None, so we continue to follow the default
-            if form.minutes_between_check.data == datastore.data['settings']['requests']['minutes_between_check']:
-                form.minutes_between_check.data = None
+#            if form.minutes_between_check.data == datastore.data['settings']['requests']['minutes_between_check']:
+#                form.minutes_between_check.data = None
+
             if form.fetch_backend.data == datastore.data['settings']['application']['fetch_backend']:
                 form.fetch_backend.data = None
 
@@ -1177,7 +1179,7 @@ def ticker_thread_check_time_launch_checks():
         now = time.time()
 
         recheck_time_minimum_seconds = int(os.getenv('MINIMUM_SECONDS_RECHECK_TIME', 60))
-        recheck_time_system_seconds = int(copied_datastore.data['settings']['requests']['minutes_between_check']) * 60
+        recheck_time_system_seconds = datastore.threshold_seconds
 
         for uuid, watch in copied_datastore.data['watching'].items():
 
diff --git a/changedetectionio/forms.py b/changedetectionio/forms.py
index b0dd561..c1333a6 100644
--- a/changedetectionio/forms.py
+++ b/changedetectionio/forms.py
@@ -85,6 +85,13 @@ class SaltyPasswordField(StringField):
         else:
             self.data = False
 
+class TimeBetweenCheckForm(Form):
+    weeks = IntegerField('Weeks', validators=[validators.Optional(), validators.NumberRange(min=0, message="Should contain zero or more seconds")])
+    days = IntegerField('Days', validators=[validators.Optional(), validators.NumberRange(min=0, message="Should contain zero or more seconds")])
+    hours = IntegerField('Hours', validators=[validators.Optional(), validators.NumberRange(min=0, message="Should contain zero or more seconds")])
+    minutes = IntegerField('Minutes', validators=[validators.Optional(), validators.NumberRange(min=0, message="Should contain zero or more seconds")])
+    seconds = IntegerField('Seconds', validators=[validators.Optional(), validators.NumberRange(min=0, message="Should contain zero or more seconds")])
+    # @todo add total seconds minimum validatior = minimum_seconds_recheck_time
 
 # Separated by  key:value
 class StringDictKeyValue(StringField):
@@ -313,8 +320,7 @@ class watchForm(commonSettingsForm):
     url = fields.URLField('URL', validators=[validateURL()])
     tag = StringField('Group tag', [validators.Optional(), validators.Length(max=35)], default='')
 
-    minutes_between_check = fields.IntegerField('Maximum time in minutes until recheck',
-                                               [validators.Optional(), validators.NumberRange(min=1)])
+    time_between_check = FormField(TimeBetweenCheckForm)
 
     css_filter = StringField('CSS/JSON/XPATH Filter', [ValidateCSSJSONXPATHInput()], default='')
 
@@ -347,8 +353,9 @@ class watchForm(commonSettingsForm):
 
 # datastore.data['settings']['requests']..
 class globalSettingsRequestForm(Form):
-    minutes_between_check = fields.IntegerField('Maximum time in minutes until recheck',
-                                               [validators.NumberRange(min=1)])
+    time_between_check = FormField(TimeBetweenCheckForm)
+
+
 # datastore.data['settings']['application']..
 class globalSettingsApplicationForm(commonSettingsForm):
 
diff --git a/changedetectionio/model/App.py b/changedetectionio/model/App.py
index c54df50..e1bbb5f 100644
--- a/changedetectionio/model/App.py
+++ b/changedetectionio/model/App.py
@@ -24,8 +24,7 @@ class model(dict):
                 },
                 'requests': {
                     'timeout': 15,  # Default 15 seconds
-                    # Default 3 hours
-                    'minutes_between_check': 3 * 60,  # Default 3 hours
+                    'time_between_check': {'weeks': None, 'days': None, 'hours': 3, 'minutes': None, 'seconds': None},
                     'workers': 10  # Number of threads, lower is better for slow connections
                 },
                 'application': {
diff --git a/changedetectionio/model/Watch.py b/changedetectionio/model/Watch.py
index b86b930..b0d7211 100644
--- a/changedetectionio/model/Watch.py
+++ b/changedetectionio/model/Watch.py
@@ -42,7 +42,7 @@ class model(dict):
             # Re #110, so then if this is set to None, we know to use the default value instead
             # Requires setting to None on submit if it's the same as the default
             # Should be all None by default, so we use the system default in this case.
-            'minutes_between_check': None
+            'time_between_check': {'weeks': None, 'days': None, 'hours': None, 'minutes': None, 'seconds': None}
         })
         # goes at the end so we update the default object with the initialiser
         super(model, self).__init__(*arg, **kw)
@@ -50,13 +50,17 @@ class model(dict):
 
     @property
     def has_empty_checktime(self):
-        if self.get('minutes_between_check', None):
-            return False
-        return True
+        # using all() + dictionary comprehension
+        # Check if all values are 0 in dictionary
+        res = all(x == None or x == False or x==0 for x in self.get('time_between_check', {}).values())
+        return res
 
     @property
     def threshold_seconds(self):
-        sec = self.get('minutes_between_check', None)
-        if sec:
-            sec = sec * 60
-        return sec
+        seconds = 0
+        mtable = {'seconds': 1, 'minutes': 60, 'hours': 3600, 'days': 86400, 'weeks': 86400 * 7}
+        for m, n in mtable.items():
+            x = self.get('time_between_check', {}).get(m, None)
+            if x:
+                seconds += x * n
+        return max(seconds, minimum_seconds_recheck_time)
diff --git a/changedetectionio/store.py b/changedetectionio/store.py
index 9aeebee..6e11b1f 100644
--- a/changedetectionio/store.py
+++ b/changedetectionio/store.py
@@ -7,6 +7,7 @@ import uuid as uuid_builder
 from copy import deepcopy
 from os import mkdir, path, unlink
 from threading import Lock
+import re
 
 from changedetectionio.model import Watch, App
 
@@ -100,6 +101,9 @@ class ChangeDetectionStore:
             secret = secrets.token_hex(16)
             self.__data['settings']['application']['rss_access_token'] = secret
 
+        # Bump the update version by running updates
+        self.run_updates()
+
         self.needs_write = True
 
         # Finally start the thread that will manage periodic data saves to JSON
@@ -145,6 +149,17 @@ class ChangeDetectionStore:
 
         self.needs_write = True
 
+    @property
+    def threshold_seconds(self):
+        seconds = 0
+        mtable = {'seconds': 1, 'minutes': 60, 'hours': 3600, 'days': 86400, 'weeks': 86400 * 7}
+        minimum_seconds_recheck_time = int(os.getenv('MINIMUM_SECONDS_RECHECK_TIME', 5))
+        for m, n in mtable.items():
+            x = self.__data['settings']['requests']['time_between_check'].get(m)
+            if x:
+                seconds += x * n
+        return max(seconds, minimum_seconds_recheck_time)
+
     @property
     def data(self):
         has_unviewed = False
@@ -398,3 +413,41 @@ class ChangeDetectionStore:
             if not str(item) in index:
                 print ("Removing",item)
                 unlink(item)
+
+    # Run all updates
+    # IMPORTANT - Each update could be run even when they have a new install and the schema is correct
+    #             So therefor - each `update_n` should be very careful about checking if it needs to actually run
+    #             Probably we should bump the current update schema version with each tag release version?
+    def run_updates(self):
+        import inspect
+        updates_available = []
+        for i, o in inspect.getmembers(self, predicate=inspect.ismethod):
+            m = re.search(r'update_(\d+)$', i)
+            if m:
+                updates_available.append(int(m.group(1)))
+        updates_available.sort()
+
+        for update_n in updates_available:
+            if update_n > self.__data['settings']['application']['schema_version']:
+                print ("Applying update_{}".format((update_n)))
+                try:
+                    update_method = getattr(self, "update_{}".format(update_n))()
+                except Exception as e:
+                    print("Error while trying update_{}".format((update_n)))
+                    print(e)
+                    # Don't run any more updates
+                    return
+                else:
+                    # Bump the version, important
+                    self.__data['settings']['application']['schema_version'] = update_n
+
+    # Convert minutes to seconds on settings and each watch
+    def update_1(self):
+        if 'minutes_between_check' in self.data['settings']['requests']:
+            self.data['settings']['requests']['time_between_check']['minutes'] = self.data['settings']['requests']['minutes_between_check']
+
+        for uuid, watch in self.data['watching'].items():
+            if 'minutes_between_check' in watch:
+                # Only upgrade individual watch time if it was set
+                if watch.get('minutes_between_check', False):
+                    self.data['watching'][uuid]['time_between_check']['minutes'] = watch['minutes_between_check']
diff --git a/changedetectionio/templates/edit.html b/changedetectionio/templates/edit.html
index f1cdc08..2f64e3c 100644
--- a/changedetectionio/templates/edit.html
+++ b/changedetectionio/templates/edit.html
@@ -41,7 +41,7 @@
                         <span class="pure-form-message-inline">Organisational tag/group name used in the main listing page</span>
                     </div>
                     <div class="pure-control-group">
-                        {{ render_field(form.minutes_between_check) }}
+                        {{ render_field(form.time_between_check) }}
                         {% if has_empty_checktime %}
                         <span class="pure-form-message-inline">Currently using the <a
                                 href="{{ url_for('settings_page', uuid=uuid) }}">default global settings</a>, change to another value if you want to be specific.</span>
diff --git a/changedetectionio/templates/settings.html b/changedetectionio/templates/settings.html
index 385f64d..c3cf109 100644
--- a/changedetectionio/templates/settings.html
+++ b/changedetectionio/templates/settings.html
@@ -28,7 +28,7 @@
             <div class="tab-pane-inner" id="general">
                 <fieldset>
                     <div class="pure-control-group">
-                        {{ render_field(form.requests.form.minutes_between_check) }}
+                        {{ render_field(form.requests.form.time_between_check) }}
                         <span class="pure-form-message-inline">Default time for all watches, when the watch does not have a specific time setting.</span>
                     </div>
                     <div class="pure-control-group">

