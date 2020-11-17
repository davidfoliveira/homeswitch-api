import binascii
import struct
from datetime import datetime
import traceback

def bin2hex(data):
    return binascii.hexlify(data)


def bin2hex_sep(data, split_every):
    hex_data = binascii.hexlify(data)
    return ' '.join([hex_data[i:i+split_every] for i in range(0, len(hex_data), split_every)])


def hex2bin(data):
    return binascii.unhexlify(data)


def int2hex(value):
    return '{0:08X}'.format(value)


def readUInt32BE(data, idx):
    return struct.unpack('>i', data[idx:idx + 4])[0]


def writeUInt32BE(data, idx, value):
    bin_value = UInt32BE(value)
    for i in range(0, 4):
        data[idx+i] = bin_value[i]
    return bin_value


def UInt32BE(value):
    return struct.pack('>i', value)


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


def DO_NOTHING(*args):
    pass


def current_stack():
    return ''.join(traceback.format_stack())