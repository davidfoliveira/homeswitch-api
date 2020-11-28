import json
import socket
import time

from ..util import debug


class OpenTSDBHook(object):
    def __init__(self, config={}):
        self.config = config
        self.http_clients = {}

    def notify(self, notif_type, settings, data):
        config = self.config.copy()
        config.update(settings)

        # Check for the metric path
        metric = config.get('metric', None)
        if metric is None:
            debug("WARN", "No OpenTSDB metric was specified. Skipping...")
            return

        # Get host/port
        host = config.get('host', '127.0.0.1')
        port = int(config.get('port', '4242'))

        # Generate the final metric and value
        value = data.status
        if type(value) is bool:
            value = 1 if value else 0
        metric = metric.format(
            type=notif_type,
            device=data.device,
            status=data.status,
            ctx=data.ctx,
        )

        debug("INFO", "Sending metric '{}' = {} to OpenTSDB at {}:{}...".format(metric, value, host, port))

        # Connect and put the metric
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.connect((host, port))
            s.sendall('put {metric} {ts} {value} origin={origin} user={user}\r\n'.format(
                metric=metric,
                ts=int(time.time()*1000),
                value=value,
                origin=data.ctx.origin or 'system',
                user=data.ctx.user or 'unknown',
            ))
            s.close()
        except Exception as e:
            debug("ERRO", "Error sending metric to OpenTSDB:", e)
        debug("INFO", "Metric '{}' successfully sent to OpenTSDB".format(metric, value, host, port))


Hook = OpenTSDBHook
