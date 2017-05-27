# piwheels

piwheels is Python package repository providing [wheels](https://packaging.python.org/wheel_egg/) (pre-built binaries) for the armv6 and armv7 architectures used by [Raspberry Pi](https://www.raspberrypi.org/).

This repository contains the source code for building armv6 and armv7 wheels for packages found on [PyPI](https://pypi.python.org/pypi), and the project's future will be discussed in [GitHub issues](https://github.com/bennuttall/piwheels/issues). A very limited live repository is currently provided at [piwheels.bennuttall.com](http://piwheels.bennuttall.com/), hosted on a Raspberry Pi 3. You shouldn't rely on this, as it's just for testing purposes at present, but feel free to try it out.

## Why?

When you try to `pip install` a Python package which is implemented in C, it requires building for your computer's architecture. On a PC this will be x86 or x86_64. Some package maintainers provide wheels for these common architectures, which means you don't have to build the package yourself to install it. However, it's unlikely a package will provide an ARM wheel.

Some packages can take a long time to build, especially on BCM2835-based Raspberry Pi models (Pi 1 and Pi Zero). If a wheel is available (for your architecture), this makes it much easier to install, as pip simply downloads the wheel and installs it, no building required.

While Debian packages are available for some Python libraries, they are often older versions than available from PyPI, and if you're using a virtualenv, you need to `pip install` modules.

## Who?

I'm Ben Nuttall, Raspberry Pi's Community Manager. I'm [@ben_nuttall](https://twitter.com/ben_nuttall/) on Twitter.

## How?

I have a Raspberry Pi 3 running the build script in this repository (written in Python), producing wheels and publishing them with a web server.

To manually build a wheel for a package, you simply run:

```bash
pip wheel <package>
```

which (if successful) will produce a `.whl` file.

The format of the filename is: `{python tag}-{abi tag}-{platform tag}`. The platform tag for Raspberry Pi 1 and Zero (BCM2835) is `armv6l`, and for Pi 2 and 3 (BCM2836/BCM2837) is `armv7l` - although the Pi 3 has an ARMv8 CPU, the Raspbian OS runs in ARMv7 (32-bit) mode. Packages which do not require building will produce a wheel with a platform tag of `any`, and can be used on either architecture.

## Usage

To install a package from piwheels, you supply the repository URL using the `i` or `--index-url` flag to the `pip install` command:

```bash
pip install <package> -i http://piwheels.bennuttall.com/
```

or to use as an "extra" index:

```bash
pip install <package> --extra-index-url http://piwheels.bennuttall.com/
```

## Uploading wheels to PyPI

PyPI does not currently support uploading ARM wheels. The [next generation](https://pypi.org/) of PyPI [will support ARM wheels](https://github.com/pypa/warehouse/issues/2003).

## Developers

Developers wishing to work on this project should observe the following notes:

TODO

## Contributing

Any help you can provide would be much appreciated! Please see the [issue tracker](https://github.com/bennuttall/piwheels/issues) to see where you can help.

Pull requests welcome - I'll try to write some project guidelines soon. It might be best to post an issue before starting work on a PR in case it's out of the scope of the project.

## Further reading

- [Wheel vs Egg](https://packaging.python.org/wheel_egg/)
- [PEP 427 -- The Wheel Binary Package Format 1.0](https://www.python.org/dev/peps/pep-0427/)
- [PEP 425 -- Compatibility Tags for Built Distributions](https://www.python.org/dev/peps/pep-0425/)
- [pip wheel documentation](https://pip.pypa.io/en/stable/reference/pip_wheel/)
- [Hosting your Own Simple Repository](https://packaging.python.org/self_hosted_repository/)
