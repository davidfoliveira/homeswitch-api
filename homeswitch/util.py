import binascii
import struct
from datetime import datetime
import traceback
import sys


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


def ucfirst(value):
    return value[0].upper()+value[1:]


def debug(type, pattern, *args):
    pattern = '{}: [{}] ' + pattern.replace('{', '{{').replace('}', '}}')
    for arg in args:
        pattern += ' {}'

    values = [type]
    values.extend(args)
    values.insert(0, str(datetime.utcnow())+'Z')
    print(pattern.format(*values))
    sys.stdout.flush()


def dump(type, data):
    print('{}: [{}] '.format(type, str(datetime.utcnow())+'Z')+data)


def dict_diff(a, b):
    diffs = {}
    for key in a:
        if key not in b or a[key] != b[key]:
            diffs[key] = b.get(key, None)
    for key in b:
        if key not in a:
            diffs[key] = b.get(key, None)

    return diffs


def dict_to_obj(input):
    return Bunch(input)


def DO_NOTHING(*args):
    pass


def current_stack():
    return ''.join(traceback.format_stack())


class Bunch:
    def __init__(self, data_dict):
        for p, v in data_dict.items():
            if type(v) is dict:
                data_dict[p] = Bunch(v)
        self.__dict__.update(data_dict)
