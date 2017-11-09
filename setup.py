"Setup script for the piwheels package"

import sys
from setuptools import setup, find_packages

if not sys.version_info >= (3, 4):
    raise RuntimeError('This application requires Python 3.4 or later')


def main():
    "Executes setup when this script is the top-level"
    import piwheels as app
    from pathlib import Path

    with Path(__file__).with_name('README.rst').open() as readme:
        setup(
            name=app.__project__,
            version=app.__version__,
            description=app.__doc__,
            long_description=readme.read(),
            classifiers=app.__classifiers__,
            author=app.__author__,
            author_email=app.__author_email__,
            url=app.__url__,
            license=[
                c.rsplit('::', 1)[1].strip()
                for c in app.__classifiers__
                if c.startswith('License ::')
            ][0],
            keywords=app.__keywords__,
            packages=find_packages(),
            include_package_data=True,
            platforms=app.__platforms__,
            install_requires=app.__requires__,
            extras_require=app.__extra_requires__,
            entry_points=app.__entry_points__,
        )


if __name__ == '__main__':
    main()
