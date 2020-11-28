import json

from ..http.asyncclient import AsyncHTTPClient


class OpenTSDBHook(object):
	def __init__(self, config={}):
		self.config = config
		self.http_client = AsyncHTTPClient()

	def notify(self, type, settings, data):
		config = self.config.copy()
		config.update(settings)
		pass

Hook = OpenTSDBHook