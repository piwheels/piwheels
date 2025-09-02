#!/bin/bash

set -eu

source /etc/os-release

curl -sSf 'https://sh.rustup.rs' | runuser -- - piwheels -s -- -y --profile minimal --default-host arm-unknown-linux-gnueabihf

if [ $VERSION_ID -eq 11 ]; then
    pip3 install setuptools --upgrade
    pip3 install pip --upgrade
else
    pip3 install setuptools --upgrade --break-system-packages
    pip3 install pip --upgrade --break-system-packages
fi

hash -r

PYTHON_PACKAGES="pypandoc versioneer kervi scikit-build cython numpy scipy setuptools_rust conan cbor2"

if [ $VERSION_ID -eq 11 ]; then
    pip3 install $PYTHON_PACKAGES \
        --upgrade --extra-index-url https://www.piwheels.org/simple --prefer-binary
else
    pip3 install $PYTHON_PACKAGES \
        --upgrade --extra-index-url https://www.piwheels.org/simple --prefer-binary --break-system-packages
fi

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

if [ $VERSION_ID -eq 11 ]; then
    pip3 install .[slave]
else
    pip3 install .[slave] --break-system-packages
fi