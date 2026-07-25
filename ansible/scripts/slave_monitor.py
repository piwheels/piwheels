#!/usr/bin/env python3
"""
Monitor piwheels build slaves and recover unhealthy or unreachable ones.

Health check distinguishes three states:
  - healthy     reachable over SSH and piwheels-slave service active
  - unhealthy   reachable but piwheels-slave service not active
  - unreachable Ansible cannot reach the host over SSH at all

Recovery tiers:
  Tier 1 (unhealthy)   restart the piwheels-slave service
  Tier 2 (unhealthy)   full Ansible redeploy, if restart failed or the slave is
                       still unhealthy RESTART_COOLDOWN after the last restart
  Tier 3 (unreachable) reboot the Pi via the hostedpi CLI
  Tier 4 (unreachable) cancel and reprovision a fresh Pi (same hostname), if the
                       slave is still unreachable REBOOT_COOLDOWN after the last
                       reboot

The monitor runs as a short, non-blocking oneshot every few minutes: each tier
fires its action and returns, and escalation happens across runs once the
relevant cooldown elapses. Only the Tier 4 reprovision blocks (it waits on
provisioning + deploy), and only for genuinely dead Pis.

State is persisted to STATE_FILE so recovery history survives across runs.
"""

import argparse
import json
import logging
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path

import yaml

import slave_balance as sb

SCRIPT_DIR = Path(__file__).parent.resolve()
ANSIBLE_DIR = SCRIPT_DIR.parent
INVENTORY = ANSIBLE_DIR / 'inventory' / 'hosts.yml'
DEPLOY_PLAYBOOK = ANSIBLE_DIR / 'playbooks' / 'deploy_slave.yml'
STATE_FILE = ANSIBLE_DIR / '.state' / 'slave-monitor-state.json'

RESTART_COOLDOWN = timedelta(minutes=15)
REBOOT_COOLDOWN = timedelta(minutes=15)
MAX_CHECK_WORKERS = 10

# Timestamp fields stored in state, parsed back to datetime on load.
_STATE_TIMES = ('last_restart', 'last_reboot', 'last_reprovision', 'last_healthy')


def load_inventory():
    with open(INVENTORY) as f:
        inv = yaml.safe_load(f)
    slaves = {}
    groups = inv['all']['children']['piwheels_slaves']['children']
    for abi, group in groups.items():
        for hostname, host_vars in (group.get('hosts') or {}).items():
            slaves[hostname] = {'abi': abi, **host_vars}
    return slaves


def _run_ansible(extra_args, timeout=120):
    return subprocess.run(
        ['ansible'] + extra_args + ['-i', str(INVENTORY)],
        capture_output=True, text=True, timeout=timeout, cwd=ANSIBLE_DIR,
    )


def _run_playbook(extra_args, timeout=1800):
    return subprocess.run(
        ['ansible-playbook', str(DEPLOY_PLAYBOOK)] + extra_args + ['-i', str(INVENTORY)],
        capture_output=True, text=True, timeout=timeout, cwd=ANSIBLE_DIR,
    )


def check_slave_health(hostname):
    """Return 'healthy', 'unhealthy', or 'unreachable' for a slave.

    Reachability is tested with the ping module first; only if the host answers
    do we check whether the piwheels-slave service is active.
    """
    log = logging.getLogger(__name__)
    try:
        ping = _run_ansible([hostname, '-m', 'ping'])
        if ping.returncode != 0:
            return 'unreachable'
        svc = _run_ansible(
            [hostname, '-m', 'shell', '-a', 'systemctl is-active piwheels-slave']
        )
        return 'healthy' if svc.returncode == 0 else 'unhealthy'
    except subprocess.TimeoutExpired:
        log.error('Health check for %s timed out; treating as unreachable', hostname)
        return 'unreachable'
    except Exception as exc:
        log.error('Error checking %s: %s', hostname, exc)
        return 'unreachable'


def restart_service(hostname):
    log = logging.getLogger(__name__)
    log.info('Restarting piwheels-slave on %s', hostname)
    result = _run_ansible(
        [hostname, '-m', 'systemd', '-a', 'name=piwheels-slave state=restarted']
    )
    if result.returncode != 0:
        log.error('Restart failed for %s:\n%s\n%s', hostname, result.stdout, result.stderr)
        return False
    log.info('Service restart succeeded for %s', hostname)
    return True


def redeploy_slave(hostname):
    log = logging.getLogger(__name__)
    log.warning('Running full Ansible redeploy for %s', hostname)
    result = _run_playbook(['--limit', hostname])
    if result.returncode != 0:
        log.error('Redeploy failed for %s:\n%s\n%s', hostname, result.stdout, result.stderr)
        return False
    log.info('Redeploy succeeded for %s', hostname)
    return True


def reboot_slave(hostname):
    """Reboot an unreachable Pi via the hostedpi CLI."""
    log = logging.getLogger(__name__)
    if hostname in sb.PROTECTED:
        log.error('Refusing to reboot protected instance: %s', hostname)
        return False
    log.warning('Rebooting %s via hostedpi', hostname)
    try:
        sb.hostedpi('reboot', hostname)
    except RuntimeError as exc:
        log.error('Reboot failed for %s: %s', hostname, exc)
        return False
    log.info('Reboot issued for %s', hostname)
    return True


