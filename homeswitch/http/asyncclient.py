import re
from urlparse import urlparse

from ..asyncsocket.client import AsyncSocketClient
from ..util import debug, DO_NOTHING


class AsyncHTTPClient(object):
	def __init__(self):
		pass
		self.connections = { }

	def get(self, url, headers={}, callback=DO_NOTHING):
		self._request("GET", url=url, headers=headers, callback=callback)

	def post(self, url, headers={}, data=None, callback=DO_NOTHING):
		return self._request("POST", url, headers, data, callback)

	def _request(self, method, url=None, headers={}, data=None, callback=None):
		debug("INFO", "Sending HTTP request {} {}".format(method, url))
		u = urlparse(url)

		host = u.netloc
		port = 80
		if ':' in host:
			host, port = u.netloc.split(':')
		if 'host' not in headers:
			headers['host'] = u.netloc

		request = "{} {} HTTP/1.0\r\n{}\r\n\r\n{}".format(
			method.upper(),
			"{}?{}".format(u.path, u.query) if u.query != '' else u.path,
			'\r\n'.join('{}: {}'.format(header[0].upper()+header[1:], value) for header, value in headers.items()),
			'' if data is None else data
		)
		print(u)
		print(request)

		connection = AsyncSocketClient()
		shared = {'response': None}

		def _on_connect():
			print("Connected!")
			connection.send(request)

		def _on_failure(err):
			print("Failed: ", err)

		def _on_data():
			response = shared.get('response')
			print(connection.socket)
			data = connection.socket.recv(1024)
			print("DATA: ", data)
			if len(data) == 0:
				return
			if response is None:
				response = HTTPClientResponse()
			response.push_data(data)
			if response.is_ready:
				connection.disconnect()
				return callback(None, response)

		connection.once('connect', _on_connect)
		connection.once('failure', _on_failure)
		connection.on('data', _on_data)

		debug("INFO", "Connecting to {}:{}".format(host, port))
		connection.connect(host, port)


class HTTPClientResponse(object):
	def __init__(self):
		self._buffer = ''
		self._eat_state = 'req_line'
		self.is_ready = False
		self.error = None
		self.proto = None
		self.status_code = None
		self.status_description = None
		self.headers = {}
		self.data = None

	def push_data(self, data):
		self._buffer += data
		while len(self._buffer) > 0 and self._eat_state != 'ready':
			if self._eat_state == 'req_line':
				if '\r\n' not in self._buffer:
					break
				line_break = self._buffer.index('\r\n')
				line = self._buffer[0:line_break]
				self._buffer = self._buffer[line_break+2:]
				m = re.search('^(HTTP\/1\.\d)\s+(\d+)\s+(.+)$', line)
				if not m:
					self.error = {'error': 'invalid_req_line', 'description': 'Unable to parse request line'}
					self.is_ready = True
				self.proto = m.group(1)
				self.status_code = m.group(2)
				self.status_description = m.group(3)
				self._eat_state = 'headers'
				self.is_ready = True
				break
#			if self.state == 'headers':
#				while '\r\n' in self._buffer:
#					line_break = self._buffer.index('\r\n')
