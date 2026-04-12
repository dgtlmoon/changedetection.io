#!/bin/bash

# run some tests and look if the 'custom-browser-search-string=1' connect string appeared in the correct containers

# @todo do it again but with the puppeteer one

# enable debug
set -x
docker network inspect changedet-network >/dev/null 2>&1 || docker network create changedet-network
docker run --network changedet-network -d --hostname selenium  -p 4444:4444 --rm --shm-size="2g"  selenium/standalone-chrome:4

# A extra browser is configured, but we never chose to use it, so it should NOT show in the logs
docker run --rm -e "PLAYWRIGHT_DRIVER_URL=ws://sockpuppetbrowser:3000" --network changedet-network test-changedetectionio  bash -c 'cd changedetectionio;pytest tests/custom_browser_url/test_custom_browser_url.py::test_request_not_via_custom_browser_url'
docker logs sockpuppetbrowser-custom-url &>log-custom.txt
grep 'custom-browser-search-string=1' log-custom.txt
if [ $? -ne 1 ]
then
  echo "Saw a request in 'sockpuppetbrowser-custom-url' container with 'custom-browser-search-string=1' when I should not - log-custom.txt"
  exit 1
fi

docker logs sockpuppetbrowser &>log.txt
grep 'custom-browser-search-string=1' log.txt
if [ $? -ne 1 ]
then
  echo "Saw a request in 'browser' container with 'custom-browser-search-string=1' when I should not"
  exit 1
fi

# Special connect string should appear in the custom-url container, but not in the 'default' one
docker run --rm -e "PLAYWRIGHT_DRIVER_URL=ws://sockpuppetbrowser:3000" --network changedet-network test-changedetectionio  bash -c 'cd changedetectionio;pytest tests/custom_browser_url/test_custom_browser_url.py::test_request_via_custom_browser_url'
docker logs sockpuppetbrowser-custom-url &>log-custom.txt
grep 'custom-browser-search-string=1' log-custom.txt
if [ $? -ne 0 ]
then
  echo "Did not see request in 'sockpuppetbrowser-custom-url' container with 'custom-browser-search-string=1' when I should - log-custom.txt"
  exit 1
fi

docker logs sockpuppetbrowser &>log.txt
grep 'custom-browser-search-string=1' log.txt
if [ $? -ne 1 ]
then
  echo "Saw a request in 'browser' container with 'custom-browser-search-string=1' when I should not"
  exit 1
fi


