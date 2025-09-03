#!/bin/bash

set -eu

DEBIAN_FRONTEND=noninteractive

source /etc/os-release

LIBXLST=libxslt1-dev
LIBGLES=libgles2-mesa-dev
SOUNDFONT=timgm6mb-soundfont
QMAKE=qt5-qmake
FPRINT=libfprint-2-dev
LIBLGPIO=liblgpio-dev
LIBADIOS=libadios-dev
ATLAS_BLAS=libatlas-base-dev
POSTGRES_SERVER_DEV=

if [ $VERSION_ID -eq 11 ]; then
    POSTGRES_SERVER_DEV=postgresql-server-dev-13
    LIBLGPIO=
else if [ $VERSION_ID -eq 12 ]; then
    POSTGRES_SERVER_DEV=postgresql-server-dev-15
else if [ $VERSION_ID -eq 13 ]; then
    POSTGRES_SERVER_DEV=postgresql-server-dev-17
    LIBADIOS=libadios2-common-c-dev
    ATLAS_BLAS=libopenblas-dev
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
    $ATLAS_BLAS python3-numpy python3-cairocffi libsdl-image1.2-dev \
    libsdl-mixer1.2-dev libsdl-ttf2.0-dev libsdl1.2-dev libportmidi-dev \
    libtiff5-dev libx11-6 libx11-dev xfonts-base xfonts-100dpi xfonts-75dpi \
    xfonts-cyrillic fluid-soundfont-gm libsystemd-dev libusb-1.0-0-dev \
    libudev-dev libopus-dev libvpx-dev libc-bin libavdevice-dev $LIBADIOS \
    libavfilter-dev libavutil-dev libcec-dev lsb-release pybind11-dev \
    libsnappy-dev libpcap0.8-dev swig libzmq5 portaudio19-dev libqpdf-dev \
    coinor-libipopt-dev libsrtp2-dev default-libmysqlclient-dev golang \
    libgeos-dev $LIBGLES $LIBXLST $SOUNDFONT $POSTGRES_SERVER_DEV \
    $QMAKE $FPRINT libgphoto2-dev $LIBLGPIO libsqlite3-dev libsqlcipher-dev \
    ninja-build libgirepository1.0-dev libfmt-dev libopenblas-dev

apt purge python3-cryptography python3-yaml -y

