#!/bin/bash

set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
    CREATE USER piwheels WITH PASSWORD 'piwheels';
    CREATE DATABASE piwheels OWNER piwheels;
    GRANT ALL PRIVILEGES ON DATABASE piwheels TO piwheels;
EOSQL