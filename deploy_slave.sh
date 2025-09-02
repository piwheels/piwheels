#!/bin/bash

set -eu

if [ $# -ne 2 ]; then
    echo "Usage: deploy_slave.sh HOSTNAME MASTER_IP"
    exit 1
fi

bash deploy_slave_1.sh $1 $2
bash deploy_slave_2.sh
bash deploy_slave_3.sh

reboot