import time
from importlib import import_module

from .hw import tuya
from .util import debug

DEVICE_CONTRUCTORS = {
	"tuya": tuya.TuyaDevice,
}


class Device(object):
	def __init__(self, id=None, hw=None, config={}, discovery_status='offline', switch_status=None, hw_metadata={}, last_seen=None, **kwargs):
		self.id = id
		self.discovery_status = discovery_status
		self.switch_status = {}
		self.hw_metadata = hw_metadata
		self.last_seen = last_seen
		self.config = config
		self.hw_metadata = hw_metadata
		self.hw = self._import_device_module(id, hw, config, hw_metadata) if hw else None

	def _import_device_module(self, id, hw, config={}, hw_metadata={}):
		hw_module = import_module("homeswitch.hw.{}".format(hw))
		return hw_module.Device(id=id, config=config, hw_metadata=hw_metadata)

	def update(self, discovery_status=None, switch_status=None, hw_metadata=None):
		if discovery_status is not None:
			self.discovery_status = discovery_status
			if discovery_status == 'online':
				self.last_seen = time.time()
		if switch_status is not None:
			self.switch_status = switch_status
		if hw_metadata is not None:
			self.hw_metadata = hw_metadata
			if self.hw:
				self.hw.update(hw_metadata=hw_metadata)
		else:
			if self.hw:
				self.hw_metadata = {}

	def json(self):
		return {
			'discovery_status': self.discovery_status,
			'switch_status': self.switch_status,
			'last_seen': self.last_seen,
			'hw_metadata': self.hw_metadata,
		}

	def get_status(self, callback):
		if not self.hw:
			raise Exception("Device has no assigned hardware. Can't get its status")
		if not self.discovery_status == 'online':
			raise Exception("Device is not online. Can't get its status")
		debug("INFO", "Getting device {} status".format(self.id))
		return self.hw.get_status(lambda status: self._get_status_callback(status, callback))

	def _get_status_callback(self, status, callback):
		debug("INFO", "Device {} status is {}".format(self.id, status))
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
		return callback(self, status, intent)
