#!/bin/bash

set -eu

if [ $# -ne 2 ]; then
    echo "Usage: deploy_slave.sh HOSTNAME MASTER_IP"
    exit 1
fi

echo $1 > /etc/hostname
echo "[slave]" > /etc/piwheels.conf
echo "master=$2" >> /etc/piwheels.conf

DEBIAN_FRONTEND=noninteractive

sed -i 's/#PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config

source /etc/os-release

LIBXLST=libxslt1-dev
LIBGLES=libgles2-mesa-dev
TURBOGEARS=
SOUNDFONT=timgm6mb-soundfont
POSTGRES_SERVER_DEV=postgresql-server-dev-13
PYTHON2_PACKAGES="ipython python-pip python-dev python-scipy python-matplotlib \
    python-pandas python-yaml libpng-dev python-lxml python-cffi python-bs4 \
    python-click python-sqlalchemy python-pil python-pymongo python-django \
    python-flask python-cherrypy python-tornado python-redis python-dateutil \
    python-dnspython python-sphinx python-boto python-gi python-gi-cairo \
    python-cairocffi python-numpy"
QMAKE=qt4-qmake
FPRINT=libfprint-2-dev

if [ $VERSION_ID -eq 10 ]; then
    POSTGRES_SERVER_DEV=postgresql-server-dev-11
    TURBOGEARS=python-turbogears2
    FPRINT=libfprint-dev
elif [ $VERSION_ID -eq 11 ]; then
    PYTHON2_PACKAGES=
    QMAKE=qt5-qmake
fi

apt update
apt -y upgrade
apt -y install vim wget curl ssh-import-id tree byobu htop pkg-config cmake time pandoc \
    gfortran ipython3 git qt5-qmake python3-dev python3-pip python3-apt \
    zlib1g-dev libpq-dev libffi-dev libxml2-dev libhdf5-dev libldap2-dev \
    libjpeg-dev libbluetooth-dev libusb-dev libhidapi-dev libfreetype6-dev \
    liblcms2-dev libzbar-dev libbz2-dev libblas-dev liblapack-dev \
    liblapacke-dev libcurl4-openssl-dev libgmp-dev libgstreamer1.0-dev \
    libsdl2-dev libsdl2-image-dev libsdl2-mixer-dev libsdl2-ttf-dev libssl-dev \
    libsasl2-dev libldap2-dev libavcodec-dev libavformat-dev libswscale-dev \
    libv4l-dev libxvidcore-dev libx264-dev libgtk2.0-dev libgtk-3-dev \
    libatlas-base-dev python3-numpy python3-cairocffi libsdl-image1.2-dev \
    libsdl-mixer1.2-dev libsdl-ttf2.0-dev libsdl1.2-dev libportmidi-dev \
    libtiff5-dev libx11-6 libx11-dev xfonts-base xfonts-100dpi xfonts-75dpi \
    xfonts-cyrillic fluid-soundfont-gm libsystemd-dev libusb-1.0-0-dev \
    libudev-dev libopus-dev libvpx-dev libc-bin libavdevice-dev libadios-dev \
    libavfilter-dev libavutil-dev libcec-dev lsb-release pybind11-dev \
    libsnappy-dev libpcap0.8-dev swig libzmq5 portaudio19-dev libqpdf-dev \
    coinor-libipopt-dev libsrtp2-dev default-libmysqlclient-dev golang \
    libgeos-dev $LIBGLES $LIBXLST $SOUNDFONT $POSTGRES_SERVER_DEV $TURBOGEARS \
    $PYTHON2_PACKAGES $QMAKE libgphoto2-dev libsqlite3-dev libsqlcipher-dev \
    ninja-build $FPRINT libgirepository1.0-dev libfmt-dev

apt purge python3-cryptography python3-yaml -y

pip3 install setuptools --upgrade
pip3 install pip --upgrade
hash -r

pip3 install pypandoc versioneer kervi scikit-build cython numpy scipy \
    setuptools_rust conan cbor2 \
    --upgrade --extra-index-url https://www.piwheels.org/simple --prefer-binary

getent passwd piwheels && userdel -fr piwheels
getent group piwheels || groupadd piwheels
getent passwd piwheels || useradd -g piwheels -m -s /bin/bash piwheels
passwd -d piwheels

curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | runuser -- - piwheels -s -- -y

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
pip3 install .[slave]

fallocate -x -l 1G /swapfile
chmod 0600 /swapfile
mkswap /swapfile
echo "/swapfile none swap x-systemd.makefs,nofail 0 0" >> /etc/fstab
systemctl daemon-reload

rm -f /etc/pip.conf

byobu-enable

reboot
