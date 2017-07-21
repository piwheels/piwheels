import os
import zmq
from piwheels import PiWheelsBuilder
from datetime import datetime
from time import sleep

ctx = zmq.Context()
build_queue = ctx.socket(zmq.PULL)
build_queue.ipv6 = True
build_queue.connect('tcp://{PW_MASTER}:5555'.format(**os.environ))
log_queue = ctx.socket(zmq.PUSH)
log_queue.ipv6 = True
log_queue.connect('tcp://{PW_MASTER}:5556'.format(**os.environ))
try:
    while True:
        events = build_queue.poll(60000)
        if not events:
            print('idle; polling master')
            log_queue.send_string('IDLE')
        else:
            package, version = build_queue.recv_json()
            dt = datetime.now()
            print('package {0} version {1} started at {2:%a} {2:%d} {2:%b} {2:%H}:{2:%M}'.format(
                package, version, dt
            ))
            builder = PiWheelsBuilder(package, version)
            builder.build_wheel('/home/piwheels/www')
            builder.log_build(log_queue)
finally:
    log_queue.close()
    build_queue.close()
    ctx.term()
