#!/usr/bin/env python3
"""
Adjust piwheels build slave counts by ABI using the hostedpi CLI.

Usage:
    slave_balance.py [--cp39 N] [--cp311 N] [--cp313 N] [--dry-run]

Auth is read from environment variables (HOSTEDPI_ID and HOSTEDPI_SECRET).

New slaves are provisioned via hostedpi, added to the Ansible inventory, and
deployed with the deploy_slave playbook. Removed slaves are cancelled via the
hostedpi CLI and removed from the inventory.
"""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).parent.resolve()
ANSIBLE_DIR = SCRIPT_DIR.parent
INVENTORY = ANSIBLE_DIR / 'inventory' / 'hosts.yml'
DEPLOY_PLAYBOOK = ANSIBLE_DIR / 'playbooks' / 'deploy_slave.yml'
BALANCE_CONFIG = ANSIBLE_DIR / 'inventory' / 'balance.yml'

SLAVE_PREFIX = 'pw-slave'
ABI_GROUPS = ['cp39', 'cp311', 'cp313']
PROTECTED = {'piwheels'}  # master — never cancel or manage
DEFAULT_MODEL = 4
DEFAULT_DISK = 50  # GB

OS_IMAGES = {
    'cp39':  'rpi-bullseye-armhf',
    'cp311': 'rpi-bookworm-armhf',
    'cp313': 'rpi-bookworm-armhf',  # upgraded to Trixie during deploy
}


def load_balance_config():
    if not BALANCE_CONFIG.exists():
        return {}
    with open(BALANCE_CONFIG) as f:
        return yaml.safe_load(f) or {}


def load_inventory():
    with open(INVENTORY) as f:
        return yaml.safe_load(f)


def save_inventory(inv):
    with open(INVENTORY, 'w') as f:
        yaml.dump(inv, f, default_flow_style=False, sort_keys=False)


def get_group(inv, abi):
    """Return (and ensure) the group dict for an ABI, mutating inv in-place."""
    group = inv['all']['children']['piwheels_slaves']['children'].setdefault(abi, {})
    if group.get('hosts') is None:
        group['hosts'] = {}
    return group


def current_counts(inv):
    return {abi: len(get_group(inv, abi).get('hosts') or {}) for abi in ABI_GROUPS}


def slave_number(name, abi):
    prefix = f'{SLAVE_PREFIX}-{abi}-'
    suffix = name[len(prefix):]
    return int(suffix) if name.startswith(prefix) and suffix.isdigit() else 0


def next_slave_number(inv, abi):
    hosts = get_group(inv, abi).get('hosts') or {}
    nums = [slave_number(n, abi) for n in hosts]
    return max(nums, default=0) + 1


def slaves_by_number(inv, abi):
    """Return hostnames for an ABI sorted ascending by their numeric suffix."""
    hosts = get_group(inv, abi).get('hosts') or {}
    return sorted(hosts, key=lambda n: slave_number(n, abi))


def hostedpi(*args):
    """Run a hostedpi CLI command, return stdout. Raises on non-zero exit."""
    result = subprocess.run(
        ['hostedpi'] + list(args),
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f'hostedpi {" ".join(args)} failed:\n{result.stderr}')
    return result.stdout.strip()


def provision_slave(name, abi, model, disk, ssh_key_path):
    """Create a Pi via hostedpi CLI and return (ssh_hostname, ssh_port)."""
    cmd = ['create', name,
           '--model', str(model),
           '--disk', str(disk),
           '--os-image', OS_IMAGES[abi],
           '--wait']
    if ssh_key_path and Path(ssh_key_path).exists():
        cmd += ['--ssh-key-path', str(ssh_key_path)]
    hostedpi(*cmd)
    ssh_hostname = f'ssh.{name}.hostedpi.com'
    for attempt in range(5):
        try:
            ssh_port = int(hostedpi('info', 'ssh-port', name))
            return ssh_hostname, ssh_port
        except (RuntimeError, ValueError):
            if attempt == 4:
                raise
            time.sleep(10)
    raise RuntimeError(f'Could not get SSH port for {name}')


def cancel_slave(name):
    """Delete a Pi via hostedpi CLI."""
    if name in PROTECTED:
        raise RuntimeError(f'Refusing to cancel protected instance: {name}')
    hostedpi('cancel', '--yes', name)


def copy_master_ssh_keys(name):
    """Copy SSH keys from the piwheels master to a slave."""
    hostedpi('ssh', 'keys', 'copy', 'piwheels', name)


