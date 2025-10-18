# Docker setup

You can set up and run a piwheels instance for local development within Docker containers with:

```console
docker compose build
docker compose up master web
```

Then once the master is running, you should see the piwheels homepage at http://localhost:8080

It starts building up the database from the very beginning of PyPI history, and there's some sketchy
records keeping to deal with, see [these notes](https://github.com/piwheels/piwheels/blob/6e6f41ffd876e6d94247051ce102f26d7e7035bf/piwheels/pypi.py#L108),
so it takes a while before you really see anything.

## Restore DB from live

Alternatively, we can restore the DB from a selective data-only DB dump from the live DB. Download
the CSVs from piwheelsdb:

```console
scp piwheelsdb:/tmp/csv/\*.csv docker/csv/
```

The `initdb` service must have been run on the same version as live before restoring from live.

Make sure the `db` service is up but the master is not running, and run one of the following
commands.

For packages and versions only, use `db-restore-minimal.sql`:

```console
docker exec -u postgres -w /app/docker piwheels-db psql piwheels -f db-restore-minimal.sql
```

For builds, files and dependencies too, use `db-restore.sql`:

```console
docker exec -u postgres -w /app/docker piwheels-db psql piwheels -f db-restore.sql
```

## psql

Access the database with psql:

```console
docker exec -it piwheels-db bash -c "su - postgres -c 'psql piwheels'"
```

## Tests

Run tests on Debian Bookworm (Python 3.11) with:
 
```console
docker compose build test-bookworm && docker compose run --rm test-bookworm
```

And on Debian Bullseye (Python 3.9) with:
 
```console
docker compose build test-bullseye && docker compose run --rm test-bullseye
```

And on Debian Trixie (Python 3.13) with:
 
```console
docker compose build test-trixie && docker compose run --rm test-trixie
```

## Shell into a container

Shell into e.g. the master:

```console
docker compose exec master bash
```

This allows you to view e.g. the output directory:

```console
$ docker compose exec master bash                                                     
root@b405ff1d98dc:/home/piwheels# ls www
```

This also makes it possible to run a command like `piw-rebuild`:

```console
$ docker compose exec master bash                                       
root@b405ff1d98dc:/home/piwheels# su - piwheels
piwheels@b405ff1d98dc:~$ piw-rebuild project gpiozero
```

Alternatively:

```console
docker compose exec master bash -c "piw-rebuild project gpiozero"
```

## Stop containers

Stop containers with:

```console
docker compose down
```

## Tear it down

Tear a container (e.g. the database) down with:

```console
docker compose down db --volumes --remove-orphans
```

Tear it all down with:

```console
docker compose down --volumes --remove-orphans
```

## Test a database migration

Start by bringing everything up from the `main` branch, and initialising/restoring the database as
required, then stop the master service:

```console
docker compose down master
```

Switch to the feature branch containing the migration:

```console
git switch new-feature
```

Make sure the database service is running:

```console
docker compose up db
```

Rebuild `initdb` and bring it back up to attempt the migration.

```console
docker compose up --build initdb
```

Once successful, rebuild `master` and bring it back up:

```console
docker compose up --build master
```

## Import a set of wheels

Place some wheels in `docker/wheels` and run:

```console
docker exec -u piwheels piwheels-master /app/docker/import-wheels.sh
```