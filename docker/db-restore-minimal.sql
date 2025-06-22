TRUNCATE configuration, build_abis, packages, versions, package_names, preinstalled_apt_packages RESTART IDENTITY CASCADE;

\COPY configuration(id, version, pypi_serial) FROM 'csv/configuration.csv' CSV;
\COPY build_abis(abi_tag, skip) FROM 'csv/build_abis.csv' CSV;
\COPY packages(package, skip, description) FROM 'csv/packages.csv' CSV;
\COPY versions(package, version, released, skip, yanked) FROM 'csv/versions.csv' CSV;
\COPY package_names(package, name, seen) FROM 'csv/package_names.csv' CSV;
\COPY preinstalled_apt_packages(abi_tag, apt_package) FROM 'csv/preinstalled_apt_packages.csv' CSV;