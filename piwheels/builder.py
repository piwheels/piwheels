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
ctrl_queue = ctx.socket(zmq.SUB)
ctrl_queue.ipv6 = True
crtl_queue.connect('tcp://{PW_MASTER}:5557'.format(**os.environ))
try:
    poller = zmq.Poller()
    poller.register(ctrl_queue, zmq.POLLIN)
    poller.register(build_queue, zmq.POLLIN)
    paused = False
    while True:
        socks = dict(poller.poll(60000))
        if ctrl_queue in socks:
            msg = ctrl_queue.recv_string()
            if msg == 'RUN':
                paused = False
            elif msg == 'PAUSE':
                paused = True
            elif msg == 'QUIT':
                break
        if paused:
            print('paused; waiting for master to resume')
        elif build_queue in socks:
            package, version = build_queue.recv_json()
            dt = datetime.now()
            print('package {} version {} started at {:%a %d %b %H:%M}'.format(package, version, dt))
            builder = PiWheelsBuilder(package, version)
            builder.build_wheel('/home/piwheels/www')
            builder.log_build(log_queue)
        else:
            print('idle; prodding master for more jobs')
            log_queue.send_json('IDLE')
finally:
    log_queue.close()
    build_queue.close()
    ctrl_queue.close()
    ctx.term()
