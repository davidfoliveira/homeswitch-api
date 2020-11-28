from importlib import import_module
import json
import socket
import uuid

from ..util import debug, dict_to_obj


class HooksClient(object):
    def __init__(self, config={}):
        self.host = config.get('host', '127.0.0.1')
        self.port = int(config.get('port', '7777'))
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, 0)
        debug("DBUG", "Hooks Client will send data to {}:{}".format(self.host, self.port))

    def notify(self, hook_name, notif_type, data):
        debug("INFO", "Sending a {} / {} hook notification:".format(hook_name, notif_type), data)
        buf = json.dumps({
            'id': str(uuid.uuid4()),
            'hook': hook_name,
            'type': notif_type,
            'data': data
        })
        return self.socket.sendto(
            buf.encode('utf-8'),
            (self.host, self.port)
        )


class HooksServer(object):
    def __init__(self, host="127.0.0.1", port=7777, devices={}, modules={}):
        self.host = host
        self.port = port
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.devices = devices
        self.modules = modules
        self.running = False

        # Load all modules
        for mod_name, mod_conf in modules.items():
            modules[mod_name] = self._import_device_module(mod_name, mod_conf)

    def _import_device_module(self, mod_name, config={}):
        hook_module = import_module("homeswitch.hooks.{}".format(mod_name))
        return hook_module.Hook(config)

    def start(self, background=False):
        if self.running:
            return

        # Start listening
        debug("INFO", "Hooks server listening on {}:{}".format(self.host, self.port))
        self.socket.bind((self.host, self.port))

        # Run in a separate thread
        self.running = True
        if background:
            self.background_run = threading.Thread(target=self.run, args=(self, ))
            self.background_run.start()
        else:
            self.run();

    def loop(self):
        (msg, addr) = self._read_message()
        debug("INFO", "Got message: ", msg)
#        self._store_message(msg)
        self._process_message(msg)
#        self._mark_message(msg, 'done')

    def stop(self):
        self.running = False

        # If it's running in background, wait for it to stop
        if self.background_run:
            self.background_run.join()

    def run(self, *args):
        # Check if there's anything queued to process
#        self._process_queue()

        # Start running
        while self.running:
            # Run devices loop
            self.loop()

    def _read_message(self):
        (msg, addr) = self.socket.recvfrom(8192)
        msg = json.loads(msg)
        return (msg, addr)

    def _process_message(self, message):
        # Get notification type
        msg = HookMessage(message)
        if msg.hook is None:
            debug("WARN", "Got a message without a hook name. Skipping:", message)
            return None
        if msg.hook not in self.modules:
            debug("WARN", "Hook '{}' is not supported. Skipping:".format(msg.hook), message)
            return None
        module = self.modules[msg.hook]

        if msg.type is None:
            debug("WARN", "Got a message without type. Skipping:", message)
            return None

        # Get message data, device and device id
        if msg.data is None or msg.data.device is None or msg.data.device.id is None:
            debug("WARN", "Got a message without device id. Skipping:", message)
            return None
        dev_id = msg.data.device.id

        # Get device settings
        dev_conf = self.devices.get(dev_id, None)
        if dev_conf is None:
            debug("WARN", "Got NO configuration for device {}. Skipping this message".format(dev_id))
            return False
        if msg.hook not in dev_conf:
            debug("WARN", "Got NO device {} configuration for hook '{}'. Skipping this message".format(dev_id, msg.hook))
            return False

        # Call each of the hook module notify() functions
        # try:
        module.notify(msg.type, dev_conf[msg.hook], msg.data)
        # except Exception as e:
        #     debug("ERRO", "Error '{}' processing notification for exception:".format(e), message)

    def _store_message(self, msg):
        pass

    def _mark_message(self, msg, status):
        pass


class HookMessage(object):
    def __init__(self, message):
        self.id = message.get('id', None)
        self.hook = message.get('hook', None)
        self.type = message.get('type', None)
        self.data = HookMessageData(message.get('data'))


class HookMessageData(object):
    def __init__(self, data):
        self.device = HookMessageDevice(data.get('device', {}))
        self.status = data.get('status', None)
        self.ctx = HookMessageContext(data.get('ctx', {}))


class HookMessageDevice(object):
    def __init__(self, device):
        self.id = device.get('id', None)
        self.last_seen = device.get('last_seen', None)
        self.switch_status = device.get('switch_status', None)
        self.discovery_status = device.get('discovery_status', None)
        self.device_status = device.get('device_status', None)
        self.metadata = device.get('metadata', {})
        self.name = self.metadata.get('name', None)


class HookMessageContext(object):
    def __init__(self, ctx):
        self.origin = ctx.get('origin', None)
        self.user = ctx.get('user', None)


def main():
    config = {}
    with open('conf/hshookd.json') as config_file:
        config = json.load(config_file)
    listener = HooksServer(**config)
    listener.start(background=False)
    listener.stop()
