TRUNCATE configuration, build_abis, packages, versions RESTART IDENTITY CASCADE;

\COPY configuration(id, version, pypi_serial) FROM 'csv/configuration.csv' CSV;
\COPY build_abis(abi_tag, skip) FROM 'csv/build_abis.csv' CSV;
\COPY packages(package, skip, description) FROM 'csv/packages.csv' CSV;
\COPY versions(package, version, released, skip, yanked) FROM 'csv/versions.csv' CSV;