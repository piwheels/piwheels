# piwheels

piwheels is Python package repository providing [wheels](https://packaging.python.org/wheel_egg/) (pre-built binaries) for the armv6 and armv7 architectures used by [Raspberry Pi](https://www.raspberrypi.org/).

This repository contains the source code for building armv6 and armv7 wheels for packages found on [PyPI](https://pypi.python.org/pypi), and the project's future will be discussed in [GitHub issues](https://github.com/bennuttall/piwheels/issues).

Two testing repositories are currently provided at [piwheels.bennuttall.com](http://piwheels.bennuttall.com/) and [www.piwheels.hostedpi.com](http://www.piwheels.hostedpi.com/). You shouldn't rely on these as they are just for testing purposes at present, but feel free to browse and try them out.

## Why?

When you try to `pip install` a Python package which is implemented in C, it requires building for your computer's architecture, such as x86 or x86_64. Some package maintainers provide wheels for these common architectures, which means you don't have to build the package yourself to install it. However, it's unlikely a package will provide an ARM wheel.

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

Note the original build test is located at [piwheels.bennuttall.com](http://piwheels.bennuttall.com/) and the ongoing production repository is located at [www.piwheels.hostedpi.com](http://www.piwheels.hostedpi.com/).

Note also that since these servers do not support HTTPS currently, a warning (or maybe a fatal error) will occur with the above usage, so instead use:

```bash
pip install <package> -i http://piwheels.bennuttall.com/ --trusted-host=piwheels.bennuttall.com
```

## Current status

In May 2017, as a proof-of-concept, I ran through the list of packages on PyPI and built the latest version of each one, logging the results in a database. There were 106,589 packages at the time. 76% built successfully, and the build run took 10 days on a single Raspberry Pi 3 in my house. The repository is still running and can be found at [piwheels.bennuttall.com](http://piwheels.bennuttall.com/). The results of the build can be found in [Issue #2](https://github.com/bennuttall/piwheels/issues/2).

In July 2017 I completed a refactoring of the code and added functionality to build every version of every package (and continuously update the build queue as new packages and versions are released), and kicked off the build again, this time on a hosted Raspberry Pi 3 using a [service provided by Mythic Beasts](https://www.mythic-beasts.com/order/rpi). This is currently running, but will require a lot more build time to complete, as there are 750,000 package versions and counting! I may have incorporate multiple Raspberry Pis to complete the initial build run. The repository is still running and can be found at [www.piwheels.hostedpi.com](http://www.piwheels.hostedpi.com/). The results of the build can be found in [Issue #5](https://github.com/bennuttall/piwheels/issues/5).

## Failed packages

If you see a failed package you would like to be provided, I would appreciate any effort you can make to help. Start by trying to build the package yourself on a Raspberry Pi 3. If it failed due to a build dependency, perhaps this is something we can fix. Please [open an issue](https://github.com/bennuttall/piwheels/issues/new/) to discuss resolving the build failure.

## Uploading wheels to PyPI

PyPI does not currently support uploading ARM wheels. The [next generation](https://pypi.org/) of PyPI [will support ARM wheels](https://github.com/pypa/warehouse/issues/2003). Package maintainers can upload ARM wheels to the next generation service, and they will be available on the current service. Do this by adding the following to your `.pypirc` file:

```bash
repository=https://upload.pypi.io/legacy/
```

Wheels generated by this project can be downloaded, and uploaded to PyPI by their maintainers.

## Developers

To develop on this project, follow the [developing instructions](developing.md). To set up your own piwheels server on a Raspberry Pi, follow the [installation instructions]. Please report any documentation issues you find on [GitHub](https://github.com/bennuttall/piwheels/issues).

## Contributing

Any help you can provide would be much appreciated! Please see the [issue tracker](https://github.com/bennuttall/piwheels/issues) to see where you can help.

Pull requests welcome. It might be best to post an issue before starting work on a PR.

See the [contributing guidelines](CONTRIBUTING.md) for more information.

## Further reading

- [Wheel vs Egg](https://packaging.python.org/wheel_egg/)
- [PEP 427 -- The Wheel Binary Package Format 1.0](https://www.python.org/dev/peps/pep-0427/)
- [PEP 425 -- Compatibility Tags for Built Distributions](https://www.python.org/dev/peps/pep-0425/)
- [pip wheel documentation](https://pip.pypa.io/en/stable/reference/pip_wheel/)
- [Hosting your Own Simple Repository](https://packaging.python.org/self_hosted_repository/)
