#!/bin/bash

set -eu

bash deploy_slave_1.sh
bash deploy_slave_2.sh
bash deploy_slave_3.sh

reboot