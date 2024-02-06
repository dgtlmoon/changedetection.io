#!/bin/bash

# exit when any command fails
set -e
# enable debug
set -x

# Test proxy list handling, starting two squids on different ports
# Each squid adds a different header to the response, which is the main thing we test for.
docker run --network changedet-network -d --name squid-one --hostname squid-one --rm -v `pwd`/tests/proxy_list/squid.conf:/etc/squid/conf.d/debian.conf ubuntu/squid:4.13-21.10_edge
docker run --network changedet-network -d --name squid-two --hostname squid-two --rm -v `pwd`/tests/proxy_list/squid.conf:/etc/squid/conf.d/debian.conf ubuntu/squid:4.13-21.10_edge

# SOCKS5 related - start simple Socks5 proxy server
# SOCKSTEST=xyz should show in the logs of this service to confirm it fetched
docker run --network changedet-network -d --hostname socks5proxy --name socks5proxy -p 1080:1080 -e PROXY_USER=proxy_user123 -e PROXY_PASSWORD=proxy_pass123 serjs/go-socks5-proxy
docker run --network changedet-network -d --hostname socks5proxy-noauth -p 1081:1080 --name socks5proxy-noauth  serjs/go-socks5-proxy

echo "---------------------------------- SOCKS5 -------------------"
# SOCKS5 related - test from proxies.json
docker run --network changedet-network \
  -v `pwd`/tests/proxy_socks5/proxies.json-example:/app/changedetectionio/test-datastore/proxies.json \
  --rm \
  -e "SOCKSTEST=proxiesjson" \
  test-changedetectionio \
  bash -c 'cd changedetectionio && pytest tests/proxy_socks5/test_socks5_proxy_sources.py'

# SOCKS5 related - by manually entering in UI
docker run --network changedet-network \
  --rm \
  -e "SOCKSTEST=manual" \
  test-changedetectionio \
  bash -c 'cd changedetectionio && pytest tests/proxy_socks5/test_socks5_proxy.py'

# SOCKS5 related - test from proxies.json via playwright - NOTE- PLAYWRIGHT DOESNT SUPPORT AUTHENTICATING PROXY
docker run --network changedet-network \
  -e "SOCKSTEST=manual-playwright" \
  -v `pwd`/tests/proxy_socks5/proxies.json-example-noauth:/app/changedetectionio/test-datastore/proxies.json \
  -e "PLAYWRIGHT_DRIVER_URL=ws://sockpuppetbrowser:3000" \
  --rm \
  test-changedetectionio \
  bash -c 'cd changedetectionio && pytest tests/proxy_socks5/test_socks5_proxy_sources.py'

echo "socks5 server logs"
docker logs socks5proxy
echo "----------------------------------"

# Used for configuring a custom proxy URL via the UI
docker run --network changedet-network -d \
  --name squid-custom \
  --hostname squid-custom \
  --rm \
  -v `pwd`/tests/proxy_list/squid-auth.conf:/etc/squid/conf.d/debian.conf \
  -v `pwd`/tests/proxy_list/squid-passwords.txt:/etc/squid3/passwords \
  ubuntu/squid:4.13-21.10_edge


## 2nd test actually choose the preferred proxy from proxies.json
docker run --network changedet-network \
  -v `pwd`/tests/proxy_list/proxies.json-example:/app/changedetectionio/test-datastore/proxies.json \
  test-changedetectionio \
  bash -c 'cd changedetectionio && pytest tests/proxy_list/test_multiple_proxy.py'


## Should be a request in the default "first" squid
docker logs squid-one 2>/dev/null|grep chosen.changedetection.io
if [ $? -ne 0 ]
then
  echo "Did not see a request to chosen.changedetection.io in the squid logs (while checking preferred proxy - squid one)"
  exit 1
fi

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
  bash -c 'cd changedetectionio && pytest tests/proxy_list/test_select_custom_proxy.py'


# Should see a request for one.changedetection.io in there
docker logs squid-custom 2>/dev/null|grep "TCP_TUNNEL.200.*changedetection.io"
if [ $? -ne 0 ]
then
  echo "Did not see a valid request to changedetection.io in the squid logs (while checking preferred proxy - squid two)"
  exit 1
fi

# Test "no-proxy" option
docker run --network changedet-network \
  test-changedetectionio \
  bash -c 'cd changedetectionio && pytest tests/proxy_list/test_noproxy.py'

# We need to handle grep returning 1
set +e
# Check request was never seen in any container
for c in $(echo "squid-one squid-two squid-custom"); do
  echo Checking $c
  docker logs $c &> $c.txt
  grep noproxy $c.txt
  if [ $? -ne 1 ]
  then
    echo "Saw request for noproxy in $c container"
    cat $c.txt
    exit 1
  fi
done


docker kill squid-one squid-two squid-custom
