from datetime import date
import pytest
from pasture_wsc.astronomy import daylength, local_day_bounds, cloud_radiation, extraterrestrial_radiation


@pytest.mark.parametrize("day,hours", [(date(2026,3,8),23),(date(2026,11,1),25),(date(2024,2,29),24)])
def test_civil_days(day,hours):
    a,b = local_day_bounds(day,"America/Toronto")
    assert (b-a).total_seconds() == hours*3600


def test_geometry_and_poles():
    assert daylength(date(2024,2,29),0) == pytest.approx(12)
    assert daylength(date(2026,6,21),90) == 24
    assert daylength(date(2026,12,21),90) == 0
    assert daylength(date(2026,6,21),-90) == 0
    assert 15 < daylength(date(2026,6,21),43.7) < 16
    # FAO-56 Example 8: latitude 20 S, 3 September (J=246), Ra ~32.2.
    assert extraterrestrial_radiation(date(2025,9,3),-20) == pytest.approx(32.2, abs=.1)


def test_cloud_scenario_missing_and_night():
    day = date(2026,12,21)
    assert cloud_radiation(day,43,None) is None
    assert cloud_radiation(day,43,None,assume_clear=True) > 0
    assert cloud_radiation(day,90,20) == 0
    assert cloud_radiation(day,43,100) == pytest.approx(cloud_radiation(day,43,0)*.25)
    with pytest.raises(ValueError):
        cloud_radiation(day,43,101)
