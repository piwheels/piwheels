# Web

FROM debian:bookworm AS piwheels-web

RUN apt update && apt install apache2 -y

COPY ./docker/apache/000-default.conf /etc/apache2/sites-available/000-default.conf

RUN a2enmod rewrite && service apache2 restart
RUN echo "ServerName localhost" > /etc/apache2/conf-available/servername.conf && a2enconf servername

EXPOSE 80

CMD ["apachectl", "-D", "FOREGROUND"]

# Bookworm with python

FROM debian:bookworm AS bookworm-python

RUN apt update && \
    apt install -y python3 python3-pip python3-setuptools python3-wheel python3-simplejson

# Docs

FROM bookworm-python AS piwheels-docs

RUN apt install -y python3-sphinx python3-sphinx-rtd-theme inkscape

# piwheels base

FROM bookworm-python AS piwheels-bookworm

RUN apt install -y python3 python3-pip python3-setuptools python3-wheel python3-packaging \
    python3-configargparse python3-zmq python3-voluptuous python3-cbor2 python3-dateutil \
    python3-apt python3-requests python3-sqlalchemy python3-psycopg2 python3-chameleon \
    python3-simplejson python3-urwid python3-pygeoip

COPY setup.cfg setup.py /app/
COPY piwheels/ /app/piwheels/
WORKDIR /app

RUN pip3 install . lars --break-system-packages --no-deps

# Bookworm with piwheels user

FROM piwheels-bookworm AS bookworm-piwheels-user

RUN addgroup --system piwheels && \
    adduser --system --ingroup piwheels --shell /bin/bash --home /home/piwheels piwheels && \
    mkdir -p /home/piwheels && \
    chown piwheels:piwheels /home/piwheels

# Master image
    
FROM bookworm-piwheels-user AS piwheels-master

RUN mkdir -p /home/piwheels/www/simple && chown -R piwheels:piwheels /home/piwheels/www

USER piwheels
WORKDIR /home/piwheels

# Bookworm test image

FROM bookworm-piwheels-user AS test-bookworm

RUN apt install -y python3-pytest python3-pytest-cov  python3-bs4

USER piwheels
WORKDIR /app

# Bullseye test image

FROM debian:bullseye AS test-bullseye

RUN apt update && \
    apt install -y python3 python3-pip python3-setuptools python3-wheel python3-packaging \
    python3-configargparse python3-zmq python3-voluptuous python3-cbor2 python3-dateutil \
    python3-pytest python3-pytest-cov python3-apt python3-requests python3-psycopg2 \
    python3-chameleon python3-simplejson python3-pygeoip python3-bs4

COPY setup.cfg setup.py /app/
COPY piwheels/ /app/piwheels/
WORKDIR /app

RUN addgroup --system piwheels && \
    adduser --system --ingroup piwheels --shell /bin/bash --home /home/piwheels piwheels && \
    mkdir -p /home/piwheels && \
    chown piwheels:piwheels /home/piwheels

RUN pip3 install . lars sqlalchemy==1.4 --no-deps
    
USER piwheels
WORKDIR /app

# Trixie test image

FROM debian:trixie AS test-trixie

RUN apt update && \
    apt install -y adduser python3 python3-pip python3-setuptools python3-wheel python3-packaging \
    python3-configargparse python3-zmq python3-voluptuous python3-cbor2 python3-dateutil \
    python3-pytest python3-pytest-cov python3-apt python3-requests python3-psycopg2 \
    python3-chameleon python3-simplejson python3-bs4

COPY setup.cfg setup.py /app/
COPY piwheels/ /app/piwheels/
WORKDIR /app

RUN addgroup --system piwheels && \
    adduser --system --ingroup piwheels --shell /bin/bash --home /home/piwheels piwheels && \
    mkdir -p /home/piwheels && \
    chown piwheels:piwheels /home/piwheels

RUN pip3 install . lars pygeoip sqlalchemy==1.4 --break-system-packages --no-deps
    
USER piwheels
WORKDIR /app