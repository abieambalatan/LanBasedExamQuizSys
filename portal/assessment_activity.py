"""Validate browser-reported observations; never infer an OS shortcut from them."""

import json
from django.core.exceptions import BadRequest

MAX_ACTIVITY_EVENTS = 2000
EVENT_TYPES = frozenset({
    "attempt_started", "attempt_resumed", "focus_lost", "focus_returned",
    "page_hidden", "page_visible", "warning_started", "warning_acknowledged",
    "submit_manual", "submit_time_limit", "submit_tab_switch",
})


def normalize_activity_log(value):
    # Older clients and results have no activity evidence, rather than zero events.
    if value is None:
        return None
    if (not isinstance(value, dict) or type(value.get("version")) is not int
            or value["version"] != 1 or not isinstance(value.get("events"), list)
            or len(value["events"]) > MAX_ACTIVITY_EVENTS
            or type(value.get("complete")) is not bool
            or type(value.get("truncated")) is not bool):
        raise BadRequest("Invalid assessment activity log.")
    events = []
    for item in value["events"]:
        if (not isinstance(item, dict) or not isinstance(item.get("type"), str)
                or item["type"] not in EVENT_TYPES
                or type(item.get("at")) is not int or not 0 <= item["at"] <= 8640000000000000
                or type(item.get("hidden")) is not bool
                or type(item.get("focused")) is not bool):
            raise BadRequest("Invalid assessment activity event.")
        # Keep arrival order: the student's device clock can move backwards.
        events.append({key: item[key] for key in ("type", "at", "hidden", "focused")})
    return {"version": 1, "complete": value["complete"], "truncated": value["truncated"], "events": events}


def activity_summary(raw):
    if not raw:
        return None
    log = json.loads(raw)
    return {
        "focusLossCount": sum(e["type"] == "focus_lost" for e in log["events"]),
        "hiddenCount": sum(e["type"] == "page_hidden" for e in log["events"]),
        "warningCount": sum(e["type"] == "warning_started" for e in log["events"]),
        "complete": log["complete"], "truncated": log["truncated"],
    }


def merge_activity_logs(saved, incoming):
    """An older request or stale submission cannot erase already received events."""
    if saved is None:
        return incoming
    if incoming is None:
        return saved
    before, after = saved["events"], incoming["events"]
    if len(after) >= len(before) and after[:len(before)] == before:
        return {**incoming, "complete": saved["complete"] and incoming["complete"],
                "truncated": saved["truncated"] or incoming["truncated"]}
    return saved
