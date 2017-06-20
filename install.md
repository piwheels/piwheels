# Installation

Installation instructions (all as root), based on Raspbian Jessie Lite.

First, install the required Debian packages:

```bash
apt install dbus apache2 python3 python3-dev python3-pip build-essential postgresql -y
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

Switch to the postgres user and load the database setup script:

```bash
su postgres
cat piwheels.sql | psql piwheels
```
