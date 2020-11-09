import time
from importlib import import_module

import asyncorepp
from .hw import tuya
from .util import debug, DO_NOTHING

DEVICE_CONTRUCTORS = {
	"tuya": tuya.TuyaDevice,
}


class Device(object):
	def __init__(self, id=None, hw=None, config={}, discovery_status='offline', switch_status=None, hw_metadata={}, last_seen=None, **kwargs):
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

	def _on_status_update(self, status):
		debug("INFO", "Got a status update about device {}. Device status is: {}".format(self.id, status))
		self.switch_status = status

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
#					self.hw = None # Evaluate whether we should destroy the hardware module or not

	def json(self):
		return {
			'discovery_status': self.discovery_status,
			'switch_status': self.switch_status,
			'last_seen': self.last_seen,
			'hw_metadata': self.hw_metadata,
		}

	def get_status(self, callback, ignore_cache=False):
		if not self.hw:
			raise Exception("Device has no assigned hardware. Can't get its status")
		if not self.discovery_status == 'online':
			raise Exception("Device is not online. Can't get its status")
		debug("INFO", "Getting device {} status".format(self.id))

		if not ignore_cache and self.status_cache and self.last_status_update > time.time() - self.status_cache:
			debug("INFO", "Serving device {} status from cache...".format(self.id))
			return callback(self, self.switch_status)

		return self.hw.get_status(lambda status: self._get_status_callback(status, callback))

	def _get_status_callback(self, status, callback):
		debug("INFO", "Device {} status is {}".format(self.id, status))
		self.switch_status = status
		self.last_status_update = time.time()
		return callback(self, status)

	def set_status(self, value, callback):
		if not self.hw:
			raise Exception("Device has no assigned hardware. Can't set its status")
		if not self.discovery_status == 'online':
			raise Exception("Device is not online. Can't get its status")
		debug("INFO", "Setting device {} status to {}".format(self.id, value))
		return self.hw.set_status(value, lambda status: self._set_status_callback(status, value, callback))

	def _set_status_callback(self, status, intent, callback):
		debug("INFO", "Device {} was set to {} and is now {}".format(self.id, intent, status))
		self.switch_status = status
		self.last_status_update = time.time()
		return callback(self, status, intent)

	def _refresh_status(self):
		if self.discovery_status == 'online':
			debug("INFO", "Updating device {} status...".format(self.id))
			self.get_status(DO_NOTHING, True)
