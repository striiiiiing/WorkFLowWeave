"""Direct SSH TCP transport with smaller segments for reliable artifact transfers."""

import select
import socket
import sys

MAX_SEGMENT_BYTES = 1000

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
    connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_MAXSEG, MAX_SEGMENT_BYTES)
    connection.connect((sys.argv[1], int(sys.argv[2])))
    while True:
        readable, _, _ = select.select([connection, sys.stdin.buffer], [], [])
        for stream in readable:
            if stream is connection:
                data = connection.recv(65536)
                if not data:
                    sys.exit(0)
                sys.stdout.buffer.write(data)
                sys.stdout.buffer.flush()
            else:
                data = sys.stdin.buffer.read1(65536)
                if not data:
                    connection.shutdown(socket.SHUT_WR)
                    while True:
                        data = connection.recv(65536)
                        if not data:
                            sys.exit(0)
                        sys.stdout.buffer.write(data)
                        sys.stdout.buffer.flush()
                connection.sendall(data)
