#!/bin/bash

source /etc/os-release

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
    output=$(apt -y full-upgrade 2>&1)
    echo "$output"
    if [ $? -eq 0 ]; then
        echo "✅ Upgrade completed successfully"
        break
    fi
    echo "⚠️ Upgrade failed, fixing and retrying..."
    if echo "$output" | grep -q "pkgProblemResolver::Resolve generated breaks"; then
        echo "⚠️ Dependency resolver stuck - force-installing libssl3 to break cycle..."
        apt -y -o Dpkg::Options::="--force-overwrite" install libssl3 libssl-dev 2>/dev/null || true
    fi
    apt -y install --fix-missing
    apt -y install --fix-broken
done

echo "Removing tmpfs /tmp/ mount"
systemctl mask tmp.mount

echo "✅ Completed step 0 - Now run bash deploy_slave.sh"
reboot