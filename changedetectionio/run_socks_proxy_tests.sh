#!/bin/bash

# exit when any command fails
set -e
# enable debug
set -x

docker network inspect changedet-network >/dev/null 2>&1 || docker network create changedet-network

# SOCKS5 related - start simple Socks5 proxy server
# SOCKSTEST=xyz should show in the logs of this service to confirm it fetched
docker run --network changedet-network -d --hostname socks5proxy --rm  --name socks5proxy -p 1080:1080 -e PROXY_USER=proxy_user123 -e PROXY_PASSWORD=proxy_pass123 serjs/go-socks5-proxy
docker run --network changedet-network -d --hostname socks5proxy-noauth --rm -p 1081:1080 --name socks5proxy-noauth -e REQUIRE_AUTH=false serjs/go-socks5-proxy

echo "---------------------------------- SOCKS5 -------------------"
# SOCKS5 related - test from proxies.json
docker run --network changedet-network \
  -v `pwd`/tests/proxy_socks5/proxies.json-example:/app/changedetectionio/test-datastore/proxies.json \
  --rm \
  -e "FLASK_SERVER_NAME=cdio" \
  --hostname cdio \
  -e "SOCKSTEST=proxiesjson" \
  test-changedetectionio \
  bash -c 'cd changedetectionio && pytest --live-server-host=0.0.0.0 --live-server-port=5004  -s tests/proxy_socks5/test_socks5_proxy_sources.py'

# SOCKS5 related - by manually entering in UI
docker run --network changedet-network \
  --rm \
  -e "FLASK_SERVER_NAME=cdio" \
  --hostname cdio \
  -e "SOCKSTEST=manual" \
  test-changedetectionio \
  bash -c 'cd changedetectionio && pytest --live-server-host=0.0.0.0 --live-server-port=5004  -s tests/proxy_socks5/test_socks5_proxy.py'

# SOCKS5 related - test from proxies.json via playwright - NOTE- PLAYWRIGHT DOESNT SUPPORT AUTHENTICATING PROXY
docker run --network changedet-network \
  -e "SOCKSTEST=manual-playwright" \
  --hostname cdio \
  -e "FLASK_SERVER_NAME=cdio" \
  -v `pwd`/tests/proxy_socks5/proxies.json-example-noauth:/app/changedetectionio/test-datastore/proxies.json \
  -e "PLAYWRIGHT_DRIVER_URL=ws://sockpuppetbrowser:3000" \
  --rm \
  test-changedetectionio \
  bash -c 'cd changedetectionio && pytest --live-server-host=0.0.0.0 --live-server-port=5004  -s tests/proxy_socks5/test_socks5_proxy_sources.py'

echo "socks5 server logs"
docker logs socks5proxy
echo "----------------------------------"

docker kill socks5proxy socks5proxy-noauth
