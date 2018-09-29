#!/usr/bin/env python3

import contextlib
import evdev
from evdev import InputEvent, SynEvent
from datetime import datetime, timedelta
from functools import reduce


def drain(dev):
    while dev.read_one() is not None:
        pass


@contextlib.contextmanager
def grabbed(dev):
    dev.grab()
    drain(dev)
    yield dev
    dev.ungrab()


def run_loop(device, on_event):
    with grabbed(device):
        for event in device.read_loop():
            on_event(event)
            if event.type == evdev.ecodes.EV_KEY:
                if event.code == 113:  # mute
                    drain(device)
                    break


names = {';': 'SEMICOLON', ',': 'COMMA', '.': 'DOT', '/': 'SLASH'}
def char_to_ev(c):
    name = names.get(c, c).upper()
    return getattr(evdev.ecodes, 'KEY_' + name)
left_to_right = {}
for left, right in [('qwert', 'yuiop'), ('asdfg', 'hjkl;'), ('zxcvb', 'nm,./')]:
    for l, r in zip(left, reversed(right)):
        ev_l = char_to_ev(l)
        ev_r = char_to_ev(r)
        left_to_right[ev_l] = ev_r


class EventTranlator:
    _space_down = None
    """When was the space pressed?"""
    _used = False
    """Were there any translations after the space was pressed?"""
    _next = None
    """Next event handler to call"""
    _active = None
    """Active translations.

    We only want to register translations on key press, and then translate until key release.
    This way it doesn't matter if you release space or the translated key first.
    """

    def __init__(self, next):
        self._next = next
        self._active = {}

    def __call__(self, event):
        if event.type == evdev.ecodes.EV_KEY:
            # If space is down and it's a new press, translate it
            if self._space_down and event.code in left_to_right and event.value == 1:
                print(event.code, '->', left_to_right[event.code])
                self._active[event.code] = left_to_right[event.code]
                self._used = True

            if event.code in self._active:
                new_code = self._active[event.code]
                if event.value == 0:
                    del self._active[event.code]
                event.code = new_code
                self._next(event)
            elif event.code == 57:  # Space
                if event.value == 1:  # press
                    self._space_down = self._space_down or datetime.now()
                    self._used = False
                elif event.value == 2:  # hold
                    pass
                elif event.value == 0:  # release
                    if datetime.now() - self._space_down < timedelta(seconds=0.25) and not self._used:
                        print('fast space', datetime.now() - self._space_down)
                        self._next(InputEvent(event.sec, event.usec, event.type, event.code, 1))
                        self._next(InputEvent(event.sec, event.usec, 0, 0, 0))
                        self._next(event)
                    self._space_down = None
                return
        self._next(event)


def logger(next):
    def handle(event):
        print(type(event))
        print(evdev.categorize(event))
        next(event)
    return handle


def compose(*steps):
    return reduce(lambda next, handler: handler(next), reversed(steps), lambda n: lambda ev: n(ev))


def injector(uinput):
    def _injector(next):
        def handle(event):
            print('   injecting', evdev.categorize(event))
            uinput.write_event(event)
        return handle
    return _injector



if __name__ == '__main__':
    import sys
    devices = [evdev.InputDevice(fn) for fn in evdev.list_devices()]
    if sys.argv[1] == 'ls':
        for dev in devices:
            print(dev)
    elif sys.argv[1] == 'mirror':
        device = [d for d in devices if sys.argv[2] in str(d)][0]
        uinput = evdev.uinput.UInput.from_device(device, name='keymapper')
        on_event = compose(
            #logger,
            EventTranlator,
            injector(uinput))
        run_loop(device, on_event)
