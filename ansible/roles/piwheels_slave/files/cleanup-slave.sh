#!/bin/bash
# cleanup-slave.sh - clean cargo/pip cache if disk usage is above threshold,
#                    and restore shell config files to their post-deploy baseline

THRESHOLD=80
PART="/"

# Always restore shell config files from baseline to undo any build modifications
BASELINE_DIR=/home/piwheels/.shell-baselines
if [ -d "$BASELINE_DIR" ]; then
    for f in .bashrc .bash_profile .profile; do
        if [ -f "$BASELINE_DIR/$f" ]; then
            cp "$BASELINE_DIR/$f" /home/piwheels/$f
        fi
    done
    logger -p info "piwheels-slave cleanup: shell configs restored from baseline"
fi

USAGE=$(df -P "$PART" | awk 'NR==2 {print $5}' | tr -d '%')

if (( USAGE >= THRESHOLD )); then
    logger -p info "piwheels-slave cleanup: disk at ${USAGE}%, cleaning cargo/pip cache"
    systemctl stop piwheels-slave
    rm -rf /home/piwheels/.cargo/registry /home/piwheels/.cargo/git /home/piwheels/.cache \
           /home/piwheels/go/pkg/mod /home/piwheels/.sage
    systemctl start piwheels-slave
    logger -p info "piwheels-slave cleanup: done, disk now $(df -P "$PART" | awk 'NR==2 {print $5}') full"
fi
