import asyncore
import base64
import binascii
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


CMD_CONTROL = 7
PROTOCOL_VERSION_BYTES_31 = b'3.1'
PROTOCOL_VERSION_BYTES_33 = b'3.3'
HEADER_SIZE = 16
PREFIX = "000055aa00000000000000"
SUFFIX = "000000000000aa55"


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



class TuyaDevice(asyncore.dispatcher, EventEmitter):
    def __init__(self, id=None, config={}, hw_metadata={}):
        asyncore.dispatcher.__init__(self)
        EventEmitter.__init__(self)
        self.id = id
        self.config = config
        self.key = config.get('key', None)
        self.ip = config.get('ip', hw_metadata.get('ip', None))
        self.port = config.get('port', 6668)
        self.socket_timeout = config.get('socket_timeout', 2)
        self.version = float(hw_metadata.get('version', '3.3'))
        self.active = hw_metadata.get('active', None)
        self.ablilty = hw_metadata.get('ablilty', None)
        self.encrypt = hw_metadata.get('encrypt', None)
        self.product_key = hw_metadata.get('productKey', None)
        self.gw_id = hw_metadata.get('gwId', None)
        self.dps = str(config.get('dps', 1))
        self.connected = False
        self.command_queue = []
        self.fd = None
        self.buffer = bytearray()

        # If we have an ip, connect right away to it
        if self.gw_id:
            self._connect()

    def update(self, hw_metadata={}):
        ip = hw_metadata.get('ip', None)
        ip_before = self.ip

        if 'ip' in hw_metadata:
            self.ip = hw_metadata.get('ip', self.config.get('ip', None))
        if 'version' in hw_metadata:
            self.version = float(hw_metadata.get('version', '3.3'))
        if 'active' in hw_metadata:
            self.active = hw_metadata.get('active', None)
        if 'ablilty' in hw_metadata:
            self.ablilty = hw_metadata.get('ablilty', None)
        if 'encrypt' in hw_metadata:
            self.encrypt = hw_metadata.get('encrypt', None)
        if 'productKey' in hw_metadata:
            self.product_key = hw_metadata.get('productKey', None)
        if 'gwId' in hw_metadata:
            self.gw_id = hw_metadata.get('gwId', None)

        # Did the IP change? Disconnect and connect to the new one!
        if ip_before != self.ip:
            if ip_before:
                debug("DBUG", "Device {} IP address has changed from {} to {}".format(self.id, ip_before, self.ip))
            else:
                debug("DBUG", "Device {} IP was set to {}".format(self.id, self.ip))
            self._reconnect()

    def send_command(self, command, payload, callback):
        self.command_queue.append({
            'command': command,
            'payload': payload,
            'status': 'waiting',
            'callback': callback,
        })


    def _connect(self):
        debug("DBUG", "IP: {}, PORT: {}, GW_ID: {}, KEY: {}".format(self.ip, self.port, self.gw_id, self.key))
        if self.ip and self.port and self.gw_id and self.key:
            self.create_socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(self.socket_timeout)
            self.fd = self.socket.fileno()
            debug("INFO", "Connecting to device {} at {}:{}...".format(self.id, self.ip, self.port))
            try:
                self.connect((self.ip, self.port))
            except Exception as ex:
                debug("ERRO", "Error connecting to device {} at {}:{}: {}".format(self.id, self.ip, self.port, ex))
                self._disconnect()
        else:
            debug("WARN", "Cannot connect because of not having an ip, port, device id or key")

    def _disconnect(self):
        if self.socket:
            if self.connected:
                debug("INFO", "Disconnecting from device {}...".format(self.id))
            self.close()
        self.connected = False

    def _reconnect(self):
        self._disconnect()
        self._connect()

    def handle_connect(self):
        debug("INFO", "Connected to device {} !".format(self.id))
        self.connected = True
        self.emit('ready')

    def handle_close(self):
        debug("INFO", "Device {} has disconnected".format(self.id))
        if self.connected:
            self._reconnect()

    def handle_expt(self, ex):
        debug("ERRO", "Socket exception on device's {} connection: {}".format(self.id, ex))

    def handle_error(self):
        import sys
        import traceback
        t, v, tb = sys.exc_info()
        debug("ERRO", "Socket error on device's {} connection:".format(self.id), traceback.format_exception(*sys.exc_info()))
        self._disconnect()

    def handle_read(self):
        debug("INFO", "Socket for device's {} should be read".format(self.id))
        while True:
            try:
                reply = self._read_and_parse_message()
                if reply is None:
