#!/bin/bash

set -eu

source /etc/os-release

curl -sSf 'https://sh.rustup.rs' | runuser -- - piwheels -s -- -y --profile minimal --default-host arm-unknown-linux-gnueabihf

BREAK_SYSTEM_PACKAGES=

if [ $VERSION_ID -gt 11 ]; then
    BREAK_SYSTEM_PACKAGES="--break-system-packages"
fi

hash -r

PYTHON_PACKAGES="pypandoc versioneer kervi scikit-build cython numpy scipy setuptools_rust conan cbor2"

for pkg in $PYTHON_PACKAGES; do
    pip3 install $pkg --extra-index-url https://www.piwheels.org/simple --prefer-binary --ignore-installed $BREAK_SYSTEM_PACKAGES
done

if [ -d piwheels ]; then
    cd piwheels
    git pull
    pip3 uninstall -y piwheels
else
    git clone https://github.com/piwheels/piwheels
    cd piwheels
fi

cp piwheels-slave.service /etc/systemd/system/
systemctl enable piwheels-slave.service

pip3 install .[slave] $BREAK_SYSTEM_PACKAGES

echo "Saving clean shell config baselines"
mkdir -p /home/piwheels/.shell-baselines
useradd -m -s /bin/bash _shellbaseline 2>/dev/null
for f in .bashrc .bash_profile .profile; do
    if [ -f /home/_shellbaseline/$f ]; then
        cp /home/_shellbaseline/$f /home/piwheels/.shell-baselines/$f
    fi
done
userdel -r _shellbaseline 2>/dev/null || true
chown -R piwheels:piwheels /home/piwheels/.shell-baselines

echo "✅ Completed step 3"