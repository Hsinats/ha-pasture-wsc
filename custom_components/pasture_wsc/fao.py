"""FAO-56 daily Penman-Monteith ET: equations 6–8, 11–13, 17, 19, 37–40, 47.

https://www.fao.org/4/X0490E/x0490e07.htm
https://www.fao.org/4/X0490E/x0490e08.htm
"""
from math import exp, isfinite, log, sqrt
from .engine.astronomy import extraterrestrial_radiation


def numeric(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and isfinite(value)


def saturation(t):
    return .6108 * exp(17.27*t/(t+237.3))


def reference_et(day, latitude, elevation, tmin, tmax, solar, *, humidity=None,
                 rhmin=None, rhmax=None, wind=None, wind_height=10, vapour_pressure=None):
    """Return mm/day; flag temporary missing-data estimates from FAO chapter 3."""
    if not all(numeric(v) for v in (latitude,elevation,tmin,tmax,solar)):
        raise ValueError("Missing FAO temperature extremes, solar or location")
    if not -90 <= latitude <= 90 or not -500 <= elevation <= 9000 or not -90 <= tmin <= tmax <= 65 or not 0 <= solar <= 100:
        raise ValueError("Invalid FAO input range")
    flags = []
    mean = (tmin+tmax)/2
    es = (saturation(tmin)+saturation(tmax))/2
    if numeric(vapour_pressure) and 0 <= vapour_pressure <= es:
        ea = vapour_pressure
    elif numeric(rhmin) and numeric(rhmax) and 0 <= rhmin <= rhmax <= 100:
        ea = (saturation(tmin)*rhmax+saturation(tmax)*rhmin)/200
    elif numeric(humidity) and 0 <= humidity <= 100:
        ea = es*humidity/100
        flags.append("mean_humidity_approximation_eq19")
    else:
        ea = saturation(tmin)
        flags.append("dewpoint_equals_tmin_assumed_eq48")
    if numeric(wind) and wind >= 0:
        if not numeric(wind_height) or not .5 <= wind_height <= 100:
            raise ValueError("Invalid wind measurement height")
        u2 = wind*4.87/log(67.8*wind_height-5.42)
    else:
        u2 = 2.0
        flags.append("wind_2m_s_assumed_at_2m")
    u2 = max(.5,u2)
    pressure = 101.3*((293-.0065*elevation)/293)**5.26
    gamma = .000665*pressure
    slope = 4098*saturation(mean)/(mean+237.3)**2
    ra = extraterrestrial_radiation(day,latitude)
    rso = (.75+2e-5*elevation)*ra
    if rso <= 1e-6:
        raise ValueError("Polar-night net radiation unsupported")
    ratio = min(1,max(.3,solar/rso))
    rns = .77*solar
    rnl = 4.903e-9*((tmax+273.16)**4+(tmin+273.16)**4)/2*(.34-.14*sqrt(ea))*(1.35*ratio-.35)
    rn = rns-rnl
    eto = max(0,(.408*slope*rn+gamma*900/(mean+273)*u2*max(0,es-ea))/(slope+gamma*(1+.34*u2)))
    return {"eto_mm":eto,"net_radiation_mj_m2":rn,"vapour_pressure_kpa":ea,
            "wind_2m_m_s":u2,"ra_mj_m2":ra,"flags":flags}
