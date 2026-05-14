#!/usr/bin/env python3
"""
Adjust piwheels build slave counts by ABI using the hostedpi CLI.

Usage:
    slave_balance.py [--cp39 N] [--cp311 N] [--cp313 N] [--dry-run]

Auth is read from environment variables (HOSTEDPI_ID and HOSTEDPI_SECRET).

New slaves are provisioned via hostedpi, added to the Ansible inventory, and
deployed with the deploy_slave playbook. Removed slaves are deleted from the
inventory first, then cancelled via the hostedpi CLI.
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
DEFAULT_DISK = 30  # GB


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


def provision_slave(name, model, disk, ssh_key_path):
    """Create a Pi via hostedpi CLI and return (ssh_hostname, ssh_port)."""
    cmd = ['create', name, '--model', str(model), '--disk', str(disk), '--wait']
    if ssh_key_path and Path(ssh_key_path).exists():
        cmd += ['--ssh-key-path', str(ssh_key_path)]
    hostedpi(*cmd)
    ssh_hostname = f'ssh.{name}.hostedpi.com'
    # Retry ssh-port — the server may not be immediately visible after provisioning
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
    hostedpi('cancel', name, '--yes')


def deploy_slaves(hostnames):
    result = subprocess.run(
        ['ansible-playbook', str(DEPLOY_PLAYBOOK),
         '-i', str(INVENTORY),
         '--limit', ','.join(hostnames)],
        cwd=ANSIBLE_DIR,
    )
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

    if not os.environ.get('HOSTEDPI_ID') or not os.environ.get('HOSTEDPI_SECRET'):
        sys.exit('Error: HOSTEDPI_ID and HOSTEDPI_SECRET environment variables must be set')

    new_slaves = []

    for abi, delta in changes.items():
        group = get_group(inv, abi)

        if delta > 0:
            print(f'\nProvisioning {delta} {abi} slave(s):')
            for _ in range(delta):
                num = next_slave_number(inv, abi)
                name = f'{SLAVE_PREFIX}-{abi}-{num:02d}'
                print(f'  Creating {name}...')
                ssh_hostname, ssh_port = provision_slave(name, args.model, args.disk, args.ssh_key)
                group['hosts'][name] = {
                    'ansible_host': ssh_hostname,
                    'ansible_port': ssh_port,
                }
                new_slaves.append(name)
                # Save after each Pi so partial progress is not lost on failure
                save_inventory(inv)
                print(f'  {name}: ready ({ssh_hostname}:{ssh_port})')

        elif delta < 0:
            count_to_remove = -delta
            print(f'\nRemoving {count_to_remove} {abi} slave(s):')
            # Remove highest-numbered slaves first
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

    if new_slaves:
        print(f'\nDeploying to {len(new_slaves)} new slave(s): {", ".join(new_slaves)}')
        if not deploy_slaves(new_slaves):
            sys.exit(
                'Ansible deploy failed. Inventory has been updated — '
                're-run the deploy playbook manually:\n'
                f'  ansible-playbook ansible/playbooks/deploy_slave.yml '
                f'--limit {",".join(new_slaves)}'
            )

    print('\nDone.')


if __name__ == '__main__':
    main()
