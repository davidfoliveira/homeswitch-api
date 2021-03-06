import asyncore
import base64
from errno import EALREADY, EINPROGRESS, EWOULDBLOCK, ECONNRESET, EINVAL, \
     ENOTCONN, ESHUTDOWN, EINTR, EISCONN, EBADF, ECONNABORTED, EPIPE, EAGAIN
import json
from pymitter import EventEmitter
import re
import socket
import time

import proto
from .util import debug, readUInt32BE, writeUInt32BE


HTTP_STATUS_BY_ERROR = {
    'request_error': 400,
    'auth': 401,
    'not_found': 404,
    'internal': 500,
}

HTTP_STATUS_DESCRIPTION = {
    '200': 'OK',
    '400': 'Invalid request',
    '401': 'Unauthorized',
    '404': 'Not Found',
    '500': 'Internal Server Error',
}

class HybridServer(asyncore.dispatcher, EventEmitter):
    def __init__(self, host='0.0.0.0', port=1234, tcp_backlog=20):
        asyncore.dispatcher.__init__(self)
        EventEmitter.__init__(self)
        self.create_socket(socket.AF_INET, socket.SOCK_STREAM)
        self.set_reuse_addr()
        self.bind((host, port))
        self.listen(tcp_backlog)
        self.clients = {}

    def handle_accept(self):
        pair = self.accept()
        if pair is not None:
            sock, addr = pair
            debug("INFO", "New Incoming connection from {} (fd: {})".format(addr, sock.fileno()))
            client_id = sock.fileno()
            client = HybridServerClient(sock, self)
            self.clients[client_id] = client

    def broadcast(self, message, ignore=[]):
        for id, client in self.clients.items():
            if client.proto == 3 and not id in ignore:
                debug("DBUG", "Broadcasting message to", id)
                client.message(message)

    def remove_user(self, client):
        del self.clients[client.id]


class HybridServerClient(asyncore.dispatcher_with_send, EventEmitter):
    def __init__(self, sock, server):
        self.id = sock.fileno()
        debug("INFO", "NEW CLIENT: ", self.id)
        self.server = server
        self.request = None
        self.proto = None
        self.status = "alive"
        self.processing = False
        self.client_id = None
        self.session_id = None
        asyncore.dispatcher_with_send.__init__(self, sock)
        EventEmitter.__init__(self)
        # Proxy 'request' event to 
        self.on('request', self.process_request)

    def process_request(self, request, error):
        if self.proto is None:
            self.proto = request.proto
        if self.session_id is None:
            self.session_id = request.get_session()
        if self.client_id is None:
            self.client_id = request.get_client()
        self.server.emit('request', self, request, error)
        self.processing = True

    def handle_read(self):
        if self.processing:
            self.request = None
            self.processing = False
        data = None

        # If we don't have a request object yet, create it... then just push data into it (it works like a stream)
        data = self.recv(1024)
        if len(data) < 1:
            return
        used_data = 0

        its = 0
        while len(data) > 0:
            its += 1
            if its > 100:
                debug("CRIT", "Something's wrong on parsing a message. Seems to be in an infinite loop")
                break
            if not self.request or self.request.is_ready:
                # Create a request object
                self.request = HomeSwitchRequest(parent=self) if ord(data[0]) == 3 else HTTPRequest(parent=self)
                self.request.on('ready', lambda: self.emit('request', self.request, None))
                self.request.on('error', lambda description: self.emit('request', self.request, description))
            used_data = self.request.push_data(data)
            data = data[used_data:]

    def handle_error(self):
        debug("INFO", "Client {} crashed".format(self.id))
        debug("DEBUG", "Exception")
        import traceback
        traceback.print_exc()
        debug("DEBUG", "Stack")
        import traceback
        traceback.print_stack()

    def handle_close(self):
        if self.status == "alive":
            debug("INFO", "Client {} has disconnected".format(self.id))
            self.status = "gone"
            self.server.remove_user(self)
            self.close()

    def reply(self, body):
        _body = body.copy()
        if self.request:
            if self.request.id:
                _body['id'] = self.request.id

        return self.message(_body if _body else body)

    def message(self, body):
        proto = "HTTP" if self.proto == "http" else "HS"
        status = "error/"+body.get('error') if body.get('error', None) else 'ok'
        user = self.request.get_user() if self.request.get_user() else 'unidentified'
        client_id = self.request.get_client() if self.request.get_client() else 'unknown-client'
        debug("INFO", "[Client {}] {}/{} => {}; by {} via {}".format(self.id, proto, self.request, status, user, client_id))
        body['when'] = time.time() * 1000
        if self.proto == 3:
            self.send_hs(body)
        else:
            if body.get('error'):
                self.send_http(HTTP_STATUS_BY_ERROR.get(body.get('error'), 500), body)
            else:
                self.send_http(200, body)

    def send_error(self, error):
        if self.proto == 3:
            self.send_hs({error: error})
        else:
            self.send_http(HTTP_STATUS_BY_ERROR[error], error)

    def send_hs(self, body):
        self.fault_tolerant_send(proto.serialise(body))

    def send_http(self, status, body):
        debug("INFO", "Responding to HTTP {} {} with {} ({} bytes)".format(
            self.request.method, self.request.url, status, len(body)
        ))
        raw_body = json.dumps(body)
        response  = "HTTP/1.0 {} {}\r\n".format(status, HTTP_STATUS_DESCRIPTION[str(status)])
        response += "Content-type: application/json\r\n"
        response += "Content-length: {}\r\n".format(len(raw_body))
        response += "\r\n"
        self.fault_tolerant_send(response)
        self.fault_tolerant_send(raw_body)

    def fault_tolerant_send(self, data):
        try:
            self.send(data)
        except socket.error as e:
            if e.args[0] in (ECONNRESET, ENOTCONN, ESHUTDOWN, ECONNABORTED, EPIPE, EBADF): # client went away, just ignore
                return
            if e.errno in (41, ): # might mean the client went away, just ignore
                return
            raise



