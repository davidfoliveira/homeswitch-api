from pymitter import EventEmitter
from time import time

from asyncorepp import set_timeout, cancel_timeout


class ExpirableQueue(EventEmitter):
	def __init__(self, default_timeout=None):
		EventEmitter.__init__(self)
		self.queue = []
		self.default_timeout = default_timeout

	def push(self, what, timeout=None):
		item = ExpirableItem(what, timeout=timeout or self.default_timeout)
		item.on('expire', lambda: self._item_expire(item))
		item.on('cancel', lambda: self._item_cancel(item))
		self.queue.push(item)

	def _item_expire(self, item):
		self.emit('item_expire', item)
		self.remove(item)
		if len(self.queue) == 0:
			self.emit('drain')

	def _item_cancel(self):
		self.remove(item)

	def remove(self, item):
		item.cancel()
		try:
			self.queue.remove(item)
		except ValueError:
			return False
		return True

	def shift(self):
		while len(self.queue) > 0:
			item = self.queue.popleft()
			if item.expires < time():
				continue
			return item


class ExpirableItem(EventEmitter):
	def __init__(self, value, timeout=None):
		self.expired = False
		self.cancelled = False
		self.timeout = None
		self.expires = None
		if timeout:
			self.timeout = set_timeout(self._expire, timeout)
			self.expires = time() + timeout

	def _expire(self):
		if self.expired or self.cancelled:
			return False
		self.timeout = None
		self.expired = True
		self.emit('expire')
		return True

	def cancel(self):
		if self.cancelled or self.expired:
			return False
		if self.timeout is not None:
			cancel_timeout(self.timeout)
		self.cancelled = True
		self.emit('cancel')
		return True