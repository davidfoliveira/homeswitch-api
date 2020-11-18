import asyncore
from errno import EALREADY, EINPROGRESS, EWOULDBLOCK, ECONNRESET, EINVAL, \
     ENOTCONN, ESHUTDOWN, EINTR, EISCONN, EBADF, ECONNABORTED, EPIPE, EAGAIN
from pymitter import EventEmitter
import socket
import sys
import traceback

from ..asyncorepp import set_timeout, cancel_timeout
from ..util import debug, DO_NOTHING


# Events
# - connect
# - next
# - drain


class AsyncSocketClient(EventEmitter):
    def __init__(self, buf_size=1024):
        EventEmitter.__init__(self)
        self.fd = None
        self.ip = None
        self.port = None
        self.timeout = None
        self.socket = None
        self.connected = False
        self.connecting = False
        self.error = None
        self.buffer = bytearray()
        pass

    # Connects
    def connect(self, ip, port, timeout=None):
        self.ip = ip
        self.port = port
        self.connecting = True
        self.socket = AsyncSocketClientNative(ip, port)
        self.fd = self.socket.socket.fileno()
        self.socket.on('connect', self._on_connect)
        self.socket.on('close', self._on_close)
        self.socket.on('exception', self._on_exception)
        self.socket.on('error', self._on_error)
        self.socket.on('read', self._on_read)
        self.socket.on('write', self._on_write)

        # Connect
        try:
            self.socket.start()
        except Exception as e:
            return self._on_failure(e)

        # Set a timeout
        self.timeout = None
        if timeout is not None:
            debug("DBUG", "Setting socket timeout to {}".format(timeout))
            self.timeout = set_timeout(lambda: self._on_failure({'error': 'timeout'}), timeout)

    def disconnect(self):
        if self.connected:
            self.connected = False
            debug("DBUG", "Closing connecting socket to {}:{} (fd: {})".format(self.ip, self.port, self.fd))
            if self.socket and self.socket.socket:
                self.socket.close()
            else:
                debug("DBUG", "Connection to {}:{} NOT closed as is has no socket (fd: {})".format(self.ip, self.port, self.fd))
            return True

    def send(self, data):
        debug("DBUG", "Sending {} bytes to {}:{} (fd: {})".format(len(data), self.ip, self.port, self.fd))
        self.socket.send(data)

    def receive(self, num_bytes):
        return self.socket.recv(num_bytes)

    def _on_connect(self):
        debug("INFO", "Connected to {}:{} !".format(self.ip, self.port))
        if self.timeout is not None:
            cancel_timeout(self.timeout)
        self.connecting = False
        self.connected = True
        self.emit('connect')

    def _on_failure(self, ex):
        debug("ERRO", "Error connecting to {}:{}".format(self.ip, self.port), ex)
        self.connecting = False
        self.connected = False
        if self.socket and self.socket.socket:
            self.socket.close()
        self.emit('failure', ex)

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
    def __init__(self, host, port):
        self._host = host
        self._port = port
        self._error = None
        self._connect_called = False
        asyncore.dispatcher.__init__(self)
        EventEmitter.__init__(self)
        self.create_socket(socket.AF_INET, socket.SOCK_STREAM)

    def start(self):
        self.connect((self._host, self._port))

    # def connect(self, address):
    #     self.connected = False
    #     self.connecting = True
    #     err = self.socket.connect_ex(address)
    #     if err in (EINPROGRESS, EALREADY, EWOULDBLOCK) \
    #     or err == EINVAL and os.name in ('nt', 'ce'):
    #         self.addr = address
    #         return
    #     if err in (0, EISCONN):
    #         self.addr = address
    #         self.handle_connect_event()
    #     else:
    #         raise socket.error(err, errorcode[err])

    # Handle the connect event
    def handle_connect(self):
        if self._connect_called:
            debug("WARN", "handle_connect() on connection to {}:{} was already called. Something's wrong here")
            return
        self._connect_called = True
        self.emit('connect')

    # Handle the connect event
    def handle_close(self):
        self.close()
        self.emit('close')

    # Handle an exception
    def handle_expt(self, ex):
        self.emit('exception', ex)

    # Handle an error
    def handle_error(self):
        self._error = True
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

    # Check if socket is readable
    def readable(self):
        return self.connected

    # Check if socket is writeable
    def writable(self):
        return not self.connected and not self._error and not self._connect_called