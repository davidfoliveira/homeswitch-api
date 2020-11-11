import asyncore
from pymitter import EventEmitter
import socket
import sys
import traceback

from ..util import debug, DO_NOTHING


# Events
# - connect
# - next
# - drain


class AsyncSocketClient(EventEmitter):
    def __init__(self, buf_size=1024):
        EventEmitter.__init__(self)
        self.ip = None
        self.port = None
        self.timeout = None
        self.socket = None
        self.connected = False
        self.connecting = False
        self.buffer = bytearray()
        pass

    # Connects
    def connect(self, ip, port, timeout=None):
        self.ip = ip
        self.port = port
        self.timeout = timeout
        self.connecting = True
        self.socket = AsyncSocketClientNative(ip, port, timeout)
        self.fd = self.socket.socket.fileno()
        self.socket.on('connect', self._on_connect)
        self.socket.on('close', self._on_close)
        self.socket.on('exception', self._on_exception)
        self.socket.on('error', self._on_error)
        self.socket.on('read', self._on_read)
        self.socket.on('write', self._on_write)
        self.socket.start()

    def disconnect(self):
        if self.connected and self.socket and self.socket.socket:
            self.connected = False
            debug("DBUG", "Closing connecting socket to {}:{} (fd: {})".format(self.ip, self.port, self.fd))
            self.socket.close()
            return True

    def send(self, data):
        debug("DBUG", "Sending {} bytes to {}:{} (fd: {})".format(len(data), self.ip, self.port, self.fd))
        self.socket.send(data)

    def receive(self, num_bytes):
        return self.socket.recv(num_bytes)

    def _on_connect(self):
        debug("INFO", "Connected to {}:{} !".format(self.ip, self.port))
        self.connecting = False
        self.connected = True
        self.emit('connect')

    def _on_close(self):
        debug("INFO", "Connection to {}:{} was closed.".format(self.ip, self.port))
        if self.connected:
            debug("INFO", "Connection to {}:{} was reset by peer.".format(self.ip, self.port))
            self.emit('break')
        else:
            self.emit('disconnect')
        self.connected = False

    def _on_exception(self, ex):
        debug("WARN", "Socket ({}:{}) exception occurred:".format(self.ip, self.port), ex)
        self.emit('exception', ex)

    def _on_error(self, t, v, tb):
        debug("WARN", "Socket ({}:{}) error occurred:".format(self.ip, self.port), t, v, tb)
        self.emit('error', t, v, tb)

    def _on_read(self):
        debug("INFO", "Socket ({}:{}) read can happen".format(self.ip, self.port))
        self.emit('data')

    def _on_write(self):
#        debug("INFO", "Socket ({}:{}) write can happen".format(self.ip, self.port))
        self.emit('write')


class AsyncSocketClientNative(asyncore.dispatcher, EventEmitter):
    def __init__(self, host, port, timeout=None):
        self._host = host
        self._port = port
        asyncore.dispatcher.__init__(self)
        EventEmitter.__init__(self)
        self.create_socket(socket.AF_INET, socket.SOCK_STREAM)
        if timeout is not None:
            self.socket.settimeout(timeout)

    def start(self):
        self.connect((self._host, self._port))

    # Handle the connect event
    def handle_connect(self):
        self.emit('connect')

    # Handle the connect event
    def handle_close(self):
        self.emit('close')

    # Handle an exception
    def handle_expt(self, ex):
        self.emit('exception', ex)

    # Handle an error
    def handle_error(self):
        import sys
        import traceback
        t, v, tb = sys.exc_info()
        self.emit('error', t, v, tb)

    # Handle a read
    def handle_read(self):
        self.emit('read')

    # Handle a read
    def handle_write(self):
        self.emit('write')

    # Check if socket is writeable
    def writeable(self):
        return False