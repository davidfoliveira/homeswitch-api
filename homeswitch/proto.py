import json
from .util import readUInt32BE, writeUInt32BE



def parse_messages(buf, encryption_key=None):
	msg = True
	while msg:
		msg, read_bytes = _parse(buf, encryption_key)
		if msg is None:
			return
		del buf[0:read_bytes]
		yield msg


def serialise(body, encryption_key=None):
    raw_body = json.dumps(body)
    message = bytearray("    "+raw_body)
    writeUInt32BE(message, 0, len(raw_body))
    message[0] = 3 # proto
    message[1] = 0 # encryption
    return message



def parse(message, encryption_key=None):
	msg, _ = _parse(message, encryption_key=encryption_key)
	return msg

def _parse(message, encryption_key=None):
	if len(message) < 4:
		return (None, 0)
	value = readUInt32BE(message, 0)
	proto = message[0]
	encryption = message[1]
	size = value & 0x0000ffff
	if len(message) - 4 < size:
		return (None, 0)
	return (json.loads(str(message[4:4+size])), size + 4)