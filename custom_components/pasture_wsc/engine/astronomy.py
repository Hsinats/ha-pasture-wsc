"""FAO-56 extraterrestrial geometry; geometric horizon, no refraction."""
from datetime import date, datetime, time, timedelta, timezone
from math import acos, cos, sin, tan, pi, isfinite
from zoneinfo import ZoneInfo


def local_day_bounds(day: date, zone: str) -> tuple[datetime, datetime]:
    """Return UTC bounds; subtracting local datetimes would hide DST changes."""
    tz = ZoneInfo(zone)
    return (datetime.combine(day, time(), tz).astimezone(timezone.utc),
            datetime.combine(day + timedelta(days=1), time(), tz).astimezone(timezone.utc))


def geometry(day: date, latitude: float) -> tuple[float, float, float]:
    if not isfinite(latitude) or not -90 <= latitude <= 90:
        raise ValueError("Latitude outside -90..90")
    j = day.timetuple().tm_yday
    phi = latitude * pi / 180
    declination = 0.409 * sin(2 * pi * j / 365 - 1.39)
    argument = -tan(phi) * tan(declination)
    sunset = acos(min(1, max(-1, argument)))
    return phi, declination, sunset


def daylength(day: date, latitude: float) -> float:
    return 24 / pi * geometry(day, latitude)[2]


def extraterrestrial_radiation(day: date, latitude: float) -> float:
    """Daily MJ/m², FAO-56 equations 21, 23–25 (365-day approximation)."""
    phi, dec, sunset = geometry(day, latitude)
    distance = 1 + 0.033 * cos(2 * pi * day.timetuple().tm_yday / 365)
    return max(0, 24 * 60 / pi * 0.0820 * distance *
               (sunset * sin(phi) * sin(dec) + cos(phi) * cos(dec) * sin(sunset)))


def cloud_radiation(day: date, latitude: float, cloud_percent: float | None,
                    *, assume_clear: bool = False, transmission: float = 0.75) -> float | None:
    """Uncalibrated daily scenario: Ra * transmission * (1 - .75 C³).

    Requires time-weighted daylight cloud coverage upstream. A daily total,
    never instantaneous nighttime irradiance. No statistical uncertainty claim.
    """
    if not isfinite(transmission) or not 0 <= transmission <= 1:
        raise ValueError("Transmission outside 0..1")
    if cloud_percent is None:
        if not assume_clear:
            return None
        cloud_percent = 0
    if not isfinite(cloud_percent) or not 0 <= cloud_percent <= 100:
        raise ValueError("Cloud cover outside 0..100")
    return extraterrestrial_radiation(day, latitude) * transmission * (1 - 0.75 * (cloud_percent / 100) ** 3)
