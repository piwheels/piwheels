import zmq
from db import PiWheelsDatabase
from threading import Thread, Event
from signal import pause

stop = Event()
idle = Event()

def update_pkgs():
    with PiWheelsDatabase() as db:
        while not stop.wait(60):
            db.update_package_list()
            db.update_package_version_list()

def send_cmds(q):
    with PiWheelsDatabase() as db:
        while not stop.wait(5):
            if db.build_active():
                q.send_string('RUN')
            else:
                q.send_string('PAUSE')

def queue_jobs(q):
    with PiWheelsDatabase() as db:
        while not stop.wait(5):
            if idle.wait(0):
                for package, version in db.get_build_queue():
                    q.send_json((package, version))
                    if stop.wait(0): # check stop regularly
                        break
                idle.clear()

def log_results(q):
    with PiWheelsDatabase() as db:
        while not stop.wait(0):
            events = q.poll(10000)
            if events:
                msg = q.recv_json()
                if msg == 'IDLE':
                    print('!!! Idle builder found')
                    idle.set()
                else:
                    db.log_build(*msg)

def main():
    ctx = zmq.Context()
    build_queue = ctx.socket(zmq.PUSH)
    build_queue.ipv6 = True
    build_queue.bind('tcp://*:5555')
    log_queue = ctx.socket(zmq.PULL)
    log_queue.ipv6 = True
    log_queue.bind('tcp://*:5556')
    ctrl_queue = ctx.socket(zmq.PUB)
    ctrl_queue.ipv6 = True
    ctrl_queue.bind('tcp://*:5557')
    try:
        pkg_thread = Thread(target=update_pkgs, args=(), daemon=True)
        job_thread = Thread(target=queue_jobs, args=(build_queue,), daemon=True)
        log_thread = Thread(target=log_results, args=(log_queue,), daemon=True)
        ctrl_thread = Thread(target=send_cmds, args=(ctrl_queue,), daemon=True)
        pkg_thread.start()
        job_thread.start()
        log_thread.start()
        ctrl_thread.start()
        try:
            pause()
        finally:
            stop.set()
            job_thread.join()
            log_thread.join()
            pkg_thread.join()
            ctrl_thread.join()
            ctrl_queue.send_string('QUIT')
    finally:
        build_queue.close()
        log_queue.close()
        ctrl_queue.close()
        ctx.term()

if __name__ == '__main__':
    main()
