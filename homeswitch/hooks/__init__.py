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

    def notify(self, notif_type, data):
        debug("INFO", "Sending a {} notification:".format(notif_type), data)
        buf = json.dumps({'id': str(uuid.uuid4()), 'type': notif_type, 'data': data})
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
        msg = dict_to_obj(message)

        notif_type = msg.type
        if notif_type is None:
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

        # Call each of the hook module notify() functions
        for mod_name, settings in dev_conf.items():
            module = self.modules[mod_name]
#            try:
            module.notify(notif_type, settings, msg.data)
            # except Exception as e:
            #     debug("ERRO", "Error '{}' processing notification for exception:".format(e), message)

    def _store_message(self, msg):
        pass

    def _mark_message(self, msg, status):
        pass


def main():
    config = {}
    with open('conf/hshookd.json') as config_file:
        config = json.load(config_file)
    listener = HooksServer(**config)
    listener.start(background=False)
    listener.stop()
