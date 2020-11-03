from flask import Flask, jsonify
from devices import DeviceListener

from .util import debug


class HomeSwitchAPI(object):
    def __init__(self, host='0.0.0.0', port=7776, processes=None, debug=False):
        self.host = host
        self.port = port
        self.debug = debug
        self.processes = processes
        self.app = Flask(__name__)

        @self.app.route('/')
        def home():
            return jsonify({'order': 'Fot el camp!'})

        @self.app.route('/api/status')
        def status():
            return jsonify({})


    def run(self):
        debug("INFO", "Starting API...")
        self.app.run(
            host=self.host,
            port=self.port,
            debug=self.debug,
            processes=self.processes,
            threaded=True,
        )



def main():
    api = HomeSwitchAPI()
    api.run()