#!/bin/bash

# exit when any command fails
set -e
# enable debug
set -x

# Test proxy list handling, starting two squids on different ports
# Each squid adds a different header to the response, which is the main thing we test for.
docker run --network changedet-network -d --name squid-one --hostname squid-one --rm -v `pwd`/tests/proxy_list/squid.conf:/etc/squid/conf.d/debian.conf ubuntu/squid:4.13-21.10_edge
docker run --network changedet-network -d --name squid-two --hostname squid-two --rm -v `pwd`/tests/proxy_list/squid.conf:/etc/squid/conf.d/debian.conf ubuntu/squid:4.13-21.10_edge

# Used for configuring a custom proxy URL via the UI - with username+password auth
docker run --network changedet-network -d \
  --name squid-custom \
  --hostname squid-custom \
  --rm \
  -v `pwd`/tests/proxy_list/squid-auth.conf:/etc/squid/conf.d/debian.conf \
  -v `pwd`/tests/proxy_list/squid-passwords.txt:/etc/squid3/passwords \
  ubuntu/squid:4.13-21.10_edge

sleep 5
## 2nd test actually choose the preferred proxy from proxies.json
# This will force a request via "proxy-two"
docker run --network changedet-network \
  -v `pwd`/tests/proxy_list/proxies.json-example:/tmp/proxies.json \
  test-changedetectionio \
  bash -c 'cd changedetectionio && pytest -s tests/proxy_list/test_multiple_proxy.py --datastore-path /tmp'

set +e
echo "- Looking for chosen.changedetection.io request in squid-one - it should NOT be here"
docker logs squid-one 2>/dev/null|grep chosen.changedetection.io
if [ $? -ne 1 ]
then
  echo "Saw a request to chosen.changedetection.io in the squid logs (while checking preferred proxy - squid one) WHEN I SHOULD NOT"
  exit 1
fi

set -e
echo "- Looking for chosen.changedetection.io request in squid-two"
# And one in the 'second' squid (user selects this as preferred)
docker logs squid-two 2>/dev/null|grep chosen.changedetection.io
if [ $? -ne 0 ]
then
  echo "Did not see a request to chosen.changedetection.io in the squid logs (while checking preferred proxy - squid two)"
  exit 1
fi

# Test the UI configurable proxies
docker run --network changedet-network \
  test-changedetectionio \
  bash -c 'cd changedetectionio && pytest tests/proxy_list/test_select_custom_proxy.py --datastore-path /tmp'

# Same again via Puppeteer fast, proxy username+password goes in via page.authenticate() not the URL
docker run --network changedet-network \
  test-changedetectionio \
  bash -c 'cd changedetectionio && FAST_PUPPETEER_CHROME_FETCHER=1 PLAYWRIGHT_DRIVER_URL=ws://sockpuppetbrowser:3000 pytest tests/proxy_list/test_select_custom_proxy.py --datastore-path /tmp'

# Give squid proxies a moment to flush their logs
sleep 2

# Should see a request for one.changedetection.io in there
echo "- Looking for .changedetection.io request in squid-custom"
docker logs squid-custom 2>/dev/null|grep "TCP_TUNNEL.200.*changedetection.io"
if [ $? -ne 0 ]
then
  echo "Did not see a valid request to changedetection.io in the squid logs (while checking preferred proxy - squid two)"
  exit 1
fi

# Test "no-proxy" option
docker run --network changedet-network \
  test-changedetectionio \
  bash -c 'cd changedetectionio && pytest tests/proxy_list/test_noproxy.py --datastore-path /tmp'

# Give squid proxies a moment to flush their logs
sleep 2

# We need to handle grep returning 1
set +e
# Check request was never seen in any container
for c in $(echo "squid-one squid-two squid-custom"); do
  echo ....Checking $c
  docker logs $c &> $c.txt
  grep noproxy $c.txt
  if [ $? -ne 1 ]
  then
    echo "Saw request for noproxy in $c container"
    cat $c.txt
    exit 1
  fi
done

# Test the proxy scanner of a watch ("Check/Scan all" on its edit page): its page fetched through every proxy.
# The page is the test's own server, which the squids (and the browser) reach as "cdio", so the test can make it
# refuse the second scan. proxies.json-scanner: the two squids and a proxy with nothing listening.
#
# "set -e" again from here to the end of the script. It was switched off above for the greps that are expected
# to find nothing and never switched back on, so a test that failed after that point did not fail the run
# (tests/proxy_list/test_proxy_noconnect.py did, for some time).
set -e
# Requests
docker run --network changedet-network --hostname cdio -e "FLASK_SERVER_NAME=cdio" \
  -v `pwd`/tests/proxy_list/proxies.json-scanner:/tmp/proxies.json \
  test-changedetectionio \
  bash -c 'cd changedetectionio && pytest --live-server-host=0.0.0.0 --live-server-port=5004 tests/proxy_list/test_proxy_scanner.py --datastore-path /tmp'

# Puppeteer fast: a scan with a browser fetcher
docker run --network changedet-network --hostname cdio -e "FLASK_SERVER_NAME=cdio" \
  -v `pwd`/tests/proxy_list/proxies.json-scanner:/tmp/proxies.json \
  test-changedetectionio \
  bash -c 'cd changedetectionio && FAST_PUPPETEER_CHROME_FETCHER=1 PLAYWRIGHT_DRIVER_URL=ws://sockpuppetbrowser:3000 pytest --live-server-host=0.0.0.0 --live-server-port=5004 tests/proxy_list/test_proxy_scanner.py --datastore-path /tmp'

# Give squid proxies a moment to flush their logs
sleep 2

# Each squid was scanned through: it saw the page fetched (first scan) and refused (second scan).
# squid leaves the query string out of its log, so this goes by the address and the status.
for c in squid-one squid-two; do
  echo "- Looking for the proxy scanner's two scans in $c"
  docker logs $c 2>/dev/null | grep "/200 .*cdio:5004/test-endpoint"
  docker logs $c 2>/dev/null | grep "/403 .*cdio:5004/test-endpoint"
done

echo "docker ps output"
docker ps

docker kill squid-one squid-two squid-custom

# Test that the UI is returning the correct error message when a proxy is not available

# Requests
docker run --network changedet-network \
  test-changedetectionio \
  bash -c 'cd changedetectionio && pytest tests/proxy_list/test_proxy_noconnect.py --datastore-path /tmp'

# Playwright
docker run --network changedet-network \
  test-changedetectionio \
  bash -c 'cd changedetectionio && PLAYWRIGHT_DRIVER_URL=ws://sockpuppetbrowser:3000 pytest tests/proxy_list/test_proxy_noconnect.py --datastore-path /tmp'

# Puppeteer fast
docker run --network changedet-network \
  test-changedetectionio \
  bash -c 'cd changedetectionio && FAST_PUPPETEER_CHROME_FETCHER=1 PLAYWRIGHT_DRIVER_URL=ws://sockpuppetbrowser:3000 pytest tests/proxy_list/test_proxy_noconnect.py --datastore-path /tmp'

# Selenium
docker run --network changedet-network \
  test-changedetectionio \
  bash -c 'cd changedetectionio && WEBDRIVER_URL=http://selenium:4444/wd/hub pytest tests/proxy_list/test_proxy_noconnect.py --datastore-path /tmp'
