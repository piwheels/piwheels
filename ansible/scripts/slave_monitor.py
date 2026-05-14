#!/usr/bin/env python3
"""
Monitor piwheels build slaves and recover unhealthy ones.

Health check: ansible shell → systemctl is-active piwheels-slave
Recovery tier 1: restart the service
Recovery tier 2: full Ansible redeploy (triggered if restart fails or slave
                 is still unhealthy RESTART_COOLDOWN after last restart)

State is persisted to STATE_FILE so restart history survives across runs.
"""

import argparse
import json
import logging
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).parent.resolve()
ANSIBLE_DIR = SCRIPT_DIR.parent
INVENTORY = ANSIBLE_DIR / 'inventory' / 'hosts.yml'
DEPLOY_PLAYBOOK = ANSIBLE_DIR / 'playbooks' / 'deploy_slave.yml'
STATE_FILE = Path('/home/piwheels/slave-monitor-state.json')

RESTART_COOLDOWN = timedelta(minutes=15)
MAX_CHECK_WORKERS = 10


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
    """Returns True if slave is reachable and piwheels-slave service is active."""
    try:
        result = _run_ansible(
            [hostname, '-m', 'shell', '-a', 'systemctl is-active piwheels-slave']
        )
        return result.returncode == 0
    except Exception as exc:
        logging.getLogger(__name__).error('Error checking %s: %s', hostname, exc)
        return False


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


def load_state():
    if not STATE_FILE.exists():
        return {}
    with open(STATE_FILE) as f:
        data = json.load(f)
    for entry in data.values():
        for key in ('last_restart', 'last_healthy'):
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


def monitor_once(dry_run=False):
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

    for hostname in slaves:
        entry = state.setdefault(hostname, {'consecutive_failures': 0})

        if health[hostname]:
            entry.update(consecutive_failures=0, last_healthy=now)
            log.info('%s: healthy', hostname)
            continue

        entry['consecutive_failures'] = entry.get('consecutive_failures', 0) + 1
        log.warning('%s: unhealthy (failure #%d)', hostname, entry['consecutive_failures'])

        if dry_run:
            continue

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

    save_state(state)


def main():
    parser = argparse.ArgumentParser(description='Monitor piwheels build slaves')
    parser.add_argument('--dry-run', action='store_true',
                        help='Check health without attempting recovery')
    parser.add_argument('--debug', action='store_true')
    args = parser.parse_args()

    logging.basicConfig(
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
        level=logging.DEBUG if args.debug else logging.INFO,
    )
    monitor_once(dry_run=args.dry_run)


if __name__ == '__main__':
    main()
