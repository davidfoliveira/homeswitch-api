import asyncore
import time
import uuid

from .util import debug


TIMERS = {}


def loop(timeout=1, use_poll=False, map=None, count=None):
    if map is None:
        map = asyncore.socket_map

    if use_poll and hasattr(select, 'poll'):
        poll_fun = asyncore.poll2
    else:
        poll_fun = asyncore.poll

    if count is None:
        while map:
            poll_fun(timeout, map)
            _check_timers()

    else:
        while map and count > 0:
            poll_fun(timeout, map)
            _check_timers()
            count = count - 1


def _check_timers():
    now = time.time()
    calls = {}
    for timer_id, timer in TIMERS.items():
        if now >= timer.get('when'):
            calls[timer_id] = timer.get('what')
            if timer.get('interval') is not None:
                timer['when'] = time.time() + timer.get('interval')

    for timer_id, call in calls.items():
        try:
            call()
        except Exception as e:
            debug("ERRO", "Exception running interval callback for timer {}: ".format(timer_id), e)


def set_timeout(callback, timeout):
    timer_id = uuid.uuid4()
    TIMERS[timer_id] = {
        'when': time.time() + timeout,
        'what': callback,
        'interval': None
    }
    return timer_id


def set_interval(callback, timeout):
    timer_id = uuid.uuid4()
    TIMERS[timer_id] = {
        'when': time.time() + timeout,
        'what': callback,
        'interval': timeout
    }
    return timer_id


def cancel_timeout(timer_id):
    del TIMERS[timer_id]


def cancel_interval(timer_id):
    del TIMERS[timer_id]
