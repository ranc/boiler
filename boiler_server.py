import collections
import datetime
import json
import logging
import os
import signal
import sys
import threading
import time
from typing import Dict, Optional, Tuple

import boiler_config
from web_server import WebServer

if os.name == 'nt':
    from gpio_nt import turn, setup, get, BOILER_GPIO
    config_path = "test_config.json"
    override_path = "test_override.json"
    legacy_path = "sched.data"
    usb_dir = "."
    http_port = 8080
else:
    from gpio_linux import turn, setup, get, BOILER_GPIO
    config_path = "/home/pi/boiler_config.json"
    override_path = "/home/pi/boiler_override.json"
    legacy_path = "/home/pi/boiler/sched.data" # the old boiler.c schedule, imported once
    usb_dir = "/media/usb" # browsable (read-only, not linked from the page) at /usb/
    http_port = 80
http_port = int(os.environ.get("BOILER_HTTP_PORT", http_port))
usb_dir = os.environ.get("BOILER_USB_DIR", usb_dir)
static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "website")

'''
    The boiler is one relay on GPIO4 (active low). Every second the monitor works out what it should be:
        1. a manual override (on or off until a given time) wins while it lasts
        2. otherwise it's on if any schedule window is active now
    and switches the relay when it differs.
    The override is kept in override_path with an absolute end time, so it survives a restart and midnight.
'''

MAX_OVERRIDE_SEC = 24 * 3600
HISTORY_LEN = 10


def week_time(t: float) -> Tuple[int, int]:
    now = time.localtime(t)
    # tm_wday     range [0, 6], Monday is 0, Sunday is 6
    my_week_day = 1 + ((now.tm_wday + 1) % 7) # Sunday is 1, Monday is 2, Saturday is 7
    sec_since_midnight = (now.tm_hour*60 + now.tm_min)*60 + now.tm_sec
    return my_week_day, sec_since_midnight


def when_str(t: float, now: float) -> str:
    same_day = datetime.date.fromtimestamp(t) == datetime.date.fromtimestamp(now)
    return time.strftime("%H:%M" if same_day else "%a %H:%M", time.localtime(t))


class Schedule:
    def __init__(self, config: Dict) -> None:
        self.entries = boiler_config.expand(config) # (day, start sec, end sec), day 0 - every day

    def is_on(self, t: float) -> bool:
        wday, sec = week_time(t)
        return any((day == 0 or day == wday) and start <= sec < end for day, start, end in self.entries)

    def next_change(self, t: float) -> Optional[Tuple[float, bool]]:
        '''the next time within a week the schedule switches, and to what'''
        current = self.is_on(t)
        today = datetime.date.fromtimestamp(t)
        edges = set()
        for offset in range(8):
            day = today + datetime.timedelta(days=offset)
            midnight = time.mktime(day.timetuple())
            wday = 1 + ((day.weekday() + 1) % 7)
            for d, start, end in self.entries:
                if d == 0 or d == wday:
                    edges.update((midnight + start, midnight + end))
        for edge in sorted(e for e in edges if e > t):
            state = self.is_on(edge)
            if state != current:
                return edge, state
        return None


