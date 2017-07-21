import zmq
from db import PiWheelsDatabase
from threading import Thread, Event
from signal import pause

stop = Event()
idle = Event()

def queue_jobs(db, q):
    while not stop.wait(0):
        if idle.wait(60):
            db.update_package_list()
            db.update_package_version_list()
            for package, version in db.get_build_queue():
                q.send_json((package, version))
            idle.clear()

def log_results(db, q):
    while not stop.wait(0):
        events = q.poll(10000)
        if events:
            msg = q.recv_json()
            if msg == 'IDLE':
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
    try:
        db = PiWheelsDatabase()
        jobs_thread = Thread(target=queue_jobs, args=(db, build_queue), daemon=True)
        log_thread = Thread(target=log_results, args=(db, log_queue), daemon=True)
        jobs_thread.start()
        log_thread.start()
        try:
            pause()
        finally:
            stop.set()
            jobs_thread.join()
            log_thread.join()
    finally:
        build_queue.close()
        log_queue.close()
        ctx.term()

if __name__ == '__main__':
    main()
