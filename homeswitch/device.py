from contextlib import contextmanager
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
    def __init__(self, id=None, hw=None, config={}, discovery_status='offline', device_status="up", switch_status=None, hw_metadata={}, last_seen=None, **kwargs):
        EventEmitter.__init__(self)
        self.id = id
        self.discovery_status = discovery_status
        self.device_status = device_status
        self.switch_status = switch_status
        self.last_status_update = 0
        self.last_seen = last_seen
        self.hw_metadata = hw_metadata
        self.hooks = config.get('hooks', [])
        self.metadata = config.get('metadata', {})
        self.status_cache = config.get('status_cache', None)
        self.refresh_status = int(config.get('refresh_status', 0))
        self.hold_get_status = config.get('hold_get_status', False)
        self.activation_key = config.get('activation_key', None)
        self.fails_to_miss = config.get('fails_to_miss', 5)
        self.config = config
        self.hw_metadata = hw_metadata
        self.hw_type = hw
        self.hw = self._import_device_module(id, hw, config, hw_metadata) if hw else None
        self.connect_errors = 0
        self.waiting_status = []

        # Listen to device's events
        if self.hw:
            self.hw.on('status_update', self._on_status_update)

        # Periodically refresh the device status
        if self.refresh_status:
            asyncorepp.set_interval(self._refresh_status, self.refresh_status)

    def _import_device_module(self, id, hw, config={}, hw_metadata={}):
        hw_module = import_module("homeswitch.hw.{}".format(hw))
        return hw_module.Device(id=id, config=config, hw_metadata=hw_metadata)

    def _on_status_update(self, status, ctx={'origin': 'UNKWNOWN'}):
        if self.switch_status != status:
            debug("INFO", "Got a status update about device {}. Device status changed from {} to {}".format(self.id, self.switch_status, status))
            self.switch_status = status
            self.emit('status_update', status, ctx)
        else:
            debug("INFO", "Got a status update about device {}. Device status has NOT changed ({})".format(self.id, status))

    def update(self, **kwargs):
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
            'id': self.id,
            'discovery_status': self.discovery_status,
            'device_status': self.device_status,
            'switch_status': self.switch_status,
            'last_seen': self.last_seen,
            'metadata': self.metadata,
            'hw_metadata': self.hw_metadata,
        }

    def get_status(self, callback=DO_NOTHING, ctx={'origin': 'UNKWNOWN'}, ignore_cache=False):
        debug("INFO", "Getting device {} status".format(self.id))
        if not self.hw:
            debug("DBUG", "Device {} has no assigned hardware. Cannot set its status".format(self.id))
            return callback({'error': 'Device {} has no assigned hardware. Cannott set its status'.format(self.id)}, ctx)
        if not self.discovery_status == 'online':
            debug("WARN", "Device {} is not online. Cannot get its status".format(self.id))
            return callback({'error': 'Device {} is not online. Cannot get its status'.format(self.id)}, None, ctx)
        if not ignore_cache and self.status_cache and self.last_status_update > time.time() - self.status_cache:
            debug("INFO", "Serving device {} status from cache...".format(self.id))
            return callback(None, self.switch_status, ctx)

        with status_collector(self, callback) as collector_callback:
            if collector_callback:
                return self.hw.get_status(lambda err, status: self._get_status_callback(err, status, ctx, collector_callback), ctx)

    def _get_status_callback(self, err, status, ctx, callback):
        if err:
            debug("ERRO", "Error getting device {} status:".format(self.id), err)
            self._check_error(err, ctx)
            return callback(err, None, ctx)

        debug("INFO", "Device {} status is {}".format(self.id, status))
        self._check_success()
        self.switch_status = status
        self.last_status_update = time.time()
        return callback(None, status, ctx)

    def set_status(self, value, ctx={'origin': 'set'}, callback=DO_NOTHING):
        debug("INFO", "Setting device {} status to {}".format(self.id, value))
        if not self.hw:
            debug("DBUG", "Device {} has no assigned hardware. Cannot set its status".format(self.id))
            return callback({'error': 'Device {} has no assigned hardware. Cannot set its status'.format(self.id)}, None, value, ctx)
        if not self.discovery_status == 'online':
            debug("DBUG", "Device {} is not online. Cannot set its status".format(self.id))
            return callback({'error': 'Device {} is not online. Cannot set its status'.format(self.id)}, None, value, ctx)

        with status_collector(self, callback, get=False) as collector_callback:
            if collector_callback:
                return self.hw.set_status(value, ctx=ctx, callback=lambda err, status: self._set_status_callback(err, status, value, ctx, collector_callback))

    def _set_status_callback(self, err, status, intent, ctx, callback):
        if err:
            debug("ERRO", "Error setting device {} status to {}:".format(self.id, intent), err)
            self._check_error(err, ctx)
            return callback(err, None, intent, ctx)

        debug("INFO", "Device {} was set to {} and is now {}".format(self.id, intent, status))
        self._check_success()
        self.switch_status = status
        self.last_status_update = time.time()
        return callback(None, status, intent, ctx)

    def put_status(self, value, ctx={'origin': 'put'}, callback=DO_NOTHING):
        debug("INFO", "Putting device {} status '{}'".format(self.id, value))
        if not self.hw:
            debug("DBUG", "Device {} has no assigned hardware. Cannot put a status in it".format(self.id))
            return callback({'error': 'Device {} has no assigned hardware. Cannot put a status in it'.format(self.id)}, None, value, ctx)

        return self.hw.put_status(value, ctx=ctx, callback=lambda err, status: self._put_status_callback(err, status, value, ctx, callback))

    def _put_status_callback(self, err, status, intent, ctx, callback):
        if err:
            debug("ERRO", "Error putting device {} status '{}'".format(self.id, intent), err)
            return callback(err, None, intent, ctx)

        debug("INFO", "Device {} status was defined to '{}' and is now '{}'".format(self.id, intent, status))
        self._check_success()
        self.last_status_update = time.time()
        self.discovery_status = "online"
        return callback(None, status, intent, ctx)

    def _refresh_status(self):
        if self.discovery_status == 'online':
            debug("INFO", "Updating device {} status...".format(self.id))
            self.get_status(DO_NOTHING, ctx={'origin': 'refresh'}, ignore_cache=True)

    def _check_success(self):
        self.device_status = "up"
        self.connect_errors = 0

    def _check_error(self, err, ctx={'origin': 'UNKWNOWN'}):
        error_code = err.get('error', None)
        is_connect_error = str(error_code).startswith('connect_')
        if is_connect_error:
            self.connect_errors += 1
            if self.connect_errors >= self.fails_to_miss:
                debug("WARN", "Too many connection errors ({}/{}) for device {}. Marking it as down!".format(self.connect_errors, self.fails_to_miss, self.id))
                self.device_status = "down"

                ctx['origin'] += '.too_many_errors'
                self._on_status_update(None, ctx)
#                print("======== DEVICE {} IS DOWN".format(self.id))


# This collector stacks all calls for gets on the same device and serves them all at once from the first returning call
@contextmanager
def status_collector(scope, callback, get=True):
    if not scope.hold_get_status:
        yield callback
        return

    def collector_callback(*args):
        err, status = args[0:2]
        # Call the first callback with all arguments (it can be a set)
        callback(*args)

        # Call the other waiting callbacks
        other_callbacks = list(filter(lambda cb: cb is not None, scope.waiting_status))
        debug("DBUG", "Serving device {} {} callbacks with the result of a {}".format(scope.id, len(other_callbacks), "get" if get else "set"))
        while len(other_callbacks) > 0:
            other_callback = other_callbacks.pop(0)
            if other_callback:
                other_callback(*args)
        scope.waiting_status = []

    # Add callback to the list of callbacks waiting for status
    if get:
        scope.waiting_status.append(None if len(scope.waiting_status) == 0 else callback)
        if len(scope.waiting_status) == 1:
            yield collector_callback
        else:
            yield None
    else:
        scope.waiting_status.append(None)
        yield collector_callback

