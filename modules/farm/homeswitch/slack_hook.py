# -*- coding: utf-8 -*-

DEFAULT_STATUS_TEMPLATE = '{device} was set to {status} by {who}'


def format_notification(message, config={}):
    dev = message.device
    status = message.status
    origin = message.origin or 'unknown'
    if dev is None:
        debug("WARN", "Was supposed to send a status update notification but got no device")
        return

    # Work our the origin
    template = config.get('text_determiner', 'The')
    device_name = dev.metadata.name if getattr(dev, 'metadata') and getattr(dev.metadata, 'name') else '{text_device} {dev_id}'.format(
        text_device=config.get('text_device', 'device'),
        dev_id=dev.id
    )
    template += ' {device_name} '
    if origin == 'online':
        if 'alerts_url' in config:
            config['url'] = config['alerts_url']
        template += config.get('text_was_found', 'was found')
    elif origin == 'refresh':
        template += config.get('text_was_found', 'was found')
    else:
        if status == None:
            template += config.get('text_is', 'is')
        else:
            template += config.get('text_was', 'was')
    template += ' '

    # Missing device
    if status == None:
        if 'alerts_url' in config:
            config['url'] = config['alerts_url']
        template += '*{}*'.format(config.get('text_offline', 'out of service'))
    else:
        template += '*{}*'.format(config.get('text_on', 'set to ON') if status else config.get('text_off', 'set to OFF'))
    template += ' '

    # User
    if origin in ('online', 'refresh'):
        template += config.get('text_by_system', 'by the system')
    elif origin == 'set':
        template += 'por _{}_ '.format('Meh')

    notification = {
        'text': template.format(
            device_name=device_name,
            device=dev,
        )
    }
    return notification
