#!/bin/bash

set -eu

source /etc/os-release

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

if [ $VERSION_ID -ge 13 ]; then
    echo "Removing tmpfs /tmp/ mount"
    systemctl mask tmp.mount
    sed -i -e 's/-$/0/' /etc/tmpfiles.d/tmp.conf
fi

echo "✅ Completed step 1"