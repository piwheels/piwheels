#!/bin/bash

set -eu

source /etc/os-release

curl -sSf 'https://sh.rustup.rs' | runuser -- - piwheels -s -- -y --profile minimal --default-host arm-unknown-linux-gnueabihf

if [ $VERSION_ID -gt 11 ]; then
    break_system_packages="--break-system-packages"
else
    break_system_packages=""
fi

hash -r

PYTHON_PACKAGES="pypandoc versioneer kervi scikit-build cython numpy scipy setuptools_rust conan cbor2"

for pkg in $PYTHON_PACKAGES; do
    pip3 install $pkg --no --extra-index-url https://www.piwheels.org/simple --prefer-binary --exists-action i $break_system_packages
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

pip3 install .[slave] $break_system_packages