import socket
import time
import json
import sys

import proto
from .util import writeUInt32BE, bin2hex


def send_test_request(args):
	#create an INET, STREAMing socket
#	body = json.dumps({'method': 'get'})
#	body = json.dumps({'method': 'set', 'devices': {'bf5d0abdb1e6210180duku': True}})
	ip, command = args[0:2]

	s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	s.connect((ip, 7776))
	if command == 'set':
		device, status = args[2:4]
		status = status == 'on'
		s.send(proto.serialise({'method': 'set', 'devices': {device: status}, 'user': 'test'}))
	else:
		s.send(proto.serialise({'method': 'get', 'user': 'test'}))

	buf = bytearray(0)
	while True:
		read_bytes = s.recv(1000)
		if len(read_bytes) == 0:
			break
		buf.extend(read_bytes)

		for message in proto.parse_messages(buf):
			print(json.dumps(message, indent=4, sort_keys=True))
			print('')

	s.close()


def main():
	send_test_request(sys.argv[1:])