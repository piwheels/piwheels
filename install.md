# Installation on a Raspberry Pi

Installation instructions (all as root), based on Raspbian Jessie Lite (or Mythic Beasts' Raspbian server image).

First, set your timezone correctly:

```bash
dpkg-reconfigure tzdata
```

Install the required Debian packages:

```bash
apt install dbus apache2 python3 python3-dev python3-pip build-essential postgresql -y
```

Upgrade pip and install the required pip packages:

```
pip3 install pip --upgrade
pip3 install psycopg2 gpiozero
```

Install the Apache `speling` module:

```bash
a2enmod speling
```

Set up a vhost by editing `/etc/apache2/sites-available/000-default.conf`, for example:

```
<VirtualHost *:80>
	ServerName www.piwheels.hostedpi.com
	ServerAdmin webmaster@localhost
	DocumentRoot /home/piwheels/www

	ErrorLog ${APACHE_LOG_DIR}/error.log
	CustomLog ${APACHE_LOG_DIR}/access.log combined

    <Directory /home/piwheels/www/>
        Order allow,deny
        Allow from all
        Allowoverride all
        Require all granted
    </Directory>
</VirtualHost>
```

Add the following to `/etc/apache2/apache2.conf`:

```
CheckSpelling On
CheckCaseOnly On
```

Restart Apache:

```bash
service apache2 restart
```

Switch to the postgres user and create a `piwheels` user (follow the interactive prompt to give the user a password):

```bash
su postgres
createuser piwheels -P --interactive
```

Create a database, and load the database setup script:

```bash
psql -c "create database piwheels"
cat piwheels.sql | psql piwheels
```

Create an environment variables file in `~/.piwheels_env_vars`:

```bash
export PW_DB=piwheels
export PW_USER=piwheels
export PW_HOST=localhost
export PW_PASS=piwheels
```

(change details as appropriate)

Ensure this is loaded in your bash profile, e.g. add to your `.bashrc`:

```bash
if [ -f ~/.piwheels_env_vars ]; then
    . ~/.piwheels_env_vars
fi
```
