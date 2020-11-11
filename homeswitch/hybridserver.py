import re
import asyncore
import socket
import json
from pymitter import EventEmitter
import time

import proto
from .util import debug, readUInt32BE, writeUInt32BE


HTTP_STATUS_BY_ERROR = {
    'request_error': 400,
    'not_found': 404,
    'internal': 500,
}

HTTP_STATUS_DESCRIPTION = {
    '200': 'OK',
    '400': 'Invalid request',
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
        asyncore.dispatcher_with_send.__init__(self, sock)
        EventEmitter.__init__(self)
        # Proxy 'request' event to 
        self.on('request', self.process_request)

    def process_request(self, request, error):
        if self.proto == None:
            self.proto = request.proto
        self.server.emit('request', self, request, error)
        self.request = None

    def handle_read(self):
        data = None

        # If we don't have a request object yet, create it... then just push data into it (it works like a stream)
        if not self.request:
            data = self.recv(1)
            if len(data) < 1:
                return
            # Create a request object
            self.request = HomeSwitchRequest() if ord(data[0]) == 3 else HTTPRequest()
            self.request.on('ready', lambda: self.emit('request', self.request, False))
            self.request.on('error', lambda: self.emit('request', self.request, True))
        else:
            data = self.recv(1024)
            if len(data) < 1:
                return
        self.request.push_data(data)

    def handle_error(self):
        debug("INFO", "Client {} crashed".format(self.id))
        import traceback
        traceback.print_stack()

    def handle_close(self):
        if self.status == "alive":
            debug("INFO", "Client {} has disconnected".format(self.id))
            self.status = "gone"
            self.server.remove_user(self)
            self.close()

    def message(self, body):
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
        self.send(proto.serialise(body))

    def send_http(self, status, body):
        raw_body = json.dumps(body)
        response  = "HTTP/1.0 {} {}\r\n".format(status, HTTP_STATUS_DESCRIPTION[str(status)])
        response += "Content-type: application/json\r\n"
        response += "Content-length: {}\r\n".format(len(raw_body))
        response += "\r\n"
        self.send(response)
        self.send(raw_body)


class HomeSwitchRequest(EventEmitter):
    def __init__(self, raw_request=None):
        super(HomeSwitchRequest, self).__init__()
        self.raw_request = ""
        self.proto = 3
        self.encryption = None
        self.size = None
        self.body = None
        self.method = None
        self._raw_body = ""
        self._eating_stage = "need_header"

    def push_data(self, data):
        self.raw_request += data
        while self._eating_stage != "done" and len(self.raw_request) > 0:
            if self._eating_stage == "need_header":
                if len(self.raw_request) >= 4:
                    self._eat_header(self.raw_request)
                    self._eating_stage = "need_body"
                    self.raw_request = self.raw_request[4:]
                else:
                    return
            elif self._eating_stage == "need_body":
                if len(self.raw_request) > 0:
                    self._raw_body += self.raw_request
                    self.raw_request = ""
                    if len(self._raw_body) >= self.size:
                        self._eating_stage = "done"
                        self.body = json.loads(self._raw_body)
                        self.method = self.body.get('method')
                        if not self.method:
                            self.emit('error')
                        else:
                            self.emit('ready')
                    return

    def _eat_header(self, data):
        header = readUInt32BE(data, 0)
        self.encryption = header >> 16 & 0xff
        self.req_size = header & 0xffff



class HTTPRequest(EventEmitter):
    def __init__(self, method=None, url=None, http_version=None, headers={}, raw_request=None):
        super(HTTPRequest, self).__init__()
        self.proto = "http"
        self.raw_request = ''
        self.method = None
        self.url = None
        self.http_version = None
        self.headers = headers
        self.post_data = None
#        if raw_request:
#            self._eat_raw_request()

    def push_data(self, data):
        self.raw_request += data
        # FIXME: this is a massive temporary hack. It should support stream parsing
        if len(self.raw_request) > 10:
            self._eat_raw_request()

    def _eat_raw_request(self):
        print("ALL: ", self.raw_request)
        line_num = 0
        last_crlf = 0
        while True:
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
                return self._eat_request_body(last_crlf)
            else:
                m = re.search('^([\w-]+)\s*:\s*(.*?)\s*$', line)
                if m:
                    self.headers[m.group(1).lower()] = m.group(2)

            line_num += 1

    def _eat_request_body(self, pos):
        if len(self.raw_request) > pos:
            self.post_data = self.raw_request[pos:]
#            debug("DBUG", "POST: ", self.post_data)
            if self.headers.get('content-type') != 'application/json':
                return self.emit('error')
            try:
                self.post_data = json.loads(self.post_data)
            except Exception:
                return self.emit('error')

        self.emit('ready')
