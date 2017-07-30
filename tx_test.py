import io
import os
import binascii
from threading import Thread
from pprint import pprint

import zmq

PIPELINE = 10
CHUNKSIZE = 65536


def consolidate(ranges):
    start = stop = None
    for r in ranges:
        if start is None:
            start = r.start
        elif r.start > stop:
            yield range(start, stop)
            start = r.start
        stop = r.stop
    yield range(start, stop)


def split(ranges, at):
    for r in ranges:
        if at in r and at > r.start:
            yield range(r.start, at)
            yield range(at, r.stop)
        else:
            yield r


def exclude(ranges, start, stop):
    for r in split(split(ranges, start), stop):
        if r.stop <= start or r.start >= stop:
            yield r


def intersect(r1, r2):
    r = range(max(r1.start, r2.start), min(r1.stop, r2.stop))
    if r:
        return r


def fetch(offset, rec_map):
    fetch_range = range(offset, offset + CHUNKSIZE)
    while True:
        for map_range in rec_map:
            result = intersect(map_range, fetch_range)
            if result:
                offset = result.stop
                return offset, result
            elif map_range.start > fetch_range.start:
                fetch_range = range(map_range.start, map_range.start + CHUNKSIZE)
        fetch_range = range(rec_map.start, rec_map.start + CHUNKSIZE)


def zpipe(ctx):
    a = ctx.socket(zmq.PAIR)
    b = ctx.socket(zmq.PAIR)
    a.linger = b.linger = 0
    a.hwm = b.hwm = 1
    iface = "inproc://%s" % binascii.hexlify(os.urandom(8))
    a.bind(iface)
    b.connect(iface)
    return a, b


def zencode(msg):
    return [
        part if isinstance(part, bytes)
        else str(part).encode('ascii')
        for part in msg
    ]


def client_thread(ctx, pipe):
    dealer = ctx.socket(zmq.DEALER)
    dealer.hwm = PIPELINE
    dealer.connect("ipc://files")

    f = io.open('test.dat', 'rb')
    f.seek(0, io.SEEK_END)

    msg = ['HELLO', f.tell()]
    dealer.send_multipart(zencode(msg))
    while True:
        try:
            req, *args = dealer.recv_multipart()
        except zmq.ZMQError as e:
            if e.errno == zmq.ETERM:
                return
            else:
                raise

        if req == b'FETCH':
            offset = int(args[0].decode('ascii'))
            size = int(args[1].decode('ascii'))
            f.seek(offset)
            dealer.send_multipart([b'CHUNK', args[0], f.read(size)])

        elif req == b'DONE':
            break

        else:
            raise ValueError('invalid message from server: %s' % req)

    pipe.send(b'OK')


def server_thread(ctx):
    router = ctx.socket(zmq.ROUTER)
    router.hwm = PIPELINE
    router.bind("ipc://files")

    credit = PIPELINE

    while True:
        try:
            address, msg, *args = router.recv_multipart()
        except zmq.ZMQError as e:
            if e.errno == zmq.ETERM:
                return # shutting down
            else:
                raise

        if msg == b'HELLO':
            f = io.open('target.dat', 'wb')
            offset = 0
            filesize = int(args[0].decode('ascii'))
            rec_map = [range(filesize)]
            f.seek(filesize)
            f.truncate()

        elif msg == b'CHUNK':
            c_offset = int(args[0].decode('ascii'))
            c_size = len(args[1])
            f.seek(c_offset)
            f.write(args[1])
            credit += 1
            rec_map = list(exclude(rec_map, range(c_offset, c_offset + c_size)))
            print('Received %d bytes' % (c_offset + c_size))
            if c_size < CHUNKSIZE:
                router.send_multipart(zencode([address, 'DONE']))
                break

        else:
            raise ValueError('unknown message from client: %s' % msg)

        while credit:
            offset, size = fetch(offset, rec_map)
            router.send_multipart(zencode([address, 'FETCH', offset, size]))
            offset += size
            credit -= 1

    pprint(received)


def main():
    ctx = zmq.Context()
    a, b = zpipe(ctx)

    client = Thread(target=client_thread, args=(ctx, b))
    server = Thread(target=server_thread, args=(ctx,))
    client.start()
    server.start()

    # loop until client tells us it's done
    try:
        print(a.recv())
    except KeyboardInterrupt:
        pass
    del a, b
    ctx.term()


if __name__ == '__main__':
    main()
