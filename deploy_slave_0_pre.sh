#!/bin/bash

set -eu

apt update
apt install chrony -y
systemctl enable --now chrony
apt install vim wget byobu -y
byobu-enable