# -*- coding: utf-8 -*-


DEFAULT_STATUS_TEMPLATE = '{device} was set to {status} by {who}'


def format_notification(message, config={}):
    dev = message.device
    status = message.status
    origin = message.ctx.origin
    if dev is None:
        debug("WARN", "Was supposed to send a status update notification but got no device")
        return

    # Work our the origin
    template = config.get('text_determiner', 'The').encode('utf-8')
    device_name = dev.name or '{text_device} {dev_id}'.format(
        text_device=config.get('text_device', 'device').encode('utf-8'),
        dev_id=dev.id
    )
    template += ' {device_name} '
    if origin == 'online':
        if 'alerts_url' in config:
            config['url'] = config['alerts_url']
        template += config.get('text_was_found', 'was found').encode('utf-8')
    elif origin == 'refresh' or origin.startswith('refresh.'):
        template += config.get('text_was_found', 'was found').encode('utf-8')
    else:
        if status == None:
            template += config.get('text_is', 'is').encode('utf-8')
        else:
            template += config.get('text_was', 'was').encode('utf-8')
    template += ' '

    # Missing device
    if status == None:
        if 'alerts_url' in config:
            config['url'] = config['alerts_url']
        template += '*{}*'.format(config.get('text_offline', 'out of service').encode('utf-8'))
    else:
        template += '*{}*'.format(config.get('text_on', 'set to ON').encode('utf-8') if status else config.get('text_off', 'set to OFF').encode('utf-8'))
    template += ' '

    # User
    if origin in ('online', 'refresh', 'request') or origin.startswith('refresh.'):
        template += config.get('text_by_system', 'by the system').encode('utf-8')
    elif origin == 'set':
        template += 'por _{}_ '.format(ucfirst(message.ctx.user) or config.get('text_unknown', 'Unknown').encode('utf-8'))

    notification = {
        'text': template.format(
            device_name=device_name,
            device=dev,
        )
    }
    return notification


def ucfirst(value):
    return value[0].upper()+value[1:]
