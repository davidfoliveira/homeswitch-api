import asyncorepp
import json
import time
import traceback

from hybridserver import HybridServer
from hooks import HooksClient

import async
from .device import Device
from .util import debug


class HomeSwitchAPI(object):
    def __init__(self, host='0.0.0.0', port=7776, debug=False, devices={}, hooks_server={}, requires_id=False):
        self.host = host
        self.port = port
        self.debug = debug
        self.server = HybridServer(host=host, port=port)
        self.running = True
        self.devices = devices
        self.hooks_client = HooksClient(hooks_server) if hooks_server else None
        self.requires_id = requires_id
        self.server.on('request', self.on_request)

        # Initialise devices
        for dev_id, config in devices.items():
            if 'hw' not in config:
                raise Exception("Device {} doesn't have a configured hardware type".format(dev_id))
            devices[dev_id] = self._create_device(dev_id, config)

    def _create_device(self, dev_id, config):
        dev = Device(id=dev_id, hw=config.get('hw'), config=config)
        dev.on('status_update', lambda status, origin: self._broadcast_status_update(dev_id, status, origin))
        dev.on('status_update', lambda status, origin: self._run_hooks(dev_id, status, origin))
        return dev

    def _broadcast_status_update(self, dev_id, status, origin):
        dev = self.devices[dev_id]
        self.server.broadcast({'devices': {dev_id: {'status': status, 'origin': origin}}})

    def _run_hooks(self, dev_id, status, origin):
        if self.hooks_client is None:
            return
        print("====== RUN HOOOOKS")
        dev = self.devices[dev_id]
        self.hooks_client.notify('status_update', {
            'device': dev.json(),
            'status': status,
            'origin': origin
        })

    def on_request(self, client, req, error):
        if req.proto == "http":
            debug("DBUG", "[Client {}] Proto {} Request: {} {}".format(client.id, req.proto, req.method, req.url))
        else:
            debug("DBUG", "[Client {}] Proto {} Request: {}".format(client.id, req.proto, req.method), req.body)

        # If we had an error parsing the request, just get rid of it now!
        if error is not None:
            return client.reply({'error': 'request_error', 'description': error})

        # Check ID
        if self.requires_id and not self._request_has_valid_auth(client, req):
            return client.reply({'error': 'auth', 'description': 'Valid identification is required'})

        # If it's an HTTP request, take care of it separately (because we care about URLs and stuff)
        if req.proto == "http":
            return self.on_http_request(client, req, error)
        else:
            return self.on_hs_request(client, req, error)

    def _request_has_valid_auth(self, client, req):
        user = req.get_user()
        return user is not None

    def on_hs_request(self, client, req, error):
        try:
            if req.method == 'get':
                return self.get(client, req)
            if req.method == 'set':
                return self.set(client, req)
            if req.method == 'ping':
                return self.ping(client, req)
        except Exception as e:
            err = {'error': 'internal', 'description': str(e)}
            if self.debug:
                err['stacktrace'] = traceback.format_exc()
            return client.reply(err)

    def on_http_request(self, client, req, error):
        debug("DBUG", "HTTP Request: {} {}:".format(req.method, req.url), req.post_data)
        if req.method == 'POST' and req.url == '/api/device/sync':
            return self.sync(client, req)

        client.reply({'error': 'not_found'})

    def ping(self, client, req):
        return client.reply({'ping': 'ping'})

    def sync(self, client, req):
        for dev_id, value in req.post_data.items():
            # Ignore devices that we didn't configure
            if dev_id in self.devices:
                self.devices[dev_id].update(discovery_status='online', hw_metadata=value)

        for dev_id, value in self.devices.items():
            # If the device is not mentioned, mark it offline
            if dev_id not in req.post_data:
                self.devices[dev_id].update(discovery_status='offline')

        return client.reply({'ok': True})

    def get(self, client, req):
        # Validate
        if 'devices' in req.body and type(req.body.get('devices')) != list:
            return client.reply({'error': 'request_error', 'description': 'Invalid devices `devices` value #1'})

        # If the user didn't ask for a specific device, that means all of them
        devices = self.devices.keys() if 'devices' not in req.body or len(req.body.get('devices')) == 0 else req.body.get('devices')
        if type(devices) is not list:
            return client.reply({'error': 'request_error', 'description': 'Invalid devices `devices` value #2'})

        devices = filter(lambda dev_id: dev_id in self.devices, devices)
        if len(devices) == 0:
            return client.reply({'error': 'not_found', 'description': 'No devices were found'})

        debug("INFO", "Getting status for devices:", devices)

        errors = []
        def reply(err, results):
            if err:
                debug("ERRO", "Error getting device statuses: ", err)
                return client.reply(err)
            if len(errors) > 0:
                debug("WARN", "Found the following errors while getting the status of each device:", errors)

            response = {'devices': {}, 'ok': True}
            for res in results:
                dev_id, status = res
                dev = self.devices[dev_id]
                response['devices'][dev_id] = {
                    'metadata': dev.metadata,
                    'status': status,
                }
            client.reply(response)

        def _get_each_dev_status(dev_id, callback):
            def _on_dev_reply(err, status):
                if err:
                    errors.append(err)
                callback(None, dev_id, None if err else status)
            self.devices[dev_id].get_status(_on_dev_reply, origin='request')
        async.each(devices, _get_each_dev_status, reply)

    def set(self, client, req):
        # Validate and clean up payload
        if 'devices' in req.body and type(req.body.get('devices')) != dict:
            return client.reply({'error': 'request_error', 'description': 'Invalid devices `devices` value'})
        devices = req.body.get('devices')
        if type(devices) is not dict:
            return client.reply({'error': 'request_error', 'description': 'Invalid devices `devices` value #2'})
        device_updates = []
        for dev_id in devices:
            dev_payload = devices[dev_id]
            dev = self.devices.get(dev_id, None)
            # If it's the value directly, move it into an object (the proper format)
            if type(dev_payload) is not dict:
                dev_payload = {'status': dev_payload}
            if dev is None:
                return client.reply({'error': 'request_error', 'description': 'Device {} does not exist'.format(dev_id)})
            status = dev_payload.get('status', None)
            if type(status) is not bool and type(status) is not int and type(status) is not float:
                return client.reply({'error': 'request_error', 'description': 'Invalid status for device {}'.format(dev_id)})
            if dev.activation_key != dev_payload.get('key'):
                debug("WARN", "Excluding device {} from SET because of having wrong activation key".format(dev_id))
                continue
            device_updates.append((dev_id, dev_payload.get('status')))

        errors = []
        def finish(err, results):
            if err:
                debug("ERRO", "Error getting device statuses: ", err)
                return client.reply(err)
            if len(errors) > 0:
                debug("WARN", "Found the following errors while getting the status of each device:", errors)

            response = {'devices': {}}
            for dev_id, status in results:
                response['devices'][dev_id] = {'status': status}
            client.reply(response)

        def _set_each_dev_status(id_status, callback):
            dev_id, status = id_status
            def _on_dev_reply(err, status, intent):
                if err:
                    errors.append(err)
                callback(None, dev_id, None if err else status)
            self.devices[dev_id].set_status(status, _on_dev_reply)

        # Set the status of all devices
        async.each(device_updates, _set_each_dev_status, finish)

    def run(self):
        debug("INFO", "Starting API...")
        asyncorepp.loop(use_poll=True)



def main():
    config = {}
    with open('conf/hsapid.json') as config_file:
        config = json.load(config_file)
    api = HomeSwitchAPI(**config)
    api.run()