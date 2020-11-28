from homeswitch.hooks.slack import SlackHook
from homeswitch.device import Device

def _on_get_response():
	print("CALLBACK CALLED")

slack = SlackHook({'url': 'https://hooks.slack.com/services/...'})
slack.notify("status_update", data={
	'device': Device('ID'),
	'status': False,
	'origin': 'meh',
}, callback=_on_get_response)