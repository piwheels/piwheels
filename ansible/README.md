# piwheels Ansible

Ansible configuration for deploying and managing piwheels build slaves.

## Prerequisites

Install ansible and hostedpi via pip:

```bash
pip3 install ansible 'hostedpi[cli]' --break-system-packages
```

hostedpi's dependencies (`pydantic-settings` etc.) are not available as apt packages so pip is required. `apt install ansible` also works if preferred.

Configure hostedpi with Mythic Beasts credentials, then add the SSH key to all slaves:

```bash
hostedpi ssh keys add ~/.ssh/id_rsa.pub --filter pw-slave
```

## Location

Ansible management runs from this checkout (not from the master — nothing is installed on the
`piwheels` master Pi other than the build slave software it already runs). All ansible commands
should be run from this directory:

```bash
cd ansible
```

`ansible.cfg` uses relative paths for the inventory and roles, so this working directory is required.
Hosts are reached directly over SSH via their hostedpi proxy hostnames, so this can run from any
machine with `ansible`, `hostedpi` and network access — it doesn't need to run on the master or on
any of the slaves themselves.

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

The desired balance is recorded in `inventory/balance.yml`. To apply it, update that file and run:

```bash
ansible-playbook playbooks/rebalance.yml
```

This runs `scripts/slave_balance.py`, which provisions or cancels Pis via hostedpi, updates `inventory/hosts.yml`, deploys new slaves, and copies master SSH keys — all automatically.

To preview changes without applying them:

```bash
python3 scripts/slave_balance.py --dry-run
```

To override the balance from `balance.yml` on the command line:

```bash
python3 scripts/slave_balance.py --cp311 8 --cp313 8 --cp39 4
```

The account quota is 22 Pis total including the master, so the maximum number of slaves is 21.

## Monitoring and recovery

`scripts/slave_monitor.py` checks the health of every slave in the inventory and recovers unhealthy
or unreachable ones (service restart → redeploy → reboot → cancel-and-reprovision, escalating across
runs). It's designed to run frequently and unattended:

```bash
python3 scripts/slave_monitor.py
```

Recovery state (cooldowns, escalation history) is persisted to `.state/slave-monitor-state.json`
(gitignored) so it survives across runs. Use `--dry-run` to check health without taking action.

Nothing runs this automatically from within the repo — it's driven by a cron job on the operator
host, which also needs `HOSTEDPI_ID`/`HOSTEDPI_SECRET` in its environment for the `hostedpi` CLI
calls the recovery tiers make. There's no equivalent automatic driver for `slave_balance.py`; rebalancing to a new
target count is a deliberate operator action (see above).

## ABIs and OS images

| Group | Python | Debian     | OS image              |
|-------|--------|------------|-----------------------|
| cp39  | 3.9    | Bullseye   | rpi-bullseye-armhf    |
| cp311 | 3.11   | Bookworm   | rpi-bookworm-armhf    |
| cp313 | 3.13   | Trixie     | rpi-bookworm-armhf *  |

\* No Trixie image is available; cp313 slaves are provisioned with Bookworm and dist-upgraded to Trixie during deployment using `upgrade_to_trixie=true`.

## Notes

- Do not run any hostedpi commands against the `piwheels` master Pi (other than retrieving info or copying SSH keys). Nothing in this directory connects to or deploys onto the master.
- `inventory/hosts.yml` and `inventory/balance.yml` are gitignored — they're generated/configured locally and will differ per machine.
- Fact caching is enabled (1 hour TTL in `.ansible_facts/`). Clear it with `rm -rf .ansible_facts/` if hosts have changed significantly.
