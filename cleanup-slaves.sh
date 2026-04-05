#!/bin/bash
# cleanup-slaves.sh - clean cargo/pip cache on slaves with high disk usage
#
# Run from the host. Checks all slaves and cleans /home/piwheels/.cargo/registry,
# .cargo/git, and .cache on any slave at or above THRESHOLD% disk usage.

set -euo pipefail

THRESHOLD=80
SSH_CONFIG="/home/claude/slaves_ssh_config"
SSH_KEY="/home/claude/.ssh/id_rsa"
SSH="ssh -F $SSH_CONFIG -i $SSH_KEY -o ConnectTimeout=10 -o StrictHostKeyChecking=no"

SLAVES=(
    pw-slave-cp313-01 pw-slave-cp313-02 pw-slave-cp313-03 pw-slave-cp313-04
    pw-slave-cp313-05 pw-slave-cp313-06 pw-slave-cp313-07 pw-slave-cp313-08
    pw-slave-cp313-09 pw-slave-cp313-10 pw-slave-cp313-11 pw-slave-cp313-12
    pw-slave-cp313-15 pw-slave-cp313-16 pw-slave-cp313-17 pw-slave-cp313-18
    pw-slave-cp313-19 pw-slave-cp313-20 pw-slave-cp313-21
    pw-slave-cp311-09
    pw-slave-cp39-05
)

# Refresh SSH config in case any slaves have been reprovisioned
hostedpi ssh config "${SLAVES[@]}" > "$SSH_CONFIG" 2>/dev/null

for slave in "${SLAVES[@]}"; do
    usage=$($SSH "$slave" "df -P / | awk 'NR==2 {print \$5}' | tr -d '%'" 2>&1)

    if ! [[ "$usage" =~ ^[0-9]+$ ]]; then
        echo "$slave: unreachable, rebooting"
        hostedpi reboot "$slave" 2>/dev/null || true
        continue
    fi

    if (( usage >= THRESHOLD )); then
        echo "$slave: ${usage}% full, cleaning"
        $SSH "$slave" "
            systemctl stop piwheels-slave
            rm -rf /home/piwheels/.cargo/registry /home/piwheels/.cargo/git /home/piwheels/.cache
            systemctl start piwheels-slave
            df -h / | tail -1
        " 2>&1
    else
        echo "$slave: ${usage}% — ok"
    fi
done
