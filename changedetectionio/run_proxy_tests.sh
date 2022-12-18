#!/bin/bash

# exit when any command fails
set -e

# Test proxy list handling, starting two squids on different ports
# Each squid adds a different header to the response, which is the main thing we test for.
docker run --network changedet-network -d --name squid-one --hostname squid-one --rm -v `pwd`/tests/proxy_list/squid.conf:/etc/squid/conf.d/debian.conf -p 3128:3128 ubuntu/squid:4.13-21.10_edge
docker run --network changedet-network -d --name squid-two --hostname squid-two --rm -v `pwd`/tests/proxy_list/squid.conf:/etc/squid/conf.d/debian.conf -p 3129:3128 ubuntu/squid:4.13-21.10_edge

## So, basic HTTP as env var test

docker run -e "HTTP_PROXY=http://squid-one:3128" \
  -e "HTTPS_PROXY=http://squid-one:3128" \
  --network changedet-network \
  test-changedetectionio\
  bash -c 'cd changedetectionio && pytest tests/proxy_list/test_proxy.py'

docker logs squid-one 2>/dev/null|grep one.changedetection.io
if [ $? -ne 0 ]
then
  echo "Did not see a request to one.changedetection.io in the squid logs (while checking env vars HTTP_PROXY/HTTPS_PROXY)"
  exit 1
fi

## 2nd test actually choose the preferred proxy from proxies.json

docker run --network changedet-network \
  -v `pwd`/tests/proxy_list/proxies.json-example:/datastore/proxies.json \
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