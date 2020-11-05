import json
from pymitter import EventEmitter
import os
#import requests
from time import sleep, time
import threading

import requests

from .hw.tuya import TuyaDeviceListener
from .util import debug



class DeviceListener(EventEmitter):
    def __init__(self, **kwargs):
        self.running = False
        self.background_run = None
        self.last_sync = time()
        self.api_url = kwargs.get('api_url', 'http://127.0.0.1:7776')
        self.sync_interval = kwargs.get('sync_interval', 60)
        self.sync_on_changes = kwargs.get('sync_on_changes', True)
        self.sleep_interval = kwargs.get('sleep_interval', 0.1)

        # Create all the listeners
        self.listeners = [
            TuyaDeviceListener(**(kwargs.get('tuya_opts', {})))
        ]

        # Attach events
        super(DeviceListener, self).__init__()
        for listener in self.listeners:
            listener.on('discover', lambda id, m: self._on_new_device(id, m))
            listener.on('lose', lambda id: self._on_lose_device(id))

    def start(self, background=False):
        if self.running:
            return

        # Call the start() methos in all the listeners
        for listener in self.listeners:
            listener.start()

        # Run in a separate thread
        self.running = True
        if background:
            self.background_run = threading.Thread(target=self.run, args=(self, ))
            self.background_run.start()
        else:
            self._run();

    def loop(self):
        # Call the loop() methos in all the listeners
        change_count = 0
        for listener in self.listeners:
            change_count += listener.loop()

        if self.sync_on_changes and change_count > 0:
            debug("INFO", "Sync on changes ({})".format(change_count))
            self._sync()

    def stop(self):
        self.running = False

        # If it's running in background, wait for it to stop
        if self.background_run:
            self.background_run.join()

        # Call the stop() methos in all the listeners
        for listener in self.listeners:
            listener.stop()

    def _run(self, *args):
        while self.running:
            # Run devices loop
            self.loop()

            # Check if we need to sync
            if self.sync_interval and self.last_sync < time() - self.sync_interval:
                debug("DBUG", "Syncing on timeout...")
                self._sync()

            sleep(self.sleep_interval)

    def _on_new_device(self, id, message):
        debug("INFO", "Found device:", id)
        self.emit('discover', id, message)

        if not self.sync_on_changes:
            url = self.api_url + "/api/device/discovery"
            try:
                res = requests.post(url, json = {'new': {'id': id, 'data': message}})
            except Exception as e:
                debug("ERRO", "Failed to call homeswitch-api at {}: {}".format(url, e))
                return

            debug("INFO", "API call: {} [{}]".format(url, res.status_code))

    def _on_lose_device(self, id):
        debug("INFO", "Lost device:", id)
        self.emit('lose', id)

        if not self.sync_on_changes:
            url = self.api_url + "/api/device/discovery"
            try:
                res = requests.post(url, json = {'lost': {'id': id}})
            except Exception as e:
                debug("ERRO", "Failed to call homeswitch-api at {}: {}".format(url, e))
                return

            debug("INFO", "API call: {} [{}]".format(url, res.status_code))

    def _sync(self):
        self.last_sync = time()
        debug("INFO", "Syncing...")

        url = self.api_url + "/api/device/sync"
        try:
            res = requests.post(url, json = self.get_devices())
        except Exception as e:
            debug("ERRO", "Failed to call homeswitch-api at {}: {}".format(url, e))
            return

        debug("INFO", "API call: {} [{}]".format(url, res.status_code))


    def get_devices(self):
        # Get all devices from all the listeners in one dictionary
        devices = {}
        for listener in self.listeners:
            devices.update(listener.get_devices())
        return devices


def main():
    config = {}
    with open('conf/hslookupd.json') as config_file:
        config = json.load(config_file)
    listener = DeviceListener(**config)
    listener.start(background=False)
    listener.stop()