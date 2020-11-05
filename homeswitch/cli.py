import socket
import time
import json

import proto
from .util import writeUInt32BE, bin2hex


def send_test_request():
	#create an INET, STREAMing socket
#	body = json.dumps({'method': 'get'})
#	body = json.dumps({'method': 'set', 'switches': {'bla': True}})

	s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	s.connect(("127.0.0.1", 7776))
	s.send(proto.serialise({'method': 'get'}))
#	s.send(proto.serialise({'method': 'set', 'switches': {'bla': True}}))

	buf = bytearray(0)
	while True:
		read_bytes = s.recv(1000)
		if len(read_bytes) == 0:
			break
		buf.extend(read_bytes)

		for message in proto.parse_messages(buf):
			print("GOT: ", message)

	s.close()


def main():
	send_test_request()