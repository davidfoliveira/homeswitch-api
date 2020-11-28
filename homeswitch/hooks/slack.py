from importlib import import_module
import json
from time import sleep
import requests

from ..util import current_stack, debug


DEFAULT_STATUS_TEMPLATE = '{device} was set to *{status}* by {who}'


class SlackHook(object):
    def __init__(self, config={}):
        self.config = config

    def notify(self, type=None, settings={}, data={}):
        config = self.config.copy()
        config.update(settings)
        notification = {}
        print("SETTINGS: ", settings)

        # If we should call a module to build the notification
        if settings.get('module', None):
            module = import_module(settings.get('module'))
            notification = module.format_notification(data, config)

        # Default behaviour
        else:
            if type == 'status_update':
                dev = data.device
                dev_name = (getattr(data.metadata, 'name') if hasattr(data, 'metadata') else None) or 'Device {}'.format(dev.id)
                status = data.status
                origin = data.origin or 'unknown'
                if dev is None:
                    debug("WARN", "Was supposed to send a status update notification but got no device")
                    return

                status_name = SlackHook.status_name(status)
                print("STATUS: ", status)
                print("STATUS NAME: ", status_name)
                template = settings.get('{}_template'.format(status_name), DEFAULT_STATUS_TEMPLATE)
                device_name = dev.metadata.name if getattr(dev, 'metadata') and getattr(dev.metadata, 'name') else 'Device {}'.format(dev.id)
                notification['text'] = template.format(
                    device=device_name,
                    status=status_name,
                    who=origin
                )

        # If there's no text, there's no message
        url = config.get('url', None)
        print("SETTINGS: ", settings)
        if url and notification and notification['text']:
            debug("INFO", "Sending slack notification with '{}'".format(notification['text']))
            headers = {'content-type': 'application/json'}
            return self._https_request(url, headers, json.dumps(notification))

    @staticmethod
    def status_name(status):
        if status == True:
            return 'on'
        elif status == False:
            return 'off'
        elif status == None:
            return 'offline'
        return 'unknown'

    def _https_request(self, url, headers, data):
        print("POSTING TO: ", url)
        response = requests.post(url, headers=headers, data=data)
        print("RES: ", response)


Hook = SlackHook