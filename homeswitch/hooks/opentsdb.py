import json
import socket
import time
import requests

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
        url = "http://{}:{}/api/put".format(host, port)

        # Generate the final metric and value
        value = data.status
        if type(value) is bool:
            value = 1 if value else 0
        elif value is None:
            value = -1
        metric = metric.format(
            type=notif_type,
            device=data.device,
            status=data.status,
            ctx=data.ctx,
        )

        # Send the metric
        debug("INFO", "Sending metric '{}' = {} to OpenTSDB at {}...".format(metric, value, url))
        self._https_request(url, {}, json.dumps({
            "metric": metric,
            "timestamp": int(time.time()*1000),
            "value": value,
            "tags": {
                "origin": data.ctx.origin or 'system',
                "user": data.ctx.user or 'unknown',
            }
        }))
        debug("INFO", "Metric '{}' successfully sent to OpenTSDB".format(metric, value, host, port))

    def _https_request(self, url, headers, data):
        debug("INFO", "Calling OpenTSDB API...")
        response = requests.post(url, headers=headers, data=data)
        if response.status_code >= 300:
            raise Exception('Error calling OpenTSDB API. Got status {}'.format(response.status_code))
        debug("INFO", "Successfully called OpenTSDB API!")


Hook = OpenTSDBHook