class HomeSwitchRequest(EventEmitter):
    def __init__(self, raw_request=None, parent=None):
        super(HomeSwitchRequest, self).__init__()
        self.raw_request = ""
        self.headers = None
        self.proto = 3
        self.encryption = None
        self.size = None
        self.is_ready = False
        self.body = None
        self.client_id = parent.client_id if parent else None
        self.session_id = parent.session_id if parent else None
        self.method = None
        self._raw_body = ""
        self._eating_stage = "need_header"
        self._ctx = None

    def push_data(self, data):
        # We need to understand how much data we actually need because perhaps it belongs to another request
        total_data_used = 0
        initial_rr_size = len(self.raw_request)
        self.raw_request += data
        while self._eating_stage != "done" and len(self.raw_request) > 0:
            if self._eating_stage == "need_header":
                if len(self.raw_request) >= 4:
                    self._eat_header(self.raw_request)
                    self._eating_stage = "need_body"
                    self.raw_request = self.raw_request[4:]
                    total_data_used += 4
                else:
                    return 4
            elif self._eating_stage == "need_body":
                # Eat everything that belongs to us
                total_data_used += self._eat_body(self.raw_request)
                self.raw_request = ""
        return total_data_used

    def _eat_header(self, data):
        header = readUInt32BE(data, 0)
        self.encryption = header >> 16 & 0xff
        self.size = header & 0xffff

    def _eat_body(self, data):
        missing = self.size - len(self._raw_body)
        eating = missing if missing <= len(data) else len(data)
        self._raw_body += data[0:eating]
        if len(self._raw_body) >= self.size:
            self._eating_stage = "done"
            self.is_ready = True
            self.body = json.loads(self._raw_body)
            self.method = self.body.get('method', None)
            self.id = self.body.get('id', None)
            if not self.method or not self.id:
                self.emit('error', 'Mandatory request fields were not present')
            else:
                self.emit('ready')
        return eating

        if missing > len(self.raw_request):
                        missing = len(self.raw_request)

    def __repr__(self):
        return "{}".format(self.method)

    def get_user(self):
        return self.body.get('user', None)

    def get_session(self):
        return self.session_id or self.body.get('session', None)

    def get_client(self):
        return self.client_id or self.body.get('client', None)

    def get_ctx(self):
        if self._ctx is None:
            self._ctx = {
                'origin': 'request', # default origin
                'via': self.get_client(),
                'session': self.get_session(),
                'user': self.get_user(),
            }
        return self._ctx


