from pymitter import EventEmitter

from ..asyncorepp import set_timeout, cancel_timeout
from ..util import debug, DO_NOTHING
from ..valueops import apply_ops


class PushDevice(EventEmitter):
    def __init__(self, id=None, config={}, hw_metadata={}):
        EventEmitter.__init__(self)
        self.id = id
        self.config = config
        self.status = None
        self.device_timeout = config.get('max_time_since_last_seen', 300)
        self._timeout_expect_new_status = None

    def get_status(self, callback=DO_NOTHING, ctx={'origin':'UNKWNOWN'}):
        debug("DBUG", "Getting Put device {} status ({})".format(self.id, self.status))
        return callback(None, self.status)

    def put_status(self, value, ctx={'origin': 'put'}, callback=DO_NOTHING):
        debug("DBUG", "Setting Put device {} status to {}".format(self.id, value))

        # First things first. Let's stop this timeout to consider device as offline/gone
        if self._timeout_expect_new_status is not None:
            cancel_timeout(self._timeout_expect_new_status)

        status_before = self.status

        # Convert value
        if 'convert' in self.config:
            value = apply_ops(value, self.config.get('convert'))

        self.status = value
        callback(None, value)
        ctx['origin'] = 'put'
        if status_before != value:
            self.emit('status_update', value, ctx=ctx)

        self._timeout_expect_new_status = set_timeout(self._set_device_as_gone, self.device_timeout)

    def _set_device_as_gone(self):
        debug("INFO", "Haven't heard from Put device {} in {}s. Considering it offline".format(self.id, self.device_timeout))
        self.status = None
        self.emit('status_update', None, ctx={'origin': 'refresh.long_time_no_see'})

Device = PushDevice