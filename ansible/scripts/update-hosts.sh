#!/bin/bash
# Generates inventory/hosts.yml from the current hostedpi state.
# Run this after provisioning or cancelling slaves.
set -e

DEST="$(dirname "$0")/../inventory/hosts.yml"

master_host=$(hostedpi info ssh-hostname piwheels)
master_port=$(hostedpi info ssh-port piwheels)

cat > "$DEST" <<EOF
all:
  children:
    piwheels_master:
      hosts:
        piwheels-master:
          ansible_host: $master_host
          ansible_port: $master_port
          ansible_user: root
    piwheels_slaves:
      children:
        cp311:
          hosts:
EOF

for name in $(hostedpi list | grep pw-slave-cp311 | sort); do
    host=$(hostedpi info ssh-hostname "$name")
    port=$(hostedpi info ssh-port "$name")
    cat >> "$DEST" <<EOF
            $name:
              ansible_host: $host
              ansible_port: $port
EOF
done

cat >> "$DEST" <<EOF
        cp313:
          hosts:
EOF

for name in $(hostedpi list | grep pw-slave-cp313 | sort); do
    host=$(hostedpi info ssh-hostname "$name")
    port=$(hostedpi info ssh-port "$name")
    cat >> "$DEST" <<EOF
            $name:
              ansible_host: $host
              ansible_port: $port
EOF
done

cat >> "$DEST" <<EOF
        cp39:
          hosts:
EOF

for name in $(hostedpi list | grep pw-slave-cp39 | sort); do
    host=$(hostedpi info ssh-hostname "$name")
    port=$(hostedpi info ssh-port "$name")
    cat >> "$DEST" <<EOF
            $name:
              ansible_host: $host
              ansible_port: $port
EOF
done

echo "Written $DEST"
