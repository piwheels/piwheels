#!/bin/bash

set -eu

source /etc/os-release
if [ $VERSION_ID -lt 9 ]; then
    LIBPNG_DEV=libpng12-dev
    LIBMYSQL_DEV=libmysqlclient-dev
    POSTGRES_SERVER_DEV=postgresql-server-dev-9.4
else
    LIBPNG_DEV=libpng-dev
    LIBMYSQL_DEV=libmariadbclient-dev
    POSTGRES_SERVER_DEV=postgresql-server-dev-9.6
fi

apt update
apt -y upgrade
apt -y install python3-zmq python-dev python3-dev zlib1g-dev $LIBPNG_DEV \
    $LIBMYSQL_DEV libpq-dev libffi-dev libxml2-dev libxslt-dev libgmp-dev \
    libhdf5-dev libldap2-dev libjpeg-dev libbluetooth-dev libusb-dev \
    libhidapi-dev libfreetype6-dev liblcms2-dev libzbar-dev libbz2-dev \
    libblas-dev liblapack-dev liblapacke-dev libgles2-mesa-dev libcurl4-openssl-dev \
    libgles1-mesa-dev libgstreamer1.0-dev libsdl2-dev libsdl2-image-dev \
    libsdl2-mixer-dev libsdl2-ttf-dev libssl-dev libsasl2-dev \
    libldap2-dev libavcodec-dev libavformat-dev libswscale-dev libv4l-dev \
    libxvidcore-dev libx264-dev libgtk2.0-dev libgtk-3-dev libatlas-base-dev \
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
    qt4-qmake qt5-qmake libsdl-image1.2-dev libsdl-mixer1.2-dev \
    libsdl-ttf2.0-dev libsdl1.2-dev libportmidi-dev libtiff5-dev \
    libx11-6 libx11-dev xfonts-base xfonts-100dpi xfonts-75dpi \
    xfonts-cyrillic fluid-soundfont-gm musescore-soundfont-gm libsystemd-dev \
    $POSTGRES_SERVER_DEV
if [ $VERSION_ID -lt 9 ]; then
    pip3 install pip --upgrade
fi
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
fi
cp piwheels-slave.service /etc/systemd/system/
systemctl enable piwheels-slave.service
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

rm -f /etc/pip.conf
