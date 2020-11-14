import time
from importlib import import_module
from pymitter import EventEmitter

import asyncorepp
from .hw import tuya
from .util import debug, DO_NOTHING

DEVICE_CONTRUCTORS = {
    "tuya": tuya.TuyaDevice,
}


class Device(EventEmitter):
    def __init__(self, id=None, hw=None, config={}, discovery_status='offline', switch_status=None, hw_metadata={}, last_seen=None, **kwargs):
        EventEmitter.__init__(self)
        self.id = id
        self.discovery_status = discovery_status
        self.switch_status = None
        self.last_status_update = 0
        self.hw_metadata = hw_metadata
        self.last_seen = last_seen
        self.metadata = config.get('metadata', {})
        self.status_cache = config.get('status_cache', None)
        self.refresh_status = int(config.get('refresh_status', None))
        self.config = config
        self.hw_metadata = hw_metadata
        self.hw = self._import_device_module(id, hw, config, hw_metadata) if hw else None

        # Listen to device's events
        self.hw.on('status_update', self._on_status_update)

        # Periodically refresh the device status
        if self.refresh_status is not None:
            asyncorepp.set_interval(self._refresh_status, self.refresh_status)

    def _import_device_module(self, id, hw, config={}, hw_metadata={}):
        hw_module = import_module("homeswitch.hw.{}".format(hw))
        return hw_module.Device(id=id, config=config, hw_metadata=hw_metadata)

    def _on_status_update(self, status, origin='UNKWNOWN'):
        if self.switch_status != status:
            debug("INFO", "Got a status update about device {}. Device status changed from {} to {}".format(self.id, self.switch_status, status))
            self.switch_status = status
            self.emit('status_update', status, origin)
        else:
            debug("INFO", "Got a status update about device {}. Device status has NOT changed ({})".format(self.id, status))


    def update(self, **kwargs): #discovery_status=None, switch_status=None, hw_metadata=None):
        if 'discovery_status' in kwargs:
            self.discovery_status = kwargs.get('discovery_status', None)
            if self.discovery_status == 'online':
                self.last_seen = time.time()
        if 'switch_status' in kwargs:
            self.switch_status = kwargs.get('switch_status', None)
        if 'hw_metadata' in kwargs:
            hw_metadata = kwargs.get('hw_metadata', None)
            if hw_metadata is not None:
                self.hw_metadata = hw_metadata
                if self.hw:
                    self.hw.update(hw_metadata=hw_metadata)
            else:
                if self.hw:
                    self.hw_metadata = {}
#                   self.hw = None # Evaluate whether we should destroy the hardware module or not

    def json(self):
        return {
            'discovery_status': self.discovery_status,
            'switch_status': self.switch_status,
            'last_seen': self.last_seen,
            'hw_metadata': self.hw_metadata,
        }

    def get_status(self, callback=DO_NOTHING, origin='UNKWNOWN', ignore_cache=False):
        debug("INFO", "Getting device {} status".format(self.id))
        if not self.hw:
            debug("DBUG", "Device {} has no assigned hardware. Cannot set its status".format(self.id))
            return callback({'error': 'Device {} has no assigned hardware. Cannott set its status'.format(self.id)})
        if not self.discovery_status == 'online':
            debug("WARN", "Device {} is not online. Cannot get its status".format(self.id))
            return callback({'error': 'Device {} is not online. Cannot get its status'.format(self.id)}, None)
        if not ignore_cache and self.status_cache and self.last_status_update > time.time() - self.status_cache:
            debug("INFO", "Serving device {} status from cache...".format(self.id))
            return callback(None, self.switch_status)

        return self.hw.get_status(lambda err, status: self._get_status_callback(err, status, callback), origin)

    def _get_status_callback(self, err, status, callback):
        if err:
            debug("ERRO", "Error getting device {} status:".format(self.id), err)
            return callback(err, None)

        debug("INFO", "Device {} status is {}".format(self.id, status))
        self.switch_status = status
        self.last_status_update = time.time()
        return callback(None, status)

    def set_status(self, value, callback=DO_NOTHING):
        debug("INFO", "Setting device {} status to {}".format(self.id, value))
        if not self.hw:
            debug("DBUG", "Device {} has no assigned hardware. Cannot set its status".format(self.id))
            return callback({'error': 'Device {} has no assigned hardware. Cannott set its status'.format(self.id)})
        if not self.discovery_status == 'online':
            debug("DBUG", "Device {} is not online. Cannot set its status".format(self.id))
            return callback({'error': 'Device {} is not online. Cannot set its status'.format(self.id)})

        return self.hw.set_status(value, lambda err, status: self._set_status_callback(err, status, value, callback))

    def _set_status_callback(self, err, status, intent, callback):
        if err:
            debug("ERRO", "Error settings device {} status to {}:".format(self.id, intent), err)
            return callback(err, None)

        debug("INFO", "Device {} was set to {} and is now {}".format(self.id, intent, status))
        self.switch_status = status
        self.last_status_update = time.time()
        return callback(None, status, intent)

    def _refresh_status(self):
        if self.discovery_status == 'online':
            debug("INFO", "Updating device {} status...".format(self.id))
            self.get_status(DO_NOTHING, origin='refresh', ignore_cache=True)
