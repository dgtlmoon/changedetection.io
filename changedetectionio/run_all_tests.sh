#!/bin/bash


# live_server will throw errors even with live_server_scope=function if I have the live_server setup in different functions
# and I like to restart the server for each test (and have the test cleanup after each test)
# merge request welcome :)


# exit when any command fails
set -e

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
# Note - this is not UI functional tests

docker run -d --name test_selenium --restart unless-stopped -p 4444:4444  --shm-size="2g"  selenium/standalone-chrome-debug:3.141.59
echo "TESTING SELENIUM/WEBDRIVER..."
export WEBDRIVER_URL=http://localhost:4444/wd/hub
pytest tests/fetchers/test_content.py
unset WEBDRIVER_URL
docker kill test_selenium


docker run -d -e "DEFAULT_LAUNCH_ARGS=[\"--window-size=1920,1080\"]" -p 3000:3000  --shm-size="2g" --name test_browserless browserless/chrome
echo "TESTING PLAYWRIGHT/BROWSERLESS..."
export PLAYWRIGHT_DRIVER_URL=ws://127.0.0.1:3000
pytest tests/fetchers/test_content.py
unset PLAYWRIGHT_DRIVER_URL
docker kill test_browserless
