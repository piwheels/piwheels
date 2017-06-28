# Developing (on any machine)

If you wish to develop on this project, you can do so without a Raspberry Pi. Follow these instructions to get set up. Instructions are provided assuming a Debian-based system, but equivalent installation should work on other systems.

## Requirements

You'll need the required apt packages (or their equivalent on your system):

```bash
sudo apt install dbus python3 python3-dev python3-pip build-essential postgresql -y
```

You'll also need the following pip packages installed:

```
pip3 install pip --upgrade
pip3 install psycopg2
```



## Test suite
