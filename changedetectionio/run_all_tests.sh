#!/bin/bash


# live_server will throw errors even with live_server_scope=function if I have the live_server setup in different functions
# and I like to restart the server for each test (and have the test cleanup after each test)
# merge request welcome :)


# exit when any command fails
set -e

export MINIMUM_SECONDS_RECHECK_TIME=0

find tests/test_*py -type f|while read test_name
do
  echo "TEST RUNNING $test_name"
  pytest $test_name
done

echo "RUNNING WITH BASE_URL SET"

# Now re-run some tests with BASE_URL enabled
# Re #65 - Ability to include a link back to the installation, in the notification.
export BASE_URL="https://really-unique-domain.io"
pytest tests/test_notification.py


# Now for the selenium and playwright/browserless fetchers
# Note - this is not UI functional tests - just checking that each one can fetch the content

echo "TESTING WEBDRIVER FETCH > SELENIUM/WEBDRIVER..."
docker run -d --name $$-test_selenium  -p 4444:4444 --rm --shm-size="2g"  selenium/standalone-chrome-debug:3.141.59
# takes a while to spin up
sleep 5
export WEBDRIVER_URL=http://localhost:4444/wd/hub
pytest tests/fetchers/test_content.py
unset WEBDRIVER_URL
docker kill $$-test_selenium

echo "TESTING WEBDRIVER FETCH > PLAYWRIGHT/BROWSERLESS..."
# Not all platforms support playwright (not ARM/rPI), so it's not packaged in requirements.txt
pip3 install playwright~=1.22
docker run -d --name $$-test_browserless -e "DEFAULT_LAUNCH_ARGS=[\"--window-size=1920,1080\"]" --rm  -p 3000:3000  --shm-size="2g"  browserless/chrome:1.53-chrome-stable
# takes a while to spin up
sleep 5
export PLAYWRIGHT_DRIVER_URL=ws://127.0.0.1:3000
pytest tests/fetchers/test_content.py
unset PLAYWRIGHT_DRIVER_URL
docker kill $$-test_browserless