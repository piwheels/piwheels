#!/bin/bash

set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
    CREATE USER piwheels WITH PASSWORD 'piwheels';
    CREATE DATABASE piwheels OWNER piwheels;
    GRANT ALL PRIVILEGES ON DATABASE piwheels TO piwheels;
    CREATE USER piwsuper WITH SUPERUSER PASSWORD 'foobar';
    CREATE DATABASE piwtest OWNER piwsuper;
    GRANT ALL PRIVILEGES ON DATABASE piwtest TO piwheels;
EOSQL