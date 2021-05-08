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
