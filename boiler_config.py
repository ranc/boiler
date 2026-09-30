import json
import logging
import os
from typing import Dict, List, Tuple

'''
    Boiler schedule, stored as json (edited from the web page, or by hand):
    {
      "schedule": [
        {"days": [0], "start": "16:00", "end": "21:00"},
        {"days": [6, 7], "start": "07:00", "end": "08:30"}
      ]
    }
    days: 1-Sunday .. 7-Saturday, [0] means every day
    start, end: HH:MM or HH:MM:SS, local time. end is after start, a window doesn't cross midnight.
'''

MAX_ENTRIES = 20

logger = logging.getLogger('config')


def parse_time(text: str) -> int:
    '''HH:MM or HH:MM:SS -> seconds since midnight, raises ValueError'''
    parts = str(text).strip().split(':')
    if len(parts) not in (2, 3):
        raise ValueError(f"time must be HH:MM, got: {text}")
    try:
        h, m, s = (int(p) for p in parts + ['0'] * (3 - len(parts)))
    except ValueError:
        raise ValueError(f"time must be HH:MM, got: {text}")
    if h<0 or h>23 or m<0 or m>59 or s<0 or s>59:
        raise ValueError(f"time is out of range: {text}")
    return (h*60 + m)*60 + s


def format_time(sec: int) -> str:
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return f"{h:02d}:{m:02d}" + (f":{s:02d}" if s else "")


def normalize_entry(entry: Dict, where: str) -> Dict:
    if not isinstance(entry, dict):
        raise ValueError(f"{where}: must be an object")
    try:
        days = sorted(set(int(d) for d in entry.get("days", [])))
    except (TypeError, ValueError):
        raise ValueError(f"{where}: days must be numbers 1-7")
    if not days:
        raise ValueError(f"{where}: pick at least one day")
    if 0 in days or days == list(range(1, 8)):
        days = [0]
    elif days[0] < 1 or days[-1] > 7:
        raise ValueError(f"{where}: days must be 1 (Sunday) to 7 (Saturday)")
    try:
        start = parse_time(entry.get("start", ""))
        end = parse_time(entry.get("end", ""))
    except ValueError as e:
        raise ValueError(f"{where}: {e}")
    if end <= start:
        raise ValueError(f"{where}: end must be after start (split a window that crosses midnight in two)")
    return {"days": days, "start": format_time(start), "end": format_time(end)}


def normalize(data: Dict) -> Dict:
    '''validates the whole config, raises ValueError with a user readable message'''
    if not isinstance(data, dict):
        raise ValueError("config must be an object")
    schedule = data.get("schedule") or []
    if not isinstance(schedule, list):
        raise ValueError("schedule must be a list")
    if len(schedule) > MAX_ENTRIES:
        raise ValueError(f"up to {MAX_ENTRIES} heating times")
    entries = [normalize_entry(e, f"heating time {i}") for i, e in enumerate(schedule, 1)]
    entries.sort(key=lambda e: (parse_time(e["start"]), e["days"]))
    return {"schedule": entries}


def default_config() -> Dict:
    return {"schedule": []}


def load(path: str) -> Dict:
    '''reads and validates the config file; a bad entry is logged and skipped'''
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    entries = []
    for i, entry in enumerate(raw.get("schedule", []) if isinstance(raw, dict) else [], 1):
        try:
            entries.append(normalize_entry(entry, f"heating time {i}"))
        except ValueError as e:
            logger.error(f"{path}: ignored: {e}")
    return normalize({"schedule": entries[:MAX_ENTRIES]})


def save(path: str, data: Dict):
    '''atomic write, so the monitor never reads a half written file'''
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def import_legacy(path: str) -> Dict:
    '''
        converts the old sched.data of boiler.c: <day> <hh:mm>-<hh:mm> per line
        day: 1-Sunday .. 7-Saturday, 0 or * every day. lines starting with # or / are comments
    '''
    entries = []
    with open(path, "r") as f:
        for row, line in enumerate(f, 1):
            line = line.strip()
            if not line or line[0] in "#/":
                continue
            try:
                day, period = line.split()[:2]
                start, end = period.split("-")
                entries.append(normalize_entry({"days": [0 if day == "*" else day], "start": start, "end": end},
                                               f"row {row}"))
            except ValueError as e:
                logger.error(f"{path}: skipped: {e} ({line})")
    return normalize({"schedule": entries[:MAX_ENTRIES]})


def expand(config: Dict) -> List[Tuple[int, int, int]]:
    '''one (day, start sec, end sec) per entry and day, for the monitor'''
    return [(day, parse_time(e["start"]), parse_time(e["end"]))
            for e in config["schedule"] for day in e["days"]]
