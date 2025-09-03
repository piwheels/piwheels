#!/bin/bash

set -eu

date -s "$(wget -qSO- --max-redirect=0 google.com 2>&1 | grep -i '^  Date:' | cut -d' ' -f4-)"

apt update
apt install chrony -y
systemctl enable --now chrony
apt install vim byobu -y
byobu-enable

echo "Now start byobu and run bash deploy_slave_0_upgrade.sh"