def reprovision_slave(hostname, abi, ssh_key):
    """Cancel a dead Pi and provision a fresh one under the same hostname.

    Mutates and saves the raw inventory, deploys the replacement and copies the
    master SSH keys, mirroring slave_balance.py's provisioning flow.
    """
    log = logging.getLogger(__name__)
    if hostname in sb.PROTECTED:
        log.error('Refusing to reprovision protected instance: %s', hostname)
        return False

    log.warning('Reprovisioning %s (%s): cancel + fresh Pi', hostname, abi)
    try:
        sb.cancel_slave(hostname)
    except RuntimeError as exc:
        # Already gone is fine; anything else and we should not push on blindly.
        log.warning('Cancel of %s reported: %s', hostname, exc)

    try:
        ssh_hostname, ssh_port = sb.provision_slave(
            hostname, abi, sb.DEFAULT_MODEL, sb.DEFAULT_DISK, ssh_key)
    except RuntimeError as exc:
        log.error('Provisioning of %s failed: %s', hostname, exc)
        return False

    raw_inv = sb.load_inventory()
    group = sb.get_group(raw_inv, abi)
    group['hosts'][hostname] = {
        'ansible_host': ssh_hostname,
        'ansible_port': ssh_port,
    }
    sb.save_inventory(raw_inv)
    log.info('%s reprovisioned (%s:%d); deploying', hostname, ssh_hostname, ssh_port)

    if not sb.deploy_slaves([hostname], upgrade_to_trixie=(abi == 'cp313')):
        log.error('Deploy of reprovisioned %s failed; will retry on a later run', hostname)
        return False

    try:
        sb.copy_master_ssh_keys(hostname)
    except RuntimeError as exc:
        log.warning('Copying master SSH keys to %s failed: %s', hostname, exc)
    log.info('Reprovision of %s complete', hostname)
    return True


def load_state():
    if not STATE_FILE.exists():
        return {}
    with open(STATE_FILE) as f:
        data = json.load(f)
    for entry in data.values():
        for key in _STATE_TIMES:
            if entry.get(key):
                entry[key] = datetime.fromisoformat(entry[key])
    return data


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    serializable = {}
    for hostname, entry in state.items():
        serializable[hostname] = {
            k: v.isoformat() if isinstance(v, datetime) else v
            for k, v in entry.items()
        }
    with open(STATE_FILE, 'w') as f:
        json.dump(serializable, f, indent=2)


def recover_unhealthy(hostname, entry, now):
    """Tier 1/2: reachable but service down — restart, escalate to redeploy."""
    log = logging.getLogger(__name__)
    last_restart = entry.get('last_restart')
    if last_restart is None or (now - last_restart) > RESTART_COOLDOWN:
        if restart_service(hostname):
            entry['last_restart'] = now
        else:
            log.warning('%s: restart failed, running full redeploy', hostname)
            redeploy_slave(hostname)
    else:
        age_min = int((now - last_restart).total_seconds() // 60)
        log.warning('%s: still unhealthy %dm after restart, redeploying', hostname, age_min)
        redeploy_slave(hostname)


def recover_unreachable(hostname, abi, entry, now, ssh_key):
    """Tier 3/4: unreachable — reboot, escalate to cancel + reprovision."""
    log = logging.getLogger(__name__)
    last_reboot = entry.get('last_reboot')
    if last_reboot is None or (now - last_reboot) > REBOOT_COOLDOWN:
        if reboot_slave(hostname):
            entry['last_reboot'] = now
        else:
            log.warning('%s: reboot failed, reprovisioning', hostname)
            if reprovision_slave(hostname, abi, ssh_key):
                entry['last_reprovision'] = now
                entry.pop('last_reboot', None)
    else:
        age_min = int((now - last_reboot).total_seconds() // 60)
        log.warning('%s: still unreachable %dm after reboot, reprovisioning', hostname, age_min)
        if reprovision_slave(hostname, abi, ssh_key):
            entry['last_reprovision'] = now
            entry.pop('last_reboot', None)


def monitor_once(dry_run=False, ssh_key=None):
    log = logging.getLogger(__name__)
    slaves = load_inventory()
    if not slaves:
        log.warning('No slaves found in inventory')
        return

    state = load_state()
    now = datetime.now()

    log.info('Checking %d slave(s)', len(slaves))
    health = {}
    workers = min(len(slaves), MAX_CHECK_WORKERS)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(check_slave_health, h): h for h in slaves}
        for future in as_completed(futures):
            health[futures[future]] = future.result()

    for hostname, info in slaves.items():
        entry = state.setdefault(hostname, {'consecutive_failures': 0})
        status = health[hostname]

        if status == 'healthy':
            entry.update(consecutive_failures=0, last_healthy=now)
            log.info('%s: healthy', hostname)
            continue

        entry['consecutive_failures'] = entry.get('consecutive_failures', 0) + 1
        log.warning('%s: %s (failure #%d)', hostname, status, entry['consecutive_failures'])

        if dry_run:
            continue

        if status == 'unreachable':
            recover_unreachable(hostname, info['abi'], entry, now, ssh_key)
        else:
            recover_unhealthy(hostname, entry, now)

    # Drop state for hosts no longer in the inventory.
    for stale in set(state) - set(slaves):
        del state[stale]

    save_state(state)


def main():
    parser = argparse.ArgumentParser(description='Monitor piwheels build slaves')
    parser.add_argument('--dry-run', action='store_true',
                        help='Check health without attempting recovery')
    parser.add_argument('--ssh-key', metavar='FILE',
                        default=str(Path('~/.ssh/id_rsa.pub').expanduser()),
                        help='SSH public key for reprovisioned Pis')
    parser.add_argument('--debug', action='store_true')
    args = parser.parse_args()

    logging.basicConfig(
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
        level=logging.DEBUG if args.debug else logging.INFO,
    )
    monitor_once(dry_run=args.dry_run, ssh_key=args.ssh_key)


if __name__ == '__main__':
    main()
