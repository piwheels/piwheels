# piwheels Ansible

Ansible configuration for deploying and managing piwheels build slaves.

## Prerequisites

Install ansible via apt and hostedpi via pip (piwheels master runs Bookworm):

```bash
apt install ansible
pip3 install 'hostedpi[cli]' --break-system-packages
```

hostedpi's dependencies (`pydantic-settings` etc.) are not available as apt packages so pip is required. Ansible's apt package is sufficient.

Configure hostedpi with Mythic Beasts credentials, then add the SSH key to all slaves:

```bash
hostedpi ssh keys add ~/.ssh/id_rsa.pub --filter pw-slave
```

## Location

The piwheels repository is cloned to `/home/piwheels/piwheels` on the master. All ansible commands should be run from `/home/piwheels/piwheels/ansible/`:

```bash
cd /home/piwheels/piwheels/ansible
```

`ansible.cfg` uses relative paths for the inventory and roles, so this working directory is required.

## Setup

Generate the local inventory from the current hostedpi state:

```bash
scripts/update-hosts.sh
```

This writes `inventory/hosts.yml` (gitignored) with the SSH hostname and port for every provisioned Pi, including the master. The script can be run from any directory. Re-run it whenever slaves are provisioned or cancelled.

## Deploying slaves

Deploy all slaves (one at a time by default):

```bash
ansible-playbook playbooks/deploy_slave.yml
```

Deploy in parallel:

```bash
ansible-playbook playbooks/deploy_slave.yml -e play_serial=0
```

Target a specific host or group:

```bash
ansible-playbook playbooks/deploy_slave.yml -e target=pw-slave-cp313-01
ansible-playbook playbooks/deploy_slave.yml -e target=cp311
```

Deploy cp313 (Trixie) slaves — these are provisioned with Bookworm and upgraded during deployment:

```bash
ansible-playbook playbooks/deploy_slave.yml -e "target=cp313 play_serial=0 upgrade_to_trixie=true"
```

## Rebalancing slaves

The desired balance is recorded in `inventory/balance.yml`. To change it, edit that file and then provision/cancel Pis via hostedpi accordingly:

1. **Cancel unwanted slaves:**
   ```bash
   hostedpi cancel -y pw-slave-cp311-10
   ```

2. **Provision new slaves** (use `rpi-bookworm-armhf` for cp311/cp313, `rpi-bullseye-armhf` for cp39):
   ```bash
   hostedpi create pw-slave-cp39-05 --model 4 --disk 50 --os-image rpi-bullseye-armhf --ssh-key-path ~/.ssh/id_rsa.pub
   ```

3. **Regenerate the inventory:**
   ```bash
   scripts/update-hosts.sh
   ```

4. **Deploy new slaves:**
   ```bash
   ansible-playbook playbooks/deploy_slave.yml -e "target=pw-slave-cp39-05 play_serial=0"
   ```

5. **Copy master SSH keys to new slaves:**
   ```bash
   hostedpi ssh keys copy piwheels pw-slave-cp39-05
   ```

The account quota is 22 Pis total including the master, so the maximum number of slaves is 21.

## ABIs and OS images

| Group | Python | Debian     | OS image              |
|-------|--------|------------|-----------------------|
| cp39  | 3.9    | Bullseye   | rpi-bullseye-armhf    |
| cp311 | 3.11   | Bookworm   | rpi-bookworm-armhf    |
| cp313 | 3.13   | Trixie     | rpi-bookworm-armhf *  |

\* No Trixie image is available; cp313 slaves are provisioned with Bookworm and dist-upgraded to Trixie during deployment using `upgrade_to_trixie=true`.

## Notes

- Do not run any hostedpi commands against the `piwheels` master Pi (other than retrieving info or copying SSH keys).
- `inventory/hosts.yml` is gitignored — it is generated locally from hostedpi and will differ per machine.
- Fact caching is enabled (1 hour TTL in `.ansible_facts/`). Clear it with `rm -rf .ansible_facts/` if hosts have changed significantly.
