import base64
from hashlib import md5
import json
import os
import socket
import time
from pymitter import EventEmitter

from ..util import hex2bin, bin2hex, int2hex, readUInt32BE, debug, dict_diff

# Import Crypto.Cipher.AES (from PyCrypto) or pyaes
try:
    import Crypto
    from Crypto.Cipher import AES
except ImportError:
    Crypto = AES = None
    import pyaes  # https://github.com/ricmoo/pyaes


HEADER_SIZE = 16



## Cryptography Helpers
class AESCipher(object):
    def __init__(self, key):
        self.bs = 16
        self.key = key

    def encrypt(self, raw, use_base64 = True):
        if Crypto:
            raw = self._pad(raw)
            cipher = AES.new(self.key, mode=AES.MODE_ECB)
            crypted_text = cipher.encrypt(raw)
        else:
            _ = self._pad(raw)
            cipher = pyaes.blockfeeder.Encrypter(pyaes.AESModeOfOperationECB(self.key))
            crypted_text = cipher.feed(raw)
            crypted_text += cipher.feed()

        if use_base64:
            return base64.b64encode(crypted_text)
        else:
            return crypted_text

    def decrypt(self, enc, use_base64=True):
        if use_base64:
            enc = base64.b64decode(enc)

        if Crypto:
            cipher = AES.new(self.key, AES.MODE_ECB)
            raw = cipher.decrypt(enc)
            return self._unpad(raw).decode('utf-8')
        else:
            cipher = pyaes.blockfeeder.Decrypter(pyaes.AESModeOfOperationECB(self.key))
            plain_text = cipher.feed(enc)
            plain_text += cipher.feed()
            return plain_text

    def _pad(self, s):
        padnum = self.bs - len(s) % self.bs
        return s + padnum * chr(padnum).encode()

    @staticmethod
    def _unpad(s):
        return s[:-ord(s[len(s)-1:])]



class TuyaUDPMessage(object):
    def __init__(self, payload=None, leftover=None, commandByte=None, sequenceN=None):
        self.payload = payload
        self.leftover = leftover
        self.commandByte = commandByte
        self.sequenceN = sequenceN



class TuyaDeviceListener(EventEmitter):
    def __init__(self, host='0.0.0.0', port=6667, udp_key=None, unseen_timeout=86400):
        debug("INFO", "TuyaDeviceListener: Created")
        super(TuyaDeviceListener, self).__init__()

        self.host = host
        self.port = port
        self.key = md5(udp_key).digest() if udp_key else None
        self.unseen_timeout = unseen_timeout
        self.socket = socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM)
        self.socket.setblocking(0)
        self.cipher = AESCipher(self.key)
        self.devices = {}
        self.device_last_seen = {}


    def get_devices(self):
        return self.devices


    def start(self):
        debug("INFO", "TuyaDeviceListener: Starting...")
        debug("INFO", "TuyaDeviceListener: Binding on {}:{}".format(self.host, self.port))
        self.socket.bind((self.host, self.port))


    def loop(self):
        # Just read data from the UDP socket
        change_count = self._read()

        # Cleanup unseen devices
        change_count += self._cleanup()

        return change_count


    def _read(self):
        # Try to read a message
        try:
            bytesAddressPair = self.socket.recvfrom(1024)
        except socket.error as e:
            # No data
            if e.errno == 35:
                return 0
            raise e

        data = bytesAddressPair[0]
        address = bytesAddressPair[1]

        # Parse messages and process them
        change_count = 0
        for m in self._parse_messages(data):
            change_count += self._process_message(m.payload, address)

        return change_count


    def _process_message(self, message, address):
        dev_id = message.get('gwId')
        if not dev_id:
            debug("WARN", "TuyaDeviceListener: Found no device ID. Ignoring: {}".format(message))
            return

        news_count = 0
        if dev_id not in self.devices:
            self.devices[dev_id] = message
            self.emit('discover', dev_id, message)
            self.devices[dev_id] = message
            news_count += 1
        else:
            diffs = dict_diff(self.devices[dev_id], message)
            self.emit('change', dev_id, message)
            if len(diffs) > 0:
                news_count += 1
        self.device_last_seen[dev_id] = time.time()

        return news_count


    def _cleanup(self):
        now = time.time()
        change_count = 0
        for dev_id, ts in self.device_last_seen.items():
            if ts < now - self.unseen_timeout:
                self.emit('lose', dev_id)
                del self.device_last_seen[dev_id]
                del self.devices[dev_id]
                change_count += 1

        return change_count


    def _parse_messages(self, message):
        if self.key:
            if len(self.key) != 16:
                raise Exception('Incorrect key format')
        return self.parse_recursive(message, [])


    def parse_recursive(self, message, packets):
        result = self.parse_packet(message)
        result.payload = self.get_payload(result.payload)
        packets.append(result)
        if result.leftover:
            return self.parse_recursive(result.leftover, packets)
        return packets


    def parse_packet(self, buffer):
        if len(buffer) < 24:
            raise Exception('Packet too short. Length: {}.'.format(len(buffer)))

        prefix = readUInt32BE(buffer, 0)
        if prefix != 0x000055AA:
            raise Exception('Prefix does not match: {} vs {}.'.format('000055AA', int2hex(prefix)))

        leftover = None

        suffix_loc = buffer.index(hex2bin('0000AA55'), 0)
        if suffix_loc != len(buffer) - 4:
            leftover = buffer[suffix_loc:suffix_loc + 4]
            buffer = buffer[0:suffix_loc + 4]

        suffix = readUInt32BE(buffer, len(buffer) - 4)
        if suffix != 0x0000AA55:
            raise Exception('Suffix does not match: {}'.format('0000AA55', bin2hex(suffix)))

        sequenceN = readUInt32BE(buffer, 4)
        commandByte = readUInt32BE(buffer, 8)
        payloadSize = readUInt32BE(buffer, 12)

        # Check for payload
        if len(buffer) - 8 < payloadSize:
            raise Exception('Packet missing payload: payload has length {}.'.format(payloadSize))

        returnCode = readUInt32BE(buffer, 16)

        payload = ''
        if returnCode & 0xFFFFFF00:
            payload = buffer[HEADER_SIZE:HEADER_SIZE + payloadSize - 8]
        else:
            payload = buffer[HEADER_SIZE + 4:HEADER_SIZE + payloadSize - 8]

        # Check CRC
        # expectedCrc = readUInt32BE(buffer, HEADER_SIZE + payloadSize - 8)
        # computedCrc = crc(buffer.slice(0, payloadSize + 8));
        # if expectedCrc != computedCrc:
        #     raise Exception('CRC mismatch: expected {}, was {}. '.format(expectedCrc, computedCrc));

        return TuyaUDPMessage(payload=payload, leftover=leftover, commandByte=commandByte, sequenceN=sequenceN)

    def get_payload(self, data):
        if len(data) == 0:
            return False

        return json.loads(self.cipher.decrypt(data, False))

    def stop(self):
        debug("INFO", "TuyaDeviceListener: Stopping...", os.getpid())
        self.socket.close()
