from pymitter import EventEmitter
import socket
import time
import uuid

from .util import DO_NOTHING, debug


class SyncProto(EventEmitter):
    def __init__(self, async_socket, encoder_and_sender, reader_and_decoder, timeout=None):
        EventEmitter.__init__(self)
        self.socket = async_socket
        self.id = None
        self.encode_and_send = encoder_and_sender
        self.receive_and_decode = reader_and_decoder
        self.command_queue = []
        self.buffer = bytearray()

        async_socket.on('connect', self._on_connect)
        async_socket.on('break', self._on_disconnect)
        async_socket.on('disconnect', self._on_disconnect)
        async_socket.on('data', self._on_data)
        self.on('_next', self._on_can_send_next_command)

    def _on_connect(self):
        self.id = '{}:{}'.format(self.socket.ip, self.socket.port)
        debug("DBUG", "Detected connect on socket {}".format(self.id))
        self.emit('_next')

    def _on_disconnect(self):
        # If the connection broke while we were waiting for a reply, change it's status to 'waiting' so it can be resent
        debug("DBUG", "Detected disconnect on socket {}".format(self.id))
        if len(self.command_queue) > 0 and self.command_queue[0].get('status') == 'sent':
            self.command_queue[0]['status'] = 'waiting'

    def _on_data(self):
        while self.socket.connected:
            try:
                reply = self.receive_and_decode(self)
                if reply is None:
                    return
                if type(reply) is str and reply == '':
                    continue
#                if type(reply) is not dict:
#                    print("Message is weird")
#                    raise Exception('Unexpected message type: {}'.format(type(reply)))
            except ValueError as e:
                debug("ERRO", "Error reading and parsing message:", e)
                if len(self.command_queue) > 0:
                    msg_obj = self.command_queue[0]
                    if msg_obj.get('status') != 'sent':
                        raise Exception('The first queue message object is NOT in "sent" state. State: {}. Oh god...'.format(msg_obj.get('status')))
                    msg_obj['status'] = 'waiting'
                self.emit('receive_error', e)

            # Get the sent message object and call its callback
            msg_obj = self.command_queue.pop(0)
            if msg_obj.get('status') != 'sent':
                raise Exception('The first queue message object is NOT in "sent" state. State: {}'.format(msg_obj.get('status')))
            callback = msg_obj.get('callback')
            callback(None, reply)
            self.emit('_next')


    def _on_can_send_next_command(self):
        debug("DBUG", "We can send next command to {}!!!".format(self.id))
        cmd = self._get_next_command()
        if cmd is None:
            debug("DBUG", "No more commands in the queue for {}...".format(self.id))
            return self.emit('drain')

        debug("DBUG", "Sending '{}' command to {}...".format(cmd.get('command'), self.id))
        if cmd.get('status') == 'waiting':
            try:
                self.encode_and_send(cmd.get('message'))
                cmd['status'] = 'sent'
            except socket.error as e:
                debug("DBUG", "Error sending message to device {}: ".format(self.id), e)
                self.emit('send_error', e)
        else:
            debug("WARN", "I was told I could process the next queued item but the item is not in 'waiting' state")

    def _get_next_command(self):
        while len(self.command_queue) > 0:
            cmd = self.command_queue[0]
            print("CMD: ", cmd)
            print("T: ", time.time())
            if cmd.get('expires') is not None:
                if cmd.get('expires') == -1: # already expired and replied
                    debug("WARN", "Found an expired and replied command that should have been sent to {}. Ignoring: ".format(self.id), cmd)
                    self.command_queue.pop(0)
                    continue                    
                if cmd.get('expires') < time.time():
                    debug("WARN", "Found an expired command that should be sent to {}. Ignoring: ".format(self.id), cmd)
                    self.command_queue.pop(0)
                    callback = cmd.get('callback')
                    callback({'error': 'command_timeout', 'descriptor': 'Waited too long for the device to respond'}, None)
                    continue
            return cmd
        return None

    def __len__(self):
        return len(self.command_queue)

    def is_dry(self):
        return len(self.command_queue) == 0

    def go(self):
        return self.emit('_next')

    def flush(self, err=None, reply=None):
        while len(self.command_queue) > 0:
            msg_obj = self.command_queue.pop(0)
            if err is not None or reply is not None:
                callback = msg_obj.get('callback')
                callback(err, reply)

    def append(self, message, callback=DO_NOTHING, timeout=None):
        id = uuid.uuid4()
        self.command_queue.append({
            'id': id,
            'status': 'waiting',
            'message': message,
            'callback': callback,
            'timeout': time.time() + timeout if timeout is not None else None,
        })
        return id

    def read(self, num_bytes):
        rv = None
        # If it available in the buffer?
        if len(self.buffer) >= num_bytes:
            rv = self.buffer[0:num_bytes]
            del self.buffer[0:num_bytes]
            return rv

        # Read only those bytes into the buffer
        try:
            data = self.socket.receive(num_bytes)
        except socket.timeout as e:
            return None
        except socket.error as e:
            if e.errno == 35: # Resource temporarily unavailable
                return None
        self.buffer.extend(data)

        # Check again
        if len(self.buffer) >= num_bytes:
            rv = self.buffer[0:num_bytes]
            del self.buffer[0:num_bytes]
            return rv

        return None

    def put_back(self, data):
        self.buffer = bytearray(data) + self.buffer
