import asyncorepp
import json
import time

from hybridserver import HybridServer

import async
from .device import Device
from .util import debug


class HomeSwitchAPI(object):
    def __init__(self, host='0.0.0.0', port=7776, debug=False, devices={}):
        self.host = host
        self.port = port
        self.debug = debug
        self.server = HybridServer(host=host, port=port)
        self.running = True
        self.devices = devices
        self.server.on('request', self.on_request)

        # Initialise devices
        for dev_id, config in devices.items():
            if 'hw' not in config:
                raise Exception("Device {} doesn't have a configured hardware type".format(dev_id))
            devices[dev_id] = self._create_device(dev_id, config)

    def _create_device(self, dev_id, config):
        dev = Device(id=dev_id, hw=config.get('hw'), config=config)
        dev.on('status_update', lambda status, origin: self._broadcast_status_update(dev_id, status, origin))
        return dev

    def _broadcast_status_update(self, dev_id, status, origin):
        dev = self.devices[dev_id]
        self.server.broadcast({'devices': {dev_id: {'status': status, 'origin': origin}}})

    def on_request(self, client, req, error):
        if req.proto == 3:
            debug("DBUG", "[Client {}] Proto {} Request: {}".format(client.id, req.proto, req.method), req.body)
        else:
            debug("DBUG", "[Client {}] Proto {} Request: {} {}".format(client.id, req.proto, req.method, req.url))

        # If we had an error parsing the request, just get rid of it now!
        if error:
            return client.message({'error': 'request_error'})

        # If it's an HTTP request, take care of it separately (because we care about URLs and stuff)
        if req.proto == "http":
            return self.on_http_request(client, req, error)

        try:
            if req.method == 'get':
                return self.get(client, req)

            if req.method == 'set':
#                def reply(dev, status, intent):
#                    self.server.broadcast({'devices': {dev.id: status}})
                status = req.body.get('switches').get('bf5d0abdb1e6210180duku')
                self.devices['bf5d0abdb1e6210180duku'].set_status(status)
        except Exception as e:
            return client.message({'error': 'internal', 'description': str(e)})


    def on_http_request(self, client, req, error):
        debug("DBUG", "HTTP Request: {} {}:".format(req.method, req.url), req.post_data)
        if req.method == 'POST' and req.url == '/api/device/sync':
            for dev_id, value in req.post_data.items():
                # Ignore devices that we didn't configure
                if dev_id in self.devices:
                    self.devices[dev_id].update(discovery_status='online', hw_metadata=value)

            for dev_id, value in self.devices.items():
                # If the device is not mentioned, mark it offline
                if dev_id not in req.post_data:
                    self.devices[dev_id].update(discovery_status='offline')

            client.message({'ok': True})

        client.message({'error': 'not_found'})
#            self.devices = req.post_data

    def get(self, client, req):
            def reply(results):
                response = {'devices': {}, 'ok': True}
                for res in results:
                    dev, status = res
                    response['devices'][dev.id] = {
                        'metadata': dev.metadata,
                        'status': status,
                    }
                client.message(response)

            # Validate
            if 'devices' in req.body and type(req.body.get('devices')) != list:
                return client.message({'error': 'request_error', 'description': 'Invalid devices `field` value'})

            # If the user didn't ask for a specific device, that means all of them
            devices = self.devices.keys() if 'devices' not in req.body or len(req.body.get('devices')) == 0 else req.body.get('devices')
            devices = filter(lambda dev_id: dev_id in self.devices, devices)
            if len(devices) == 0:
                return client.message({'error': 'not_found', 'description': 'No devices were found'})

            debug("INFO", "Getting status for devices:", devices)

            async.each(devices, lambda dev_id, callback: self.devices[dev_id].get_status(callback, origin='request'), reply)


    def run(self):
        debug("INFO", "Starting API...")
        asyncorepp.loop()
#        while self.running:
#            self.loop()
#        self.app.run(
#            host=self.host,
#            port=self.port,
#            debug=self.debug,
#            processes=self.processes,
#            threaded=True,
#        )


def main():
    config = {}
    with open('conf/hsapid.json') as config_file:
        config = json.load(config_file)
    api = HomeSwitchAPI(**config)
    api.run()