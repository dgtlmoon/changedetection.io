#!/bin/bash

# exit when any command fails
set -e

# Test proxy list handling, starting two squids on different ports
# Each squid adds a different header to the response, which is the main thing we test for.
docker run --network changedet-network -d --name squid-one --hostname squid-one --rm -v `pwd`/tests/proxy_list/squid.conf:/etc/squid/conf.d/debian.conf ubuntu/squid:4.13-21.10_edge
docker run --network changedet-network -d --name squid-two --hostname squid-two --rm -v `pwd`/tests/proxy_list/squid.conf:/etc/squid/conf.d/debian.conf ubuntu/squid:4.13-21.10_edge


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
