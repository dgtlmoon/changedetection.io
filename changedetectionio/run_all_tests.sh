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
  pytest $test_name
done

echo "RUNNING WITH BASE_URL SET"

# Now re-run some tests with BASE_URL enabled
# Re #65 - Ability to include a link back to the installation, in the notification.
export BASE_URL="https://really-unique-domain.io"
pytest tests/test_notification.py


# Re-run with HIDE_REFERER set - could affect login
export HIDE_REFERER=True
pytest tests/test_access_control.py


# Now for the selenium and playwright/browserless fetchers
# Note - this is not UI functional tests - just checking that each one can fetch the content

echo "TESTING WEBDRIVER FETCH > SELENIUM/WEBDRIVER..."
docker run -d --name $$-test_selenium  -p 4444:4444 --rm --shm-size="2g"  selenium/standalone-chrome-debug:3.141.59
# takes a while to spin up
sleep 5
export WEBDRIVER_URL=http://localhost:4444/wd/hub
pytest tests/fetchers/test_content.py
pytest tests/test_errorhandling.py
unset WEBDRIVER_URL
docker kill $$-test_selenium

echo "TESTING WEBDRIVER FETCH > PLAYWRIGHT/BROWSERLESS..."
# Not all platforms support playwright (not ARM/rPI), so it's not packaged in requirements.txt
PLAYWRIGHT_VERSION=$(grep -i -E "RUN pip install.+" "$SCRIPT_DIR/../Dockerfile" | grep --only-matching -i -E "playwright[=><~+]+[0-9\.]+")
echo "using $PLAYWRIGHT_VERSION"
pip3 install "$PLAYWRIGHT_VERSION"
docker run -d --name $$-test_browserless -e "DEFAULT_LAUNCH_ARGS=[\"--window-size=1920,1080\"]" --rm  -p 3000:3000  --shm-size="2g"  browserless/chrome:1.53-chrome-stable
# takes a while to spin up
sleep 5
export PLAYWRIGHT_DRIVER_URL=ws://127.0.0.1:3000
pytest tests/fetchers/test_content.py
pytest tests/test_errorhandling.py
pytest tests/visualselector/test_fetch_data.py

unset PLAYWRIGHT_DRIVER_URL
docker kill $$-test_browserless

# Test proxy list handling, starting two squids on different ports
# Each squid adds a different header to the response, which is the main thing we test for.
docker run -d --name $$-squid-one --rm -v `pwd`/tests/proxy_list/squid.conf:/etc/squid/conf.d/debian.conf -p 3128:3128 ubuntu/squid:4.13-21.10_edge
docker run -d --name $$-squid-two --rm -v `pwd`/tests/proxy_list/squid.conf:/etc/squid/conf.d/debian.conf -p 3129:3128 ubuntu/squid:4.13-21.10_edge


# So, basic HTTP as env var test
export HTTP_PROXY=http://localhost:3128
export HTTPS_PROXY=http://localhost:3128
pytest tests/proxy_list/test_proxy.py
docker logs $$-squid-one 2>/dev/null|grep one.changedetection.io
if [ $? -ne 0 ]
then
  echo "Did not see a request to one.changedetection.io in the squid logs (while checking env vars HTTP_PROXY/HTTPS_PROXY)"
fi
unset HTTP_PROXY
unset HTTPS_PROXY


# 2nd test actually choose the preferred proxy from proxies.json
cp tests/proxy_list/proxies.json-example ./test-datastore/proxies.json
# Makes a watch use a preferred proxy
pytest tests/proxy_list/test_multiple_proxy.py

# Should be a request in the default "first" squid
docker logs $$-squid-one 2>/dev/null|grep chosen.changedetection.io
if [ $? -ne 0 ]
then
  echo "Did not see a request to chosen.changedetection.io in the squid logs (while checking preferred proxy)"
fi

# And one in the 'second' squid (user selects this as preferred)
docker logs $$-squid-two 2>/dev/null|grep chosen.changedetection.io
if [ $? -ne 0 ]
then
  echo "Did not see a request to chosen.changedetection.io in the squid logs (while checking preferred proxy)"
fi

# @todo - test system override proxy selection and watch defaults, setup a 3rd squid?
docker kill $$-squid-one
docker kill $$-squid-two