def deploy_slaves(hostnames, upgrade_to_trixie=False):
    cmd = ['ansible-playbook', str(DEPLOY_PLAYBOOK),
           '-i', str(INVENTORY),
           '-e', f'play_serial=0',
           '--limit', ','.join(hostnames)]
    if upgrade_to_trixie:
        cmd += ['-e', 'upgrade_to_trixie=true']
    result = subprocess.run(cmd, cwd=ANSIBLE_DIR)
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description='Balance piwheels build slave counts')
    for abi in ABI_GROUPS:
        parser.add_argument(f'--{abi}', type=int, metavar='N',
                            help=f'Desired number of {abi} slaves')
    parser.add_argument('--model', type=int, default=DEFAULT_MODEL,
                        help=f'Pi model for new slaves (default: {DEFAULT_MODEL})')
    parser.add_argument('--disk', type=int, default=DEFAULT_DISK,
                        help=f'Disk size in GB for new slaves (default: {DEFAULT_DISK})')
    parser.add_argument('--ssh-key', metavar='FILE',
                        default=os.path.expanduser('~/.ssh/id_rsa.pub'),
                        help='SSH public key file to add to new Pi instances')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show plan without making changes')
    args = parser.parse_args()

    config = load_balance_config()
    desired = {
        abi: getattr(args, abi) if getattr(args, abi) is not None else config.get(abi)
        for abi in ABI_GROUPS
        if getattr(args, abi) is not None or abi in config
    }
    if not desired:
        parser.error('Specify at least one ABI count, or add targets to inventory/balance.yml')

    inv = load_inventory()
    counts = current_counts(inv)

    print('Slave counts:')
    for abi in ABI_GROUPS:
        target = f'→ {desired[abi]}' if abi in desired else '(unchanged)'
        print(f'  {abi}: {counts[abi]}  {target}')

    changes = {abi: desired[abi] - counts[abi] for abi in desired if desired[abi] != counts[abi]}
    if not changes:
        print('No changes needed.')
        return

    if args.dry_run:
        print('\nPlanned changes:')
        for abi, delta in changes.items():
            print(f'  {abi}: {delta:+d} slaves')
        print('Dry run — no changes made.')
        return

    # Provision new slaves first, grouped by ABI for deployment
    new_slaves_by_abi = {abi: [] for abi in ABI_GROUPS}

    for abi, delta in changes.items():
        group = get_group(inv, abi)

        if delta > 0:
            print(f'\nProvisioning {delta} {abi} slave(s):')
            for _ in range(delta):
                num = next_slave_number(inv, abi)
                name = f'{SLAVE_PREFIX}-{abi}-{num:02d}'
                print(f'  Creating {name}...')
                ssh_hostname, ssh_port = provision_slave(
                    name, abi, args.model, args.disk, args.ssh_key)
                group['hosts'][name] = {
                    'ansible_host': ssh_hostname,
                    'ansible_port': ssh_port,
                }
                new_slaves_by_abi[abi].append(name)
                save_inventory(inv)
                print(f'  {name}: ready ({ssh_hostname}:{ssh_port})')

        elif delta < 0:
            count_to_remove = -delta
            print(f'\nRemoving {count_to_remove} {abi} slave(s):')
            to_remove = slaves_by_number(inv, abi)[-count_to_remove:]
            for name in to_remove:
                print(f'  Removing {name} from inventory...')
                del group['hosts'][name]
                save_inventory(inv)
                print(f'  Cancelling {name}...')
                try:
                    cancel_slave(name)
                    print(f'  {name}: cancelled')
                except RuntimeError as e:
                    print(f'  Warning: {e}')

    # Deploy new slaves, passing upgrade_to_trixie for cp313
    for abi, hostnames in new_slaves_by_abi.items():
        if not hostnames:
            continue
        print(f'\nDeploying {len(hostnames)} new {abi} slave(s): {", ".join(hostnames)}')
        if not deploy_slaves(hostnames, upgrade_to_trixie=(abi == 'cp313')):
            sys.exit(
                'Ansible deploy failed. Inventory has been updated — '
                're-run the deploy playbook manually:\n'
                f'  ansible-playbook playbooks/deploy_slave.yml '
                f'--limit {",".join(hostnames)}'
            )
        print(f'  Copying master SSH keys...')
        for name in hostnames:
            try:
                copy_master_ssh_keys(name)
                print(f'  {name}: keys copied')
            except RuntimeError as e:
                print(f'  Warning: {e}')

    print('\nDone.')


if __name__ == '__main__':
    main()
