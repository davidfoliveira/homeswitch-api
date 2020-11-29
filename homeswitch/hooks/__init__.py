from importlib import import_module
import json
#from multiprocessing.pool import ThreadPool
import os.path
import socket
import sqlite3
import uuid
import threading
import time

from ..util import debug, dict_to_obj


class HooksClient(object):
    def __init__(self, config={}):
        self.host = config.get('host', '127.0.0.1')
        self.port = int(config.get('port', '7777'))
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, 0)
        debug("DBUG", "Hooks Client will send data to {}:{}".format(self.host, self.port))

    def notify(self, hook_name, notif_type, data):
        debug("INFO", "Sending a {} / {} hook notification:".format(hook_name, notif_type), data)
        buf = json.dumps({
            'id': str(uuid.uuid4()),
            'hook': hook_name,
            'type': notif_type,
            'data': data
        })
        return self.socket.sendto(
            buf.encode('utf-8'),
            (self.host, self.port)
        )


class HooksServer(object):
    def __init__(self, host="127.0.0.1", port=7777, database={}, retry_wait=30, max_attempts=5, devices={}, modules={}):
        self.host = host
        self.port = port
        self.retry_wait = retry_wait
        self.max_attempts = max_attempts
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.database_conf = database
        self.receiver_db = None
        self.scheduler_db = None
        self.devices = devices
        self.modules = modules
        self.running = False

        # Load all modules
        for mod_name, mod_conf in modules.items():
            modules[mod_name] = self._import_device_module(mod_name, mod_conf)

    def _database_connect(self, init=False):
        db_file = self.database_conf.get('file', None)
        if db_file is None:
            return
        db_exists = os.path.isfile(db_file)
        return sqlite3.connect(db_file)

        # If the database table don't exist, initialise them
        if init:
            self._database_init(db)

    def _database_init(self, db):
        return self._database_op(db, '''
            CREATE TABLE IF NOT EXISTS notifications (
                id VARCHAR(64) NOT NULL PRIMARY KEY,
                arrived DATETIME NOT NULL,
                process_at DATETIME NOT NULL,
                attempts INT NOT NULL,
                data TEXT
            )
        ''')

    def _database_op(self, db, cmd, *values):
        cur = db.cursor()
        cur.execute(cmd, *values)
        rv = db.commit()
#        debug("DBUG", "SQL Statement `{}`{}: {}".format(cmd, values, rv))

    def _database_q(self, db, cmd, *values):
        cur = db.cursor()
#        debug("DBUG", "SQL Query `{}`{}".format(cmd, values))
        for row in cur.execute(cmd, *values):
            yield row

    def _store_raw_message(self, db, msg):
        msg_id = msg.get('id')
        debug("INFO", "Storing message {}...".format(msg_id))
        try:
            return self._database_op(db, '''
                INSERT INTO notifications (id, arrived, process_at, attempts, data)
                VALUES (?, DATETIME("now"), DATETIME("now"), 0, ?)
            ''', (
                msg_id,
                json.dumps(msg),
            ))
        except Exception as e:
            debug("ERRO", "Error storing message {}: ".format(msg_id), e)
            return

    def _get_queue_message(self, db):
