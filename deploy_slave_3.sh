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

echo "✅ Completed step 3"