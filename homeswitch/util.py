import binascii
import struct
from datetime import datetime


def bin2hex(data):
    return binascii.hexlify(data)


def hex2bin(data):
    return binascii.unhexlify(data)


def int2hex(value):
    return '{0:08X}'.format(value)


def readUInt32BE(data, idx):
    return struct.unpack('>i', data[idx:idx + 4])[0]


def debug(type, pattern, *args):
    pattern = '{}: [{}] ' + pattern
    for arg in args:
        pattern += ' {}'

    values = [type]
    values.extend(args)
    values.insert(0, str(datetime.utcnow())+'Z')
    print(pattern.format(*values))


def dict_diff(a, b):
    diffs = {}
    for key in a:
        if key not in b or a[key] != b[key]:
            diffs[key] = b.get(key, None)
    for key in b:
        if key not in a:
            diffs[key] = b.get(key, None)

    return diffs