#                    print("Message is NONE")
                    return
                if type(reply) is str and reply == '':
#                    print("Message is empty")
                    continue
                if type(reply) is not dict:
#                    print("Message is weird")
                    raise Exception('Unexpected message type: {}'.format(type(reply)))
            except ValueError as e:
                debug("ERRO", "Error reading and parsing message:", e)
                debug("WARN", "Marking connection as unhealthy. Reconnecting and resending message!")
                if len(self.command_queue) > 0:
                    msg_obj = self.command_queue[0]
                    if msg_obj.get('status') != 'sent':
                        raise Exception('The first queue message object is NOT in "sent" state. State: {}. Oh god...'.format(msg_obj.get('status')))
                    msg_obj['status'] = 'waiting'
                self._reconnect()

            # Get the sent message object and call its callback
            msg_obj = self.command_queue.pop(0)
            if msg_obj.get('status') != 'sent':
                raise Exception('The first queue message object is NOT in "sent" state. State: {}'.format(msg_obj.get('status')))
            callback = msg_obj.get('callback')
            callback(reply)


    def writable(self):
        is_writeable = len(self.command_queue) > 0 and self.command_queue[0].get('status') == 'waiting'
        debug("DBUG", "IS WRITEABLE ({}:{}): {}".format(self.fd, self.id, is_writeable))
        return is_writeable

    def handle_write(self):
        debug("INFO", "Socket {} for device's {} IS WRITEABLE".format(self.fd, self.id))
        if len(self.command_queue) > 0 and self.command_queue[0].get('status') == 'waiting':
            bin_message = self._serialise_message(self.command_queue[0])
            self.send(bin_message)
            self.command_queue[0]['status'] = 'sent'

    def set_status(self, value, callback):
        if not self.ip:
            raise Exception("Device {} has NO IP address yet. Can't get its status")
        debug("DBUG", "Getting device status to {} (IP: {}, PORT: {}, GW_ID: {}, KEY: {})".format(value, self.ip, self.port, self.gw_id, self.key))
        def set_callback(reply):
            debug("DBUG", "Got device {} status after SET:".format(self.gw_id), reply)
            return callback(reply.get('dps').get(self.dps))

        return self.send_command(7, {
            'gwId':  self.gw_id,
            'devId': self.gw_id,
            'dps':   {str(self.dps): value},
            'uid':   self.gw_id,
        }, set_callback)

    def get_status(self, callback):
        if not self.ip:
            raise Exception("Device {} has NO IP address yet. Can't get its status")
        debug("DBUG", "Getting device status (IP: {}, PORT: {}, GW_ID: {}, KEY: {})".format(self.ip, self.port, self.gw_id, self.key))
        def get_callback(reply):
            debug("DBUG", "Got device {} status:".format(self.gw_id), reply)
            return callback(reply.get('dps').get(self.dps))

        return self.send_command(7, {
            'gwId':  self.gw_id,
            'devId': self.gw_id,
            'dps':   {str(self.dps): None},
            'uid':   self.gw_id,
        }, get_callback)

    def _serialise_message(self, message):
        command = message.get('command')
        payload = message.get('payload')

        command_hb = hex(command)[2:]
        if command < 16:
            command_hb = '0{}'.format(command_hb)
        if 't' not in payload:
            payload['t'] = str(int(time.time()))

        # Serialise the payload and clean it up
        json_payload = json.dumps(payload)
        json_payload = json_payload.replace(' ', '')
        json_payload = json_payload.encode('utf-8')

        if self.version == 3.3:
            cipher = AESCipher(self.key)  # expect to connect and then disconnect to set new
            json_payload = cipher.encrypt(json_payload, False)
            cipher = None
            if command_hb != '0a':
                json_payload = PROTOCOL_VERSION_BYTES_33 + b"\0\0\0\0\0\0\0\0\0\0\0\0" + json_payload
        elif command == CMD_CONTROL:  
            cipher = AESCipher(self.key)
            json_payload = cipher.encrypt(json_payload)
            preMd5String = b'data=' + json_payload + b'||lpv=' + PROTOCOL_VERSION_BYTES_31 + b'||' + self.key
            m = md5()
            m.update(preMd5String)
            hexdigest = m.hexdigest()
            json_payload = PROTOCOL_VERSION_BYTES_31 + hexdigest[8:][:16].encode('latin1') + json_payload

        postfix_payload = hex2bin(bin2hex(json_payload) + SUFFIX)
        assert len(postfix_payload) <= 0xff
        postfix_payload_hex_len = '%x' % len(postfix_payload)  # single byte 0-255 (0x00-0xff)
        buffer = hex2bin(PREFIX + command_hb + '000000' + postfix_payload_hex_len) + postfix_payload
        hex_crc = format(binascii.crc32(buffer[:-8]) & 0xffffffff, '08X')
        return buffer[:-8] + hex2bin(hex_crc) + buffer[-4:]

    def _read_and_parse_message(self):
        # Read the header and parse it
