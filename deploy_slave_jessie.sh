#!/bin/bash

set -eu

rm -f /etc/pip.conf
apt update
apt -y upgrade
apt -y install python3-zmq python-dev python3-dev zlib1g-dev libpng12-dev \
    libffi-dev libxml2-dev libgmp-dev libhdf5-dev libldap2-dev libjpeg-dev \
    libusb-dev libhidapi-dev libfreetype6-dev liblcms2-dev libzbar-dev libbz2-dev \
    libblas-dev liblapack-dev liblapacke-dev libgles2-mesa-dev libgles1-mesa-dev \
    libgstreamer1.0-dev libsdl2-dev libssl-dev libsasl2-dev libldap2-dev \
    python-numpy python3-numpy python-scipy python3-scipy python-matplotlib \
    python3-matplotlib python-pandas python3-pandas cython cython3 \
    python-yaml python3-yaml python-lxml python3-lxml python-cffi \
    python3-cffi python-bs4 python3-bs4 python-click \
    python3-click python-sqlalchemy python3-sqlalchemy python-pil python3-pil \
    python-pymongo python3-pymongo python-django python3-django python-flask \
    python3-flask python-turbogears python-cherrypy python3-cherrypy3 \
    python-tornado python3-tornado python-pip python3-pip \
    python-redis python3-redis python-dateutil python3-dateutil \
    python-dnspython python3-dnspython python-sphinx python3-sphinx \
    python-boto python3-boto python-gi python3-gi python-gi-cairo \
    python3-gi-cairo python-cairocffi python3-cairocffi \
    ipython ipython3 git tree byobu htop pkg-config gfortran cmake \
    qt4-qmake qt5-qmake
pip3 install pip --upgrade
pip3 install pypandoc
pip3 install versioneer
pip3 install kervi
getent passwd piwheels && userdel -fr piwheels
getent group piwheels || groupadd piwheels
getent passwd piwheels || useradd -g piwheels -m -s /bin/bash piwheels
passwd -d piwheels
if [ -d piwheels ]; then
  cd piwheels
  git pull
  pip uninstall -y piwheels
else
  git clone https://github.com/bennuttall/piwheels
  cd piwheels
  git checkout separate-tasks
fi
pip3 install .
if ! grep swapfile /etc/rc.local >/dev/null; then
    dd if=/dev/zero of=/swapfile bs=1M count=1024
    chmod 0600 /swapfile
    sed -i -e '$i\
chmod 0600 /swapfile\
losetup /dev/loop0 /swapfile\
mkswap /dev/loop0\
swapon /dev/loop0\
' /etc/rc.local
fi
