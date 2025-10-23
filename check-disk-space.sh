#!/bin/bash
# check-disk-space.sh - shutdown system if less than 1% disk space remains

# Partition to check (usually /)
PART="/"

# Get the remaining disk space percentage (without % sign)
AVAIL=$(df -P "$PART" | awk 'NR==2 {gsub("%",""); print 100-$5}')

# If available space is less than 1%, shut down
if (( AVAIL < 1 )); then
    logger -p crit "Disk space critically low ($AVAIL% free). Shutting down system."
    /usr/sbin/shutdown -h now "Disk space critically low ($AVAIL% free)"
fi