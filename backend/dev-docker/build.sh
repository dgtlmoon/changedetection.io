#!/bin/bash
docker stop tss-node
docker rm tss-node
docker build -t tss-node .

