import binascii
from hashlib import md5
import json
import os
from pymitter import EventEmitter
import socket
import sys
import time
import traceback
import uuid

from ..aes import AESCipher
from ..asyncorepp import set_timeout
from ..asyncsocket.client import AsyncSocketClient
from ..util import hex2bin, bin2hex, int2hex, readUInt32BE, UInt32BE, debug, dict_diff, DO_NOTHING, bin2hex_sep
from ..syncproto import SyncProto


Crypto = None
CMD_CONTROL = 7
PROTOCOL_VERSION_BYTES_31 = b'3.1'
PROTOCOL_VERSION_BYTES_33 = b'3.3'
HEADER_SIZE = 16
PREFIX = "000055aa00000000"
SUFFIX = "000000000000aa55"


class TuyaDevice(EventEmitter):
    def __init__(self, id=None, config={}, hw_metadata={}):
        EventEmitter.__init__(self)
        self.id = id
        self.config = config
        self.key = config.get('key', None)
        self.ip = config.get('ip', hw_metadata.get('ip', None))
        self.port = config.get('port', 6668)
        self.socket_timeout = config.get('socket_timeout', 10)
        self.command_timeout = config.get('command_timeout', 5)
        self.version = float(hw_metadata.get('version', '3.3'))
        self.active = hw_metadata.get('active', None)
        self.ablilty = hw_metadata.get('ablilty', None)
        self.encrypt = hw_metadata.get('encrypt', None)
        self.product_key = hw_metadata.get('productKey', None)
        self.gw_id = hw_metadata.get('gwId', None)
        self.dps = str(config.get('dps', 1))
        self.persistent_connections = config.get('persistent_connections', False)
        self.get_status_on_start = config.get('get_status_on_start', True)

        # Creates the connection object and sets event handlers
        self.connection = AsyncSocketClient()
        self.connection.on('connect', self._on_dev_connect)
        self.connection.on('failure', self._on_dev_connection_failure)
        self.connection.on('timeout', self._on_dev_connection_failure)
        self.connection.on('break', self._on_dev_connection_break)
        self.connection.on('disconnect', self._on_dev_disconnect)
        self.connection.on('exception', self._on_dev_exception)
        self.connection.on('error', self._on_dev_error)

        self.connected = False
        self.connecting = False
        self.sync_proto = SyncProto(
            self.connection,
            self._encode_and_send_message,
            self._read_and_parse_message,
        )
        self.sync_proto.on('drain', self._on_dev_send_drain)
        self.sync_proto.on('send_error', self._on_dev_send_error)
        self.sync_proto.on('receive_error', self._on_dev_recv_error)

        # When IP address changes
        self.on('_ip', self._on_ip_change)

        # Connect to the device right away if persistent_connections is ON
        if self.gw_id and self.ip:
            self.emit('_ip')

    def _on_ip_change(self):
        # If connected, disconnect
        # We will later connect to the new IP in case there's something in the queue or persistent_connections are on
        self._disconnect()

        # Be super sure we can connect
        if self.gw_id and self.ip:
            if self.persistent_connections:
                debug("INFO", "Connecting to the device as persistent_connections is ON")
                self._connect()
            elif not self.sync_proto.is_dry():
                self._connect()
            if self.get_status_on_start:
               debug("INFO", "Getting device's status on start...")
               self.get_status(origin='online')

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
                debug("DBUG", "Tuya device {} IP address has changed from {} to {}".format(self.id, ip_before, self.ip))
            else:
                debug("DBUG", "Tuya device {} IP was set to {}".format(self.id, self.ip))

            if self.gw_id and self.ip:
                self.emit('_ip')

    def send_command(self, command, payload, callback):
        was_dry = self.sync_proto.is_dry()
        self.sync_proto.append(
            message={'command': command, 'payload': payload},
            callback=callback,
            timeout=self.command_timeout
        )

        # If not connected and not connecting, connect! Connect will take care of processing the queue
        debug("DBUG", "Device {} Connecting={}, Connected={}".format(self.id, self.connecting, self.connected))
        if not self.connected and not self.connecting:
            return self._connect()

        # If connected but the queue was empty, start processing it
        if self.connected and was_dry:
            return self.sync_proto.go()

    def _connect(self):
        debug("DBUG", "IP: {}, PORT: {}, GW_ID: {}".format(self.ip, self.port, self.gw_id))
        if self.ip and self.port and self.gw_id and self.key:
            debug("INFO", "Connecting to Tuya device {} at {}:{}...".format(self.id, self.ip, self.port))
            self.connecting = True
            self.connection.connect(self.ip, self.port, timeout=self.socket_timeout)
            debug("DBUG", "Connection to Tuya device {} at {}:{} for file descriptor {}".format(self.id, self.ip, self.port, self.connection.fd))
        else:
            debug("WARN", "Cannot connect because of not having an ip, port, device id or key")

    def _disconnect(self):
        if self.connected or self.connecting:
            debug("INFO", "Disconnecting from Tuya device {}...".format(self.id))
            self.connected = False
            self.connection.disconnect()

    def _reconnect(self):
        debug("INFO", "Reconnecting to {}...".format(self.id))
        self._disconnect()
        self._connect()

    def _on_dev_connect(self):
        debug("INFO", "Connected to Tuya device {} !".format(self.id))
        self.connected = True
        self.connecting = False
        self.emit('_next')

    def _on_dev_connection_failure(self, ex):
        debug("WARN", "Failure while connecting to Tuya device {}:".format(self.id), ex)
        self.connecting = False
        self.connected = False
        # If persistent connections are on, keep trying to connect...
        if self.persistent_connections:
            return self._connect()

        # Otherwise, return an error to each command waiting in the queue
        # TODO: change me according to retry policy. Some parts of the code retry forever, others fail immediately
        self.sync_proto.flush(
            {'error': 'connect_timeout', 'description': 'Failure connecting to device {}'.format(self.id)},
            None
        )

    def _on_dev_connection_break(self):
        debug("INFO", "Device {} has disconnected.".format(self.id))
        if self.connected:
            set_timeout(self._reconnect, 1)

    def _on_dev_disconnect(self):
        debug("INFO", "Successfully disconnected from device {}".format(self.id))

    def _on_dev_exception(self, ex):
        debug("ERRO", "Socket exception on device's {} connection: {}".format(self.id, ex))

    def _on_dev_error(self, t, v, tb):
        debug("ERRO", "Socket error on device's {} connection:".format(self.id), traceback.format_exception(*sys.exc_info()))
        self._disconnect()

    def _on_dev_send_drain(self):
        debug("INFO", "Tuya device {} send queue has drained".format(self.id))
        if not self.persistent_connections:
            debug("INFO", "Disconnecting as command queue is empty")
            self._disconnect()

    def _on_dev_send_error(self, err):
        debug("DBUG", "Tuya device {} send error".format(self.id), err)
        if err.errno in (41): # might mean the device went away, we need to reconnect and retry
            return self._reconnect()

    def _on_dev_recv_error(self, err):
        debug("INFO", "Tuya device {} receive error".format(self.id), err)
        debug("WARN", "Marking connection as unhealthy. Reconnecting and resending message!")
        self._reconnect()

    def set_status(self, value, callback=DO_NOTHING):
        if not self.ip:
            raise Exception("Device {} has NO IP address yet. Can't get its status")
        debug("DBUG", "Setting Tuya device status to {} (IP: {}, PORT: {}, GW_ID: {})".format(value, self.ip, self.port, self.gw_id))
        return self.send_command(7, {
            'gwId':  self.gw_id,
            'devId': self.gw_id,
            'dps':   {str(self.dps): value},
            'uid':   self.gw_id,
        }, lambda err, reply: self._set_status_callback(err, reply, callback))

    def _set_status_callback(self, err, reply, callback):
        if err:
            debug("DBUG", "Error setting device {} status:".format(self.gw_id), err)
            return callback(err, None)
        debug("DBUG", "Got device {} status after SET:".format(self.gw_id), reply)
        status = reply.get('dps').get(self.dps)
        self.emit('status_update', status, 'set')
        return callback(None, status)

    def get_status(self, callback=DO_NOTHING, origin='UNKWNOWN'):
        if not self.ip:
            raise Exception("Device {} has NO IP address yet. Can't get its status")
        debug("DBUG", "Getting Tuya device status (IP: {}, PORT: {}, GW_ID: {})".format(self.ip, self.port, self.gw_id))

        return self.send_command(7, {
            'gwId':  self.gw_id,
            'devId': self.gw_id,
            'dps':   {str(self.dps): None},
            'uid':   self.gw_id,
        }, lambda err, reply: self._get_status_callback(err, reply, callback, origin))

    def _get_status_callback(self, err, reply, callback, origin):
        if err:
            debug("ERRO", "Error getting Tuya device {} status:".format(self.gw_id), err)
            return callback(err, None)

        debug("DBUG", "Got device {} status:".format(self.gw_id), reply)
        status = reply.get('dps').get(self.dps)
        self.emit('status_update', status, origin)
        return callback(None, status)

    def _encode_and_send_message(self, message):
        return self.connection.send(self._serialise_message(message))

    def _serialise_message(self, message):
        command = message.get('command')
        payload = message.get('payload')
        sequence_num = message.get('sequenceN', 0)

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
            hexdigest = md5(preMd5String).hexdigest()
            json_payload = PROTOCOL_VERSION_BYTES_31 + hexdigest[8:][:16].encode('latin1') + json_payload

        postfix_payload = hex2bin(bin2hex(json_payload) + SUFFIX)
        assert len(postfix_payload) <= 0xff
        postfix_payload_hex_len = '%x' % len(postfix_payload)  # single byte 0-255 (0x00-0xff)

        buffer = bytearray()
        buffer.extend(hex2bin(PREFIX[0:8]))            # prefix
        buffer.extend(UInt32BE(sequence_num))          # seq_number
        buffer.extend(UInt32BE(command))               # command
        buffer.extend(UInt32BE(len(postfix_payload)))  # payload length
        buffer.extend(postfix_payload)
        hex_crc = format(binascii.crc32(buffer[:-8]) & 0xffffffff, '08X')
        return buffer[:-8] + hex2bin(hex_crc) + buffer[-4:]

    def _read_and_parse_message(self, proto):
        # Read the header and parse it
#        print("READING header from {} ({})".format(self.socket.fileno(), self.id))
        header = proto.read(16)
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
        payload = proto.read(payloadSize - 8)
        if payload is None:
            proto.put_back(header)
            return None

        # Read suffix
#        print("READING suffix from {} ({})".format(self.socket.fileno(), self.id))
        suffix = proto.read(8)
        if suffix is None:
            proto.put_back(payload)
            proto.put_back(header)
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
        self.key = md5(str(udp_key)).digest() if udp_key else None
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
            if e.errno in (35, 11):
                return 0
            raise e

        data = bytesAddressPair[0]
        address = bytesAddressPair[1]

        # Parse messages and process them
        change_count = 0
        for m in self._parse_messages(data):
#            m.payload['ip'] = m.payload['ip'].replace('.10.', '.11.') # TODO: remove me, just for making connects fail
#            print("M: ", m)
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
