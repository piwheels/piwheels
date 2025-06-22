#!/bin/bash

for f in /app/docker/wheels/*.whl;
    do piw-import $f --abi cp311 -y;
done