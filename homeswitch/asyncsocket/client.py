import asyncore
from pymitter import EventEmitter

from ..util import DO_NOTHING


class AsyncSocketClient(asyncore.dispatcher, EventEmitter):
	def __init__(self):
		pass