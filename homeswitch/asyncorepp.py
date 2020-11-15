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


def poll(timeout=0.0, map=None):
    if map is None:
        map = asyncore.socket_map
    if map:
        print("MAP: ", map)
        r = []; w = []; e = []
        for fd, obj in map.items():
            is_r = obj.readable()
            is_w = obj.writable()
            if is_r:
                r.append(fd)
            # accepting sockets should not be writable
            if is_w and not obj.accepting:
                w.append(fd)
            if is_r or is_w:
                e.append(fd)
        if [] == r == w == e:
            time.sleep(timeout)
            return

        try:
            r, w, e = select.select(r, w, e, timeout)
        except select.error, err:
            if err.args[0] != EINTR:
                raise
            else:
                return

        for fd in r:
            print("READ {}".format(fd))
            obj = map.get(fd)
            if obj is None:
                continue
            asyncore.read(obj)

        for fd in w:
            print("WRITE {}".format(fd))
            obj = map.get(fd)
            if obj is None:
                continue
            asyncore.write(obj)

        for fd in e:
            print("E {}".format(fd))
            obj = map.get(fd)
            if obj is None:
                continue
            asyncore._exception(obj)



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
    if timer_id not in TIMERS:
        debug("WARN", "Trying to cancel timeout timer {} which doesn't exist. This should be fixed".format(timer_id))
        return
    del TIMERS[timer_id]


def cancel_interval(timer_id):
    if timer_id not in TIMERS:
        debug("WARN", "Trying to cancel interval timer {} which doesn't exist. This should be fixed".format(timer_id))
        return
    del TIMERS[timer_id]
