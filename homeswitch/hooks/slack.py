from importlib import import_module
import json
from time import sleep
import requests

from ..util import current_stack, debug


DEFAULT_STATUS_TEMPLATE = '{device} was set to *{status}* by {who}'


class SlackHook(object):
    def __init__(self, config={}):
        self.config = config

    def notify(self, notif_type=None, settings={}, data={}):
        config = self.config.copy()
        config.update(settings)
        notification = {}

        # If we should call a module to build the notification
        if config.get('module', None):
            module = import_module(config.get('module'))
            notification = module.format_notification(data, config)

        # Default behaviour
        else:
            if notif_type == 'status_update':
                dev = data.device
                status = data.status
                if dev is None:
                    debug("WARN", "Was supposed to send a status update notification but got no device")
                    return

                status_name = SlackHook.status_name(status)
                template = settings.get('{}_template'.format(status_name), DEFAULT_STATUS_TEMPLATE)
                notification['text'] = template.format(
                    device=dev.name or 'Device {}'.format(dev.id),
                    status=status_name,
                    who=data.ctx.user or 'System ({})'.format(data.ctx.origin)
                )

        # If there's no text, there's no message
        url = config.get('url', None)
        if url and notification and notification['text']:
            text = notification['text'].encode('utf-8')
            debug("INFO", "Sending slack notification with '{}'".format(text))
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
        debug("INFO", "Calling Slack webhook...")
        response = requests.post(url, headers=headers, data=data)
        if response.status_code != 200:
            debug("ERRO", "Error calling Slack webhook. Got status {}".format(response.status_code))
            return False
        debug("INFO", "Successfully called Slack webhook!")
        return True


Hook = SlackHook