#        debug("DBUG", "Getting a message from the queue...")
        try:
            db_msg = next(self._database_q(db, '''
                SELECT id, CAST(strftime('%s', arrived) AS INT), CAST(strftime('%s', process_at) AS INT), attempts, data
                FROM notifications
                WHERE process_at <= DATETIME('now')
                ORDER BY arrived ASC LIMIT 1
            '''))
        except StopIteration:
            return None
        except Exception as e:
            debug("ERRO", "Error getting a message from the queue:", e)
            raise

        (id, arrived, process_at, attempts, raw_msg) = db_msg
        raw_msg = json.loads(raw_msg)
        print("GOT MSG FROM Q:", raw_msg)

        return (id, arrived, process_at, attempts, raw_msg)

    def _update_message(self, db, msg):
        debug("INFO", "Updating message {}...".format(msg.id))
        try:
            return self._database_op(db, 'UPDATE notifications SET process_at=datetime(?, "unixepoch"), attempts=?, data=? WHERE id=?', (
                msg.process_at,
                msg.attempts,
                json.dumps(msg.source_data),
                msg.id,
            ))
        except Exception as e:
            debug("ERRO", "Error storing message {}: ".format(msg_id), e)
            return

    def _unstore_message(self, db, msg):
        debug("INFO", "Remove completed message {}...".format(msg.id))
        return self._database_op(db, '''
            DELETE FROM notifications WHERE id = ?
        ''', [msg.id])

    def _import_device_module(self, mod_name, config={}):
        hook_module = import_module("homeswitch.hooks.{}".format(mod_name))
        return hook_module.Hook(config)

    def start(self, background=False):
        if self.running:
            return

        # Start listening
        debug("INFO", "Hooks server listening on {}:{}".format(self.host, self.port))
        self.socket.bind((self.host, self.port))

        # Run in a separate thread
        self.running = True
        if background:
            self.background_run = threading.Thread(target=self.run, args=(self, ))
            self.background_run.start()
        else:
            self.run();


    def stop(self):
        self.running = False

        # If it's running in background, wait for it to stop
        if self.background_run:
            self.background_run.join()
        if self.scheduler_thread:
            self.scheduler_thread.join()

    def run(self, *args):
        # Create the scheduler thread and run it
        self.scheduler_thread = threading.Thread(target=self._run_scheduler, args=())
        self.scheduler_thread.daemon = True
        self.scheduler_thread.start()

        # Run receiver
        self._run_receiver()

    def _run_receiver(self):
        # Connect to database
        db = self._database_connect(init=True)

        # Start running
        while self.running:
            (raw_msg, addr) = self._read_message()
            debug("INFO", "Got message: ", raw_msg)

            # Store the message in the queue
            self._store_raw_message(db, raw_msg)

    def _run_scheduler(self):
        # Wait a couple of seconds for the receiver to start (...)
        # Not beautiful but just to avoid multiple threads connecting and initialising the DB at the same time
        time.sleep(2)

        # Connect to the database
        db = self._database_connect(init=False)

        # Start running (get messages from the DB, process and remove them; if they fail update them to run later or expire them)
        while self.running:
            # Retrieve a message from there (should be the same one) and parse it
            db_msg = self._get_queue_message(db)
            if db_msg is None:
                time.sleep(1)
                continue

            (id, arrived, process_at, attempts, raw_msg) = db_msg
            msg = self._parse_raw_message(raw_msg, id=id, arrived=arrived, process_at=process_at, attempts=attempts)
            if msg is None:
                debug("WARN", "Error parsing raw message. Skipping it!", raw_msg)
                return None
            msg_dict = msg.__dict__

            # Process it
            try:
                self._process_message(msg)
            except Exception as e:
                debug("ERRO", "Error '{}' processing notification for exception:".format(e), msg_dict)
                msg.attempts += 1
                if msg.attempts >= self.max_attempts:
                    debug("ERRO", "Message {} exceeded maximum number of attempts {}:".format(msg.id, self.max_attempts), msg_dict)
                    continue
                else:
                    msg.process_at += self.retry_wait
                    self._update_message(db, msg)
                    continue

            # Delete it from storage
            self._unstore_message(db, msg)


    def _read_message(self):
        while True:
            (msg, addr) = self.socket.recvfrom(8192)
            msg = json.loads(msg)
            if 'id' not in msg:
                debug("WARN", "Found a message without id, skipping...: ", msg)
                continue
            return (msg, addr)

    def _parse_raw_message(self, raw_msg, id='-', arrived=0, process_at=0, attempts=0):
        msg = HookMessage(raw_msg, id=id, arrived=arrived, process_at=process_at, attempts=attempts)
        if msg.hook is None:
            debug("WARN", "Got a message without a hook name. Skipping:", message)
            return None
        if msg.hook not in self.modules:
            debug("WARN", "Hook '{}' is not supported. Skipping:".format(msg.hook), message)
            return None
        return msg

    def _process_message(self, msg):
        # Get notification type
        module = self.modules[msg.hook]
        msg_dict = msg.__dict__

        if msg.type is None:
            debug("WARN", "Got a message without type. Skipping:", msg_dict)
            return None

        # Get message data, device and device id
        if msg.data is None or msg.data.device is None or msg.data.device.id is None:
            debug("WARN", "Got a message without device id. Skipping:", msg_dict)
            return None
        dev_id = msg.data.device.id

        # Get device settings
        dev_conf = self.devices.get(dev_id, None)
        if dev_conf is None:
            debug("WARN", "Got NO configuration for device {}. Skipping this message".format(dev_id))
            return False
        if msg.hook not in dev_conf:
            debug("WARN", "Got NO device {} configuration for hook '{}'. Skipping this message".format(dev_id, msg.hook))
            return False

        # Call each of the hook module notify() functions
        module.notify(msg.type, dev_conf[msg.hook], msg.data)


class HookMessage(object):
    def __init__(self, message, **kwargs):
        self.source_data = message
        self.id = kwargs.get('id', message.get('id', None))
        self.hook = message.get('hook', None)
        self.type = message.get('type', None)
        self.data = HookMessageData(message.get('data'))
        self.arrived = int(kwargs.get('arrived', 0))
        self.process_at = int(kwargs.get('process_at', 0))
        self.attempts = int(kwargs.get('attempts', 0))


class HookMessageData(object):
    def __init__(self, data):
        self.device = HookMessageDevice(data.get('device', {}))
        self.status = data.get('status', None)
        self.ctx = HookMessageContext(data.get('ctx', {}))


class HookMessageDevice(object):
    def __init__(self, device):
        self.id = device.get('id', None)
        self.last_seen = device.get('last_seen', None)
        self.switch_status = device.get('switch_status', None)
        self.discovery_status = device.get('discovery_status', None)
        self.device_status = device.get('device_status', None)
        self.metadata = device.get('metadata', {})
        self.name = self.metadata.get('name', None)


class HookMessageContext(object):
    def __init__(self, ctx):
        self.origin = ctx.get('origin', None)
        self.user = ctx.get('user', None)


def main():
    config = {}
    with open('conf/hshookd.json') as config_file:
        config = json.load(config_file)
    listener = HooksServer(**config)
    listener.start(background=False)
    listener.stop()