class HTTPRequest(EventEmitter):
    def __init__(self, method=None, url=None, http_version=None, headers=None, raw_request=None, parent=None):
        super(HTTPRequest, self).__init__()
        self.id = None
        self.proto = "http"
        self.is_ready = False
        self.raw_request = ''
        self.method = None
        self.url = None
        self.http_version = None
        self.headers = headers if headers is not None else {}
        self.post_data = ''
        self.body = None
        self._ctx = None
        self._eating_stage = "need_request_line"
#        if raw_request:
#            self._eat_raw_request()

    def push_data(self, data):
        self.raw_request += data
        # FIXME: this is a massive temporary hack. It should support stream parsing
        if len(self.raw_request) > 10:
            self._eat_raw_request()
        return len(data)

    def _eat_raw_request(self):
        debug("DBUG", "HTTP Request:", self.raw_request)
        debug("DBUG", "Starting headers: ", self.headers)
        line_num = 0
        last_crlf = 0
        if self._eating_stage in ("need_request_line", "need_headers"):
            while len(self.raw_request) > 0:
                try:
                    eol = self.raw_request.index("\r\n", last_crlf)
                except ValueError:
                    return
                line = self.raw_request[last_crlf:eol]
    #            debug("DBUG", "Line:", line)
                last_crlf = eol + 2

                # Request line
                if line_num == 0:
                    m = re.search('^(GET|POST|HEAD|PUT|PATCH|DELETE) (\/[^ ]*) (HTTP\/[0-9](?:\.[0-9]+)?)$', line)
                    if not m:
                        raise ValueError('Invalid HTTP request. Could not parse request line: {}'.format(line))
                    self.method = m.group(1)
                    self.url = m.group(2)
                    self.http_version = m.group(3)
                elif line == "":
                    # End of request headers
                    self._eating_stage = "need_body"
                    self.raw_request = self.raw_request[last_crlf:]
                    return self._eat_request_body()
                else:
                    m = re.search('^([\w-]+)\s*:\s*(.*?)\s*$', line)
                    if m:
                        self.headers[m.group(1).lower()] = m.group(2)
                line_num += 1
        elif self._eating_stage == "need_body":
            self._eat_request_body()

    def _eat_request_body(self):
        content_length = self.headers.get('content-length', None)
        if content_length is None:
            self.is_ready = True
            return self.emit('ready')

        self.post_data += self.raw_request
        if len(self.post_data) == int(content_length):
            debug("DBUG", "POST: ", self.post_data)
            if self.headers.get('content-type') != 'application/json':
                return self.emit('error', "Unsupported content-type")
            try:
                self.body = self.post_data = json.loads(self.post_data)
            except Exception as e:
                return self.emit('error', 'Invalid request body')
            self.is_ready = True
            return self.emit('ready')

    def __repr__(self):
        return "{} {}".format(self.method, self.url)

    def get_user(self):
        return self.headers.get('from')

    def get_client(self):
        if self.headers.get('authorization', None):
            try:
                auth = base64.b64decode(re.sub(r'^basic +', '', self.headers.get('authorization'), flags=re.I))
                return re.sub(r':.*', '', auth)
            except Exception as e:
                return None

    def get_session(self):
        return None

    def get_ctx(self):
        if self._ctx is None:
            self._ctx = {
                'origin': 'request', # default origin
                'via': self.get_client(),
                'session': self.get_session(),
                'user': self.get_user(),
            }
        return self._ctx