#        print("READING header from {} ({})".format(self.socket.fileno(), self.id))
        header = self._read_need(16)
        if header is None:
            return None

        prefix = readUInt32BE(header, 0)
        sequenceN = readUInt32BE(header, 4)
        commandByte = readUInt32BE(header, 8)
        payloadSize = readUInt32BE(header, 12)
        debug("DBUG", "Got header (prefix: {}, seq: {}, cmd: {}, size: {})".format(prefix, sequenceN, commandByte, payloadSize))

        # Check prefix
        if prefix != readUInt32BE(hex2bin(PREFIX), 0):
            raise ValueError('Unknown prefix {}'.format(prefix))

        # Read payload
#        print("READING payload from {} ({})".format(self.socket.fileno(), self.id))
        payload = self._read_need(payloadSize - 8)
        if payload is None:
            self._read_put_back(header)
            return None

        # Read suffix
#        print("READING suffix from {} ({})".format(self.socket.fileno(), self.id))
        suffix = self._read_need(8)
        if suffix is None:
            self._read_put_back(payload)
            self._read_put_back(header)
            return None

        if suffix[-4:] != hex2bin(SUFFIX[-8:]):
            raise ValueError('Unknown suffix {} vs {}'.format(suffix[-4:], hex2bin(SUFFIX[-8:])))

        returnCode = readUInt32BE(payload, 0)
        if returnCode == 1:
            raise ValueError('Return code is 1. An error has occurred')
        if not returnCode & 0xFFFFFF00:
            payload = payload[4:]

        # If there's nothing left, stop here...
        if len(payload) == 0:
            return ''

        # Skip some things based on the protocol version
        format = 'binary' # if aren't using format for now
        if payload.startswith(str(self.version)):
            if self.version == 3.3:
                payload = payload[15:]
            else:
                payload = payload[19:]
                format = 'base64'

        if payload[0] == ord('{'):
            if not isinstance(payload, str):
                payload = payload.decode()
            try:
                return json.loads(payload)
            except Exception as ex:
                raise ValueError('Error parsing NON encrypted message JSON body: {}'.format(ex))
        elif str(payload).startswith(str(PROTOCOL_VERSION_BYTES_31)):
            payload = payload[len(PROTOCOL_VERSION_BYTES_31):]
            payload = payload[16:]
            return self._decrypt_json(payload, True)
        elif self.version == 3.3:
            return self._decrypt_json(payload, False)
        else:
            raise ValueError("Don't know how to parse messages from this device (version: {})".format(self.version))

        return payload

    def _read_need(self, num_bytes):
        rv = None
        # If it available in the buffer?
        if len(self.buffer) >= num_bytes:
            rv = self.buffer[0:num_bytes]
            del self.buffer[0:num_bytes]
            return rv

        # Read only those bytes into the buffer
        try:
            data = self.recv(num_bytes)
        except socket.timeout as e:
            return None
        self.buffer.extend(data)

        # Check again
        if len(self.buffer) >= num_bytes:
            rv = self.buffer[0:num_bytes]
            del self.buffer[0:num_bytes]
            return rv

        return None

    def _read_put_back(self, data):
        self.buffer = bytearray(data) + self.buffer

    def _decrypt_json(self, data, base64):
        cipher = AESCipher(self.key)
        payload = cipher.decrypt(str(data), base64)
        if not isinstance(payload, bytes):
            payload = payload.decode()
        try:
            payload = json.loads(payload)
        except Exception as ex:
            raise Exception('Error parsing decrypted message JSON body. Perhaps the configured key is wrong')
        return payload


    def __del__(self):
        self._disconnect()


Device = TuyaDevice


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


DeviceListener = TuyaDeviceListener