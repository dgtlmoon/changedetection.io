#!/bin/bash


# live_server will throw errors even with live_server_scope=function if I have the live_server setup in different functions
# and I like to restart the server for each test (and have the test cleanup after each test)
# merge request welcome :)


# exit when any command fails
set -e

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

find tests/test_*py -type f|while read test_name
do
  echo "TEST RUNNING $test_name"
  # REMOVE_REQUESTS_OLD_SCREENSHOTS disabled so that we can write a screenshot and send it in test_notifications.py without a real browser
  REMOVE_REQUESTS_OLD_SCREENSHOTS=false pytest $test_name
done

echo "RUNNING WITH BASE_URL SET"

# Now re-run some tests with BASE_URL enabled
# Re #65 - Ability to include a link back to the installation, in the notification.
export BASE_URL="https://really-unique-domain.io"
REMOVE_REQUESTS_OLD_SCREENSHOTS=false pytest tests/test_notification.py


# Re-run with HIDE_REFERER set - could affect login
export HIDE_REFERER=True
pytest tests/test_access_control.py

# Re-run a few tests that will trigger brotli based storage
export SNAPSHOT_BROTLI_COMPRESSION_THRESHOLD=5
pytest tests/test_access_control.py
REMOVE_REQUESTS_OLD_SCREENSHOTS=false pytest tests/test_notification.py
pytest tests/test_backend.py
pytest tests/test_rss.py
pytest tests/test_unique_lines.py

# Check file:// will pickup a file when enabled
echo "Hello world" > /tmp/test-file.txt
ALLOW_FILE_URI=yes pytest tests/test_security.py
