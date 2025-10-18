#!/bin/bash

export DEBIAN_FRONTEND=noninteractive

apt update

while true; do
    if apt -y full-upgrade; then
        echo "✅ Upgrade completed successfully"
        break
    else
        echo "⚠️ Upgrade failed, fixing and retrying..."
        apt -y install --fix-missing
        apt -y install --fix-broken
    fi
done

while true; do
    if apt autoremove --purge -y; then
        echo "✅ Upgrade completed successfully"
        break
    else
        echo "⚠️ Upgrade failed, fixing and retrying..."
        apt -y install --fix-missing
        apt -y install --fix-broken
    fi
done

sed -i 's/bookworm/trixie/g' /etc/apt/sources.list
sed -i 's/bookworm/trixie/g' /etc/apt/sources.list.d/raspi.list

apt update

while true; do
    if apt -y full-upgrade; then
        echo "✅ Upgrade completed successfully"
        break
    else
        echo "⚠️ Upgrade failed, fixing and retrying..."
        apt -y install --fix-missing
        apt -y install --fix-broken
    fi
done

echo "✅ Completed step 0 - Now run bash deploy_slave.sh HOSTNAME MASTER_IP"