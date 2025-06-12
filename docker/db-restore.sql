TRUNCATE configuration, build_abis, packages, versions, package_names, builds, files RESTART IDENTITY CASCADE;

\COPY configuration(id, version, pypi_serial) FROM 'csv/configuration.csv' CSV;
\COPY build_abis(abi_tag, skip) FROM 'csv/build_abis.csv' CSV;
\COPY packages(package, skip, description) FROM 'csv/packages.csv' CSV;
\COPY versions(package, version, released, skip, yanked) FROM 'csv/versions.csv' CSV;
\COPY package_names(package, name, seen) FROM 'csv/package_names.csv' CSV;
\COPY builds(build_id, package, version, built_by, built_at, duration, status, abi_tag) FROM 'csv/builds.csv' CSV;
\COPY files(filename, build_id, filesize, filehash, package_tag, package_version_tag, py_version_tag, abi_tag, platform_tag, requires_python) FROM 'csv/files.csv' CSV;
\COPY dependencies(filename, tool, dependency) FROM 'csv/dependencies.csv' CSV;