class BoilerMonitor(threading.Thread):
    def __init__(self) -> None:
        super().__init__(name="monitor")
        self.logger = logging.getLogger('monitor')
        self.lock = threading.Lock() # guards config, schedule and override, taken by the web threads too
        self.config_path = config_path
        self.override = self.load_override() # {"on": bool, "until": epoch, "started": epoch} or None
        self.history = collections.deque(maxlen=HISTORY_LEN)
        self.next_reason = "startup" # reason for the next relay change, when it isn't the obvious one
        self.keepalive_count = 0
        self.last_live_time = time.perf_counter()
        self.init_config()
        self.work = True

    # ---------- config ----------
    def init_config(self):
        if not os.path.exists(self.config_path):
            if os.path.exists(legacy_path):
                config = boiler_config.import_legacy(legacy_path)
                self.logger.info(f"Imported schedule from {legacy_path}")
            else:
                config = boiler_config.default_config()
            boiler_config.save(self.config_path, config)
            self.logger.info(f"Created {self.config_path}")
        self.lastmtime = os.path.getmtime(self.config_path)
        self.apply_config(boiler_config.load(self.config_path))

    def configure(self):
        try:
            config = boiler_config.load(self.config_path)
        except (OSError, ValueError) as e:
            # a broken hand edit: keep running with the previous schedule
            self.logger.error(f"Cannot read {self.config_path}, keeping the previous schedule: {e}")
            return
        with self.lock:
            self.apply_config(config)

    def apply_config(self, config: Dict):
        self.config = config
        self.schedule = Schedule(config)
        self.logger.info(f"Loaded {len(config['schedule'])} heating times from {self.config_path}")

    def update_schedule(self, data: Dict) -> str:
        config = boiler_config.normalize(data)
        with self.lock:
            boiler_config.save(self.config_path, config)
            self.lastmtime = os.path.getmtime(self.config_path) # our own write, no need to reload it
            self.apply_config(config)
        return "Schedule saved"

    # ---------- manual override ----------
    def load_override(self) -> Optional[Dict]:
        try:
            with open(override_path, "r", encoding="utf-8") as f:
                ov = json.load(f)
            ov = {"on": bool(ov["on"]), "until": float(ov["until"]), "started": float(ov.get("started", 0))}
        except FileNotFoundError:
            return None
        except (OSError, ValueError, KeyError, TypeError) as e:
            self.logger.error(f"Ignoring bad {override_path}: {e}")
            return None
        self.logger.info(f"Manual {'on' if ov['on'] else 'off'} until {time.ctime(ov['until'])}")
        return ov

    def set_override(self, is_on: bool, sec: int) -> str:
        if sec<60 or sec>MAX_OVERRIDE_SEC:
            raise ValueError(f"duration must be 1 min to {MAX_OVERRIDE_SEC // 3600} hours, got: {sec} sec")
        now = time.time()
        ov = {"on": is_on, "until": now + sec, "started": now}
        with self.lock:
            boiler_config.save(override_path, ov)
            self.override = ov
        return f"Boiler {'on' if is_on else 'off'} until {when_str(ov['until'], now)}"

    def clear_override(self) -> str:
        with self.lock:
            if self.override is None:
                return "No manual override"
            self.drop_override("manual cleared")
        return "Back to the schedule"

    def drop_override(self, reason: str):
        # called with the lock held
        self.override = None
        self.next_reason = reason
        try:
            os.remove(override_path)
        except FileNotFoundError:
            pass

    # ---------- the loop ----------
    def run(self):
        while self.work:
            self.keepalive_count += 1
            self.last_live_time = time.perf_counter()
            try:
                lastmtime = os.path.getmtime(self.config_path)
                if lastmtime != self.lastmtime:
                    self.lastmtime = lastmtime
                    self.configure()
                self.check()
            except Exception as e:
                self.logger.exception(f"Error {e}, retrying...")
            time.sleep(1)

    def wanted(self, now: float) -> Tuple[bool, str]:
        # called with the lock held
        if self.override is not None:
            return self.override["on"], "manual"
        return self.schedule.is_on(now), "schedule"

    def check(self):
        now = time.time()
        with self.lock:
            if self.override is not None and now >= self.override["until"]:
                self.drop_override("manual ended")
            is_on, reason = self.wanted(now)
            if get() == is_on:
                self.next_reason = None # nothing changed, the next change has its own reason
                return
            if reason == "schedule" and self.next_reason:
                reason = self.next_reason
            self.next_reason = None
        turn(is_on)
        self.logger.info(f"Boiler {'on' if is_on else 'off'} ({reason})")
        self.history.appendleft({"on": is_on, "reason": reason, "at": time.strftime("%a %H:%M:%S")})

    def status(self) -> Tuple[float, int]:
        return time.perf_counter()-self.last_live_time, self.keepalive_count

    def stop(self):
        self.work = False
        self.join()

    def state(self) -> Dict:
        now = time.time()
        tick_age, ticks = self.status()
        with self.lock:
            is_on, reason = self.wanted(now)
            ov = self.override
            override = None
            if ov is not None:
                override = {"on": ov["on"], "until": when_str(ov["until"], now),
                            "left": max(0, round(ov["until"] - now)),
                            "then": self.schedule.is_on(ov["until"])}
            change = self.schedule.next_change(now)
            next_change = None if change is None else \
                {"at": when_str(change[0], now), "on": change[1], "in": round(change[0] - now)}
            return {
                "now": time.strftime("%a %d %b %H:%M:%S"),
                "gpio": BOILER_GPIO,
                "config_path": self.config_path,
                "monitor": {"tick_age": round(tick_age, 1), "ticks": ticks, "alive": self.is_alive()},
                "config": self.config,
                "boiler": get(), # actual relay state, None = not set up
                "wanted": is_on,
                "reason": reason,
                "override": override,
                "schedule_on": self.schedule.is_on(now),
                "next_change": next_change,
                "history": list(self.history),
            }


def as_int(body: dict, key: str) -> int:
    try:
        return int(body[key])
    except (KeyError, TypeError, ValueError):
        raise ValueError(f"'{key}' must be an integer")


def as_bool(body: dict, key: str) -> bool:
    if not isinstance(body.get(key), bool):
        raise ValueError(f"'{key}' must be true or false")
    return body[key]


def set_logging():
    from logging import handlers
    handler = handlers.RotatingFileHandler('boiler.log', maxBytes=20000, backupCount=3)
    formatter = logging.Formatter('%(asctime)s %(levelname)-10.10s [%(name)-15.15s]: %(message)s')
    handler.setFormatter(formatter)
    logging.basicConfig(handlers=[handler, logging.StreamHandler()])
    logging.getLogger().setLevel(logging.INFO)


def main():
    set_logging()
    setup()
    monitor = BoilerMonitor()
    monitor.start()

    get_routes = {
        'state': monitor.state,
    }
    post_routes = {
        'override': lambda b: monitor.set_override(as_bool(b, "on"), as_int(b, "sec")),
        'clear': lambda b: monitor.clear_override(),
        'schedule': monitor.update_schedule,
    }
    srv = WebServer(http_port, static_dir, get_routes, post_routes, browse_dirs={"/usb": usb_dir})
    # systemd stops us with SIGTERM: turn it into a clean exit so the boiler isn't left on unattended
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    logging.getLogger('web').info(f"Serving on port {http_port}")
    try:
        srv.serve_forever()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        srv.server_close()
        monitor.stop()
        turn(False)
        logging.getLogger('web').info("Stopped, boiler off")


if __name__ == "__main__":
    main()
