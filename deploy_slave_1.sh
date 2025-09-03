#!/bin/bash

set -eu

if [ $# -ne 2 ]; then
    echo "Usage: deploy_slave.sh HOSTNAME MASTER_IP"
    exit 1
fi

echo "Setting hostname"
echo $1 > /etc/hostname

echo "[slave]" > /etc/piwheels.conf
echo "master=$2" >> /etc/piwheels.conf

sed -i 's/#PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
rm -f /boot/kernel8.img
rm -f /etc/pip.conf

echo "Creating piwheels user"
getent passwd piwheels && userdel -fr piwheels
getent group piwheels || groupadd piwheels
getent passwd piwheels || useradd -g piwheels -m -s /bin/bash piwheels
passwd -d piwheels > /dev/null

echo "Creating swap file"
fallocate -x -l 1G /swapfile
chmod 0600 /swapfile
mkswap /swapfile
echo "/swapfile none swap x-systemd.makefs,nofail 0 0" >> /etc/fstab
systemctl daemon-reload

echo "✅ Completed step 1"