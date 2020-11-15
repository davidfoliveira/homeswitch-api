import asyncore
import select
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
            import traceback
            traceback.print_exc()


def set_timeout(callback, timeout):
    def call_and_expire():
        del TIMERS[timer_id]
        return callback()

    timer_id = uuid.uuid4()
    TIMERS[timer_id] = {
        'when': time.time() + timeout,
        'what': call_and_expire,
        'interval': None,
    }
    return timer_id


def set_interval(callback, timeout):
    timer_id = uuid.uuid4()
    TIMERS[timer_id] = {
        'when': time.time() + timeout,
        'what': callback,
        'interval': timeout,
    }
    return timer_id


def cancel_timeout(timer_id):
    if timer_id not in TIMERS:
        debug("WARN", "Trying to cancel timeout timer {} which doesn't exist. This should be fixed".format(timer_id))
        return
    del TIMERS[timer_id]


def cancel_interval(timer_id):
    if timer_id not in TIMERS:
        debug("WARN", "Trying to cancel interval timer {} which doesn't exist. This should be fixed".format(timer_id))
        return
    del TIMERS[timer_id]
