import asyncore
import json
import time

from hybridserver import HybridServer

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
            devices[dev_id] = Device(id=dev_id, hw=config.get('hw'), config=config)

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


        if req.method == 'get':
            def reply(dev, status):
                print("REPLY")
                client.message({'devices': {dev.id: status}})
            self.devices['bf4a36374de48f83d8vd9g'].get_status(reply)
#            self.devices[]

        if req.method == 'set':
            def reply(dev, status, intent):
                print("REPLY")
                self.server.broadcast({'devices': {dev.id: status}})
            status = req.body.get('switches').get('bf4a36374de48f83d8vd9g')
            self.devices['bf4a36374de48f83d8vd9g'].set_status(status, reply)

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
#            print("UPDATE DEVS: ", req.post_data)
            client.message({'ok': True})

        client.message({'error': 'not_found'})
#            self.devices = req.post_data


    def run(self):
        debug("INFO", "Starting API...")
        asyncore.loop()
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