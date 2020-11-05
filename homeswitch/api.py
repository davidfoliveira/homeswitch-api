import asyncore

from devices import DeviceListener
from hybridserver import HybridServer

from .util import debug


class HomeSwitchAPI(object):
    def __init__(self, host='0.0.0.0', port=7776, debug=False):
        self.host = host
        self.port = port
        self.debug = debug
        self.server = HybridServer(host=host, port=port)
        self.running = True

        self.server.on('request', self.on_request)
        # @self.app.route('/')
        # def home():
        #     return jsonify({'order': 'Fot el camp!'})

        # @self.app.route('/api/status')
        # def status():
        #     return jsonify({})

    def on_request(self, client, req, error):
        if req.proto == 3:
            debug("DBUG", "[Client {}] Proto {} Request: {}".format(client.id, req.proto, req.method), req.body)
        else:
            debug("DBUG", "[Client {}] Proto {} Request: {} {}".format(client.id, req.proto, req.method, req.url))

        if error:
            return self.reply({'error': 'request_error'})

        if req.method == 'get':
            client.message({'switches': {'bla': True}})
        if req.method == 'set':
            self.server.broadcast(req.body, ignore=[client.id])
            client.message({'ok': True})



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
    api = HomeSwitchAPI()
    api.run()