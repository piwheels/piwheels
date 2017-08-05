#!/bin/bash

set -eu

apt update
apt -y upgrade
apt -y install python3-zmq python-dev python3-dev zlib1g-dev libpng12-dev \
    libffi-dev libxml2-dev libgmp-dev libhdf5-dev libldap2-dev libjpeg-dev \
    libfreetype6-dev liblcms2-dev libzbar-dev libbz2-dev python-numpy \
    python3-numpy python-scipy python3-scipy python-matplotlib \
    python3-matplotlib python-pandas python3-pandas cython cython3 \
    python-yaml python3-yaml python-lxml python3-lxml python-cffi \
    python3-cffi python-bs4 python3-bs4 python-click \
    python3-click python-sqlalchemy python3-sqlalchemy python-pil python3-pil \
    python-pymongo python3-pymongo python-django python3-django python-flask \
    python3-flask python-turbogears python-cherrypy python3-cherrypy3 \
    python-qt4 python3-pyqt4 python-pyqt5 python3-pyqt5 python-pyside \
    python3-pyside python-tornado python3-tornado python-pip python3-pip \
    python-redis python3-redis python-dateutil python3-dateutil \
    python-dnspython python3-dnspython python-sphinx python3-sphinx \
    python-boto python3-boto python-gi python3-gi python-gi-cairo \
    python3-gi-cairo python-cairocffi python3-cairocffi \
    ipython ipython3 git tree byobu htop pkg-config
pip3 install pip --upgrade
pip3 install pypandoc
pip3 install versioneer
pip3 install kervi
getent passwd piwheels && userdel -fr piwheels
getent group piwheels || groupadd piwheels
getent passwd piwheels || useradd -g piwheels -m piwheels
passwd -d piwheels
git clone https://github.com/bennuttall/piwheels
cd piwheels
git remote add waveform https://github.com/waveform80/piwheels
git fetch --all
git checkout cli
pip install .
if ! grep swapfile /etc/rc.local >/dev/null; then
    dd if=/dev/zero of=/swapfile bs=1M count=512
    chmod 0600 /swapfile
    cat << EOF >> /etc/rc.local
chmod 0600 /swapfile
losetup /dev/loop0 /swapfile
mkswap /dev/loop0
swapon /dev/loop0
EOF
fi
