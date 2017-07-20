# Installation on a Raspberry Pi

Installation instructions (all as root), based on Raspbian Jessie Lite (or Mythic Beasts' Raspbian server image).

First, set your timezone correctly:

```bash
dpkg-reconfigure tzdata
```

Install the required Debian packages:

```bash
apt install apache2 python3 python3-dev python3-pip build-essential postgresql -y
```

Upgrade pip and install the required pip packages:

```
pip3 install pip --upgrade
pip3 install psycopg2
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
export PW_NUM=1  # optional node number
```

(change details as appropriate)

Ensure this is loaded in your bash profile, e.g. add to your `.bashrc`:

```bash
if [ -f ~/.piwheels_env_vars ]; then
    . ~/.piwheels_env_vars
fi
```

## Operation

In order for piwheels to be fully operational, the following components need to be running:

- Update package list
	  - [update_package_list.py](piwheels/update_package_versions.py) should be continuously running to update the list of packages and versions on PyPI.
- Build new packages
		- [main.py](piwheels/main.py) should be running continuously to work through the build queue building any unattempted packages
- Web index
    - [web_index.py](piwheels/web_index.py) should be running every minute in cron

One way of managing this is to install `byobu` and launch new windows for each of the two continuous scripts and just run the web index script minutely in cron.
