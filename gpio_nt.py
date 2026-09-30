import datetime

from gpio_linux import BOILER_GPIO

_state = None


def setup():
    now = datetime.datetime.now()
    print(f"[{now}] setting gpio", BOILER_GPIO)
    global _state
    _state = False


def turn(is_on: bool):
    now = datetime.datetime.now()
    print(f"[{now}] boiler:", "on" if is_on else "off")
    global _state
    _state = is_on


def get():
    return _state
