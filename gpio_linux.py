import os
import time


BOILER_GPIO = 4 # BCM pin of the boiler relay (header pin 7), the relay is active low
_base = f"/sys/class/gpio/gpio{BOILER_GPIO}"


def setup():
    '''exports the pin as an output, starting high (relay off) so the boiler doesn't glitch on'''
    if not os.path.exists(_base):
        try:
            with open("/sys/class/gpio/export", "w") as f:
                f.write(str(BOILER_GPIO))
        except OSError as ex:
            print(f"Warning exporting gpio {BOILER_GPIO}:", ex)
    # right after the export udev needs a moment to give the gpio group access
    for attempt in range(20):
        try:
            with open(_base + "/direction", "r") as f:
                if f.read().strip() == "out":
                    return # already set up, keep the current relay state
            with open(_base + "/direction", "w") as f:
                f.write("high") # output, initially high = off
            return
        except OSError as ex:
            if attempt == 19:
                print(f"Warning setting gpio {BOILER_GPIO} direction:", ex)
            time.sleep(0.1)


def turn(is_on: bool):
    gpiofile = _base + "/value"
    if not os.path.exists(gpiofile):
        print("setting gpio", BOILER_GPIO)
        setup()
    with open(gpiofile, "w") as f:
        f.write('0' if is_on else '1')


def get():
    '''returns True if the relay is on (active low), None if the pin is not set up'''
    gpiofile = _base + "/value"
    if not os.path.exists(gpiofile):
        return None
    with open(gpiofile, "r") as f:
        return f.read().strip() == '0'
