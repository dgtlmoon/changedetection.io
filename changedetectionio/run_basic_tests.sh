#!/bin/bash


# live_server will throw errors even with live_server_scope=function if I have the live_server setup in different functions
# and I like to restart the server for each test (and have the test cleanup after each test)
# merge request welcome :)


# exit when any command fails
set -e

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

# Since theres no curl installed lets roll with python3
check_sanity() {
  local port="$1"
  if [ -z "$port" ]; then
    echo "Usage: check_sanity <port>" >&2
    return 1
  fi

  python3 - "$port" <<'PYCODE'
import sys, time, urllib.request, socket

port = sys.argv[1]
url = f'http://localhost:{port}'
ok = False

for _ in range(6):  # --retry 6
    try:
        r = urllib.request.urlopen(url, timeout=3).read().decode()
        if 'est-url-is-sanity' in r:
            ok = True
            break
    except (urllib.error.URLError, ConnectionRefusedError, socket.error):
        time.sleep(1)
sys.exit(0 if ok else 1)
PYCODE
}

data_sanity_test () {
  # Restart data sanity test
  cd ..
  TMPDIR=$(mktemp -d)
  PORT_N=$((5000 + RANDOM % (6501 - 5000)))
  ./changedetection.py -p $PORT_N -d $TMPDIR -u "https://localhost?test-url-is-sanity=1" &
  PID=$!
  sleep 5
  kill $PID
  sleep 2
  ./changedetection.py -p $PORT_N -d $TMPDIR &
  PID=$!
  sleep 5
  # On a restart the URL should still be there
  check_sanity $PORT_N || exit 1
  kill $PID
  cd $OLDPWD

  # datastore looks alright, continue
}

data_sanity_test

echo "-------------------- Running rest of tests in parallel -------------------------------"

# REMOVE_REQUESTS_OLD_SCREENSHOTS disabled so that we can write a screenshot and send it in test_notifications.py without a real browser
REMOVE_REQUESTS_OLD_SCREENSHOTS=false \
pytest tests/test_*.py \
  -n 30 \
  --dist=load \
  -vvv \
  -s \
  --capture=no \
  --log-cli-level=DEBUG \
  --log-cli-format="%(asctime)s [%(process)d] [%(levelname)s] %(name)s: %(message)s"

echo "---------------------------- DONE parallel test ---------------------------------------"

echo "RUNNING WITH BASE_URL SET"

# Now re-run some tests with BASE_URL enabled
# Re #65 - Ability to include a link back to the installation, in the notification.
export BASE_URL="https://really-unique-domain.io"

# Re-run with HIDE_REFERER set - could affect login
export HIDE_REFERER=True
REMOVE_REQUESTS_OLD_SCREENSHOTS=false pytest -vv -s --maxfail=1 tests/test_notification.py tests/test_access_control.py


# Re-run a few tests that will trigger brotli based storage
# And again with brotli+screenshot attachment
SNAPSHOT_BROTLI_COMPRESSION_THRESHOLD=5 REMOVE_REQUESTS_OLD_SCREENSHOTS=false pytest -vv -s --maxfail=1 --dist=load tests/test_backend.py tests/test_rss.py tests/test_unique_lines.py tests/test_notification.py  tests/test_access_control.py

# Try high concurrency with aggressive worker restarts
FETCH_WORKERS=50 WORKER_MAX_RUNTIME=2 WORKER_MAX_JOBS=1 pytest  tests/test_history_consistency.py -vv -l -s

# Check file:// will pickup a file when enabled
echo "Hello world" > /tmp/test-file.txt
ALLOW_FILE_URI=yes pytest -vv -s  tests/test_security.py


# Run it again so that brotli kicks in
TEST_WITH_BROTLI=1 SNAPSHOT_BROTLI_COMPRESSION_THRESHOLD=100 FETCH_WORKERS=20 pytest tests/test_history_consistency.py -vv -l -s
