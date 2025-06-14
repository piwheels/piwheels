# Docker setup

You can set up piwheels for local development within Docker containers with:

```console
docker compose build
docker compose up
```

Then once the master is running, you should see the piwheels homepage at http://localhost:8080

It starts building up the database from the very beginning of PyPI history, and there's some sketchy
records keeping to deal with, see [these notes](https://github.com/piwheels/piwheels/blob/6e6f41ffd876e6d94247051ce102f26d7e7035bf/piwheels/pypi.py#L108),
so it takes a while before you really see anything.

## Restore DB from live

Alternatively, we can restore the DB from a selective data-only DB dump from the live DB. Download
the CSVs from piwheelsdb:

```console
scp piwheelsdb:/tmp/csv/"*".csv docker/csv/
```

Make sure the `db` service is up but the master is not running, and run:

```console
docker exec -u postgres -w /app/docker piwheels-db psql piwheels -f db-restore.sql
```

This will populate the database with packages, versions, builds etc.

## Tests

Run tests with:
 
```console
docker compose --profile test run --rm test
```