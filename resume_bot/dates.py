"""Normalise the five posted_at formats the sources return into a unix epoch.

  greenhouse/ashby/remoteok  ISO8601 with offset   2026-08-21T12:49:34-04:00
  adzuna                     ISO8601 with Z        2019-05-17T21:02:38Z
  remotive                   naive ISO8601         2026-09-04T16:53:29
  lever                      epoch milliseconds    1740765419645
  arbeitnow                  epoch seconds         1789844112
"""
import datetime as _dt


def to_epoch(value):
    """Return int epoch seconds, or None if it cannot be parsed."""
    if value is None:
        return None
    v = str(value).strip()
    if not v or v.lower() in ("none", "null"):
        return None

    if v.isdigit():
        n = int(v)
        # 13 digits is milliseconds, 10 is seconds
        if n > 10_000_000_000:
            n //= 1000
        # sanity: 2000-01-01 .. 2100-01-01
        return n if 946_684_800 < n < 4_102_444_800 else None

    iso = v.replace("Z", "+00:00")
    try:
        d = _dt.datetime.fromisoformat(iso)
    except ValueError:
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d",
                    "%a, %d %b %Y %H:%M:%S %z"):
            try:
                d = _dt.datetime.strptime(v[:len(fmt) + 8], fmt)
                break
            except ValueError:
                continue
        else:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=_dt.timezone.utc)
    return int(d.timestamp())


def age_days(epoch, now=None):
    if not epoch:
        return None
    now = now or _dt.datetime.now(_dt.timezone.utc).timestamp()
    return max(0.0, (now - epoch) / 86400.0)
