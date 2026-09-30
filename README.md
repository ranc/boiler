# boiler

Boiler on/off scheduler with a web UI, running on a Raspberry Pi. It's one Python process (`boiler_server.py`, a systemd unit) that:

- checks every second whether the boiler should be on: a manual override if there is one, otherwise the weekly schedule
- switches the relay on **GPIO4** (BCM, header pin 7, active low: `0` = on) through sysfs
- serves the web page and a JSON API on port 80

It runs on Raspberry Pi, version 5.4.51+ #1333 Mon Aug 10 16:38:02 BST 2020 armv6l GNU/Linux,
with Python 3.7 at /usr/bin/python3, so it has to stay 3.7 compatible (no walrus, no 3.8+ APIs). It uses only the standard library.

## Files

| File | Role |
|---|---|
| `boiler_server.py` | Entry point: `BoilerMonitor` thread (schedule + override → relay), the API routes, shutdown |
| `boiler_config.py` | Load, validate, save the JSON schedule; one-time import of the old `sched.data` |
| `web_server.py` | Generic stdlib HTTP server (static whitelist + JSON GET/POST), same as the garden project |
| `website/index.html` | The whole UI: status, manual on/off, schedule editor |
| `gpio_linux.py` / `gpio_nt.py` | sysfs GPIO for the relay / Windows stub for local runs |
| `deploy/boiler.service` | systemd unit, install steps in its header |
| `sched.data` | The old schedule of the C version, imported once into the JSON config |

## Schedule and override

`/home/pi/boiler_config.json` (hot reloaded on change, written by the page):

```json
{"schedule": [{"days": [0], "start": "16:00", "end": "21:00"},
              {"days": [1, 7], "start": "07:00", "end": "08:30"}]}
```

`days`: 1 = Sunday … 7 = Saturday, `[0]` = every day. A window is `start <= now < end` and doesn't cross midnight.
If the file doesn't exist, it's imported from `/home/pi/boiler/sched.data` (`<day|0|*> HH:MM-HH:MM` per line).

A manual override turns the boiler on or off for 1 min to 24 h, whatever the schedule says. It's saved in
`/home/pi/boiler_override.json` with an absolute end time, so it survives a restart and midnight.
On service stop the relay is turned off.

## API

| Method & path | Body | |
|---|---|---|
| `GET /api/state` | | `{now, boiler (actual), wanted, reason, override, schedule_on, next_change, config, history, monitor, ...}` |
| `POST /api/override` | `{"on": true, "sec": 3600}` | manual on/off for `sec` seconds |
| `POST /api/clear` | `{}` | end the manual override |
| `POST /api/schedule` | `{"schedule": [...]}` | replace and save the schedule |

POSTs need `Content-Type: application/json`. Bad input returns 400 `{"error": ...}`. There's no auth, so keep it on the LAN.

```
curl http://pi/api/state
curl -X POST -H 'Content-Type: application/json' -d '{"on":true,"sec":3600}' http://pi/api/override
```

## Install on the Pi

See the header of `deploy/boiler.service`: remove the old `boiler check` cron job, disable Apache, install and enable the unit.

## Running locally

`python boiler_server.py` on Windows uses `gpio_nt` (prints relay changes), `test_config.json` (imported from `sched.data`)
and serves http://localhost:8080. Set `BOILER_HTTP_PORT` to change the port.
