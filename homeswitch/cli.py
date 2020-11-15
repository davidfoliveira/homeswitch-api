import socket
import time
import json
import sys

import proto
from .util import writeUInt32BE, bin2hex


def send_test_request(args):
	#create an INET, STREAMing socket
#	body = json.dumps({'method': 'get'})
#	body = json.dumps({'method': 'set', 'switches': {'bf5d0abdb1e6210180duku': True}})

	s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	s.connect(("127.0.0.1", 7776))
	if len(args) > 1 and args[0] == 'set':
		status = args[1] == 'on'
		s.send(proto.serialise({'method': 'set', 'switches': {'bf5d0abdb1e6210180duku': status}, 'id': 123}))
	else:
		s.send(proto.serialise({'method': 'get'}))

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