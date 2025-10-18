#!/bin/bash

date -s "$(wget -qSO- --max-redirect=0 google.com 2>&1 | grep -i '^  Date:' | cut -d' ' -f4-)"

apt update

while true; do
    if apt install chrony -y; then
        break
    else
        echo "⚠️ Install failed, fixing and retrying..."
        apt -y install --fix-missing
        apt -y install --fix-broken
    fi
done

systemctl enable --now chrony


while true; do
    if apt install vim byobu -y; then
        break
    else
        echo "⚠️ Install failed, fixing and retrying..."
        apt -y install --fix-missing
        apt -y install --fix-broken
    fi
done

byobu-enable

echo "✅ Completed prestep 0 - now start byobu and run bash deploy_slave_0_upgrade.sh (if upgrading) or bash deploy_slave.sh HOSTNAME MASTER_IP"