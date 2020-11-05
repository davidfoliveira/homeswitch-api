import time

from .util import debug


class Device(object):
	def __init__(self, discovery_status='offline', switch_status=None, hw_metadata={}, last_seen=None):
		self.discovery_status = discovery_status
		self.switch_status = {}
		self.hw_metadata = hw_metadata
		self.last_seen = last_seen

	def update(self, discovery_status=None, switch_status=None, hw_metadata=None):
		if discovery_status is not None:
			self.discovery_status = discovery_status
			if discovery_status == 'online':
				self.last_seen = time.time()
		if switch_status is not None:
			self.switch_status = switch_status
		if hw_metadata is not None:
			self.hw_metadata = hw_metadata

	def json(self):
		return {
			'discovery_status': self.discovery_status,
			'switch_status': self.switch_status,
			'last_seen': self.last_seen,
			'hw_metadata': self.hw_metadata,
		}