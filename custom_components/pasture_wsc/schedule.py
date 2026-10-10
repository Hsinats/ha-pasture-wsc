"""Civil-time scheduling independent of the HA process's timezone."""
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


def scheduled_day(now,zone,clock):
    local = now.astimezone(ZoneInfo(zone))
    return local.date()-timedelta(days=1 if local.time() >= time.fromisoformat(clock) else 2)


def next_run(now, zone, clock):
    tz = ZoneInfo(zone)
    local_day = now.astimezone(tz).date()
    for days in range(3):
        candidate = datetime.combine(local_day+timedelta(days=days),time.fromisoformat(clock),tz)
        # First fold only; nonexistent civil times move forward across the DST gap.
        candidate = candidate.astimezone(timezone.utc)
        if candidate > now:
            return candidate
    raise ValueError("No next schedule time")
