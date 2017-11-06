# piwheels

piwheels is Python package repository providing [wheels](https://packaging.python.org/wheel_egg/)
(pre-built binaries) for the ARMv6 and ARMv7 architectures used by
[Raspberry Pi](https://www.raspberrypi.org/).

This repository contains the source code for building armv6 and armv7 wheels
for packages found on [PyPI](https://pypi.python.org/pypi), and the project's
future will be discussed in [GitHub issues](https://github.com/bennuttall/piwheels/issues).

The piwheels service is hosted at [www.piwheels.hostedpi.com](https://www.piwheels.hostedpi.com/).

## Usage

[Raspbian Stretch](https://www.raspberrypi.org/downloads/raspbian/) includes
configuration for pip to use piwheels by default. If you're using an alternate
distribution, make sure you have pip v9, and you can use piwheels by placing
the following lines in `etc/pip.conf`:

```
[global]
extra-index-url=https://www.piwheels.hostedpi.com/simple
```

Alternatively, install from piwheels explicitly with `-i` or `--index-url`:

```
sudo pip3 install numpy -i https://www.piwheels.hostedpi.com/simple
```

or:

```
sudo pip3 install numpy --index-url https://www.piwheels.hostedpi.com/simple
```

Or as an additional index:

```
sudo pip3 install numpy --extra-index-url https://www.piwheels.hostedpi.com/simple
```

## Support

piwheels provides wheels which are compatible with all Raspberry Pi models
(Pi 3, Pi 2, Pi 1 and Pi Zero), for Python 3.4 and 3.5. We plan to add support
for Python 3.6 and 2.7.

## Issues

If you find any issues with packages installed from piwheels, please post an
issue on [GitHub](https://github.com/bennuttall/piwheels/issues), providing as
much detail as possible.

## Contributing

See the [contributing guidelines](CONTRIBUTING.md) for more information.

## Further reading

- [Wheel vs Egg](https://packaging.python.org/wheel_egg/)
- [PEP 427 -- The Wheel Binary Package Format 1.0](https://www.python.org/dev/peps/pep-0427/)
- [PEP 425 -- Compatibility Tags for Built Distributions](https://www.python.org/dev/peps/pep-0425/)
- [pip wheel documentation](https://pip.pypa.io/en/stable/reference/pip_wheel/)
- [Hosting your Own Simple Repository](https://packaging.python.org/self_hosted_repository/)
- [piwheels: building a faster Python package repository for Raspberry Pi users](http://bennuttall.com/piwheels-building-a-faster-python-package-repository-for-raspberry-pi-users/)
