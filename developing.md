# Developing (on any machine)

If you wish to develop on this project, you can do so without a Raspberry Pi. Follow these instructions to get set up. Instructions are provided assuming a Debian-based system, but equivalent installation should work on other systems.

You should start by git cloning this repository:

```bash
git clone https://github.com/bennuttall/piwheels
```

## Basic requirements

You'll need the required apt packages (or their equivalent on your system):

```bash
sudo apt install python3 python3-dev python3-pip build-essential postgresql -y
```

You'll also need the following pip packages installed:

```bash
pip3 install pip --upgrade
pip3 install psycopg2 gpiozero pytest
```

## Test suite

Enter the piwheels directory:

```bash
cd piwheels/piwheels
```

Run the test runner bash script:

```bash
./test_runner.sh
```

Note that some tests require an internet connection. If you are online, these tests will be run. If you are offline, or PyPI is unreachable, the tests will be skipped and a message will be shown.

## Apache

If you're only working with the build scripts or the database, you don't need to install Apache, and if you are editing the web pages you may simply wish to save HTML output to a file for testing purposes. However, if you do want to generate web pages for the project and have an actual web server serve them, you can follow the following guide.

Install Apache:

```bash
apt install apache2
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
