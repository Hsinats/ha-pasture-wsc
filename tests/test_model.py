import math
import pytest
from pasture_wsc.model import calculate, SoilIndex, MoistureMode, VIGOR_REGROWTH


def test_paper_table_2_coefficients():
    p = VIGOR_REGROWTH
    # Independently transcribed Vigor N40 regrowth column, Table 2, p.10.
    assert tuple(vars(p).values())[1:] == (20, .80, 10, .234, 4, .271, 6.195, .993, .090, 6, .073, 2, 8, .100, 5, 8, .47)


@pytest.mark.parametrize("l,t,r", [(0,-20,0), (10,4,2)])
def test_thresholds(l,t,r):
    result = calculate(l,t,r,0,SoilIndex(.47,"test compatible index",True),MoistureMode.INCREASING)
    assert result.development == 0
    assert result.radiation_effect == result.temperature_effect == result.experimental_wsc == 0


def test_independent_reference():
    # L = 10+ln(2)/.8, T = 4+ln(2)/.234 => factors each .5.
    t = 4 + math.log(2)/.234
    r = 2 + math.log(2)/.073
    result = calculate(10+math.log(2)/.8,t,r,1,SoilIndex(.271,"reference",True),MoistureMode.INCREASING)
    assert result.photoperiod_factor == pytest.approx(.5)
    assert result.temperature_factor == pytest.approx(.5)
    assert result.development == pytest.approx(.25)
    assert result.trend == pytest.approx(5.661804999255706)
    assert result.radiation_effect == pytest.approx(3)
    expected = 6.195 * math.exp(-.09) + 3 - 8*(1-math.exp(-.1*(t-5))) + 8*(.271/.47-1)
    assert result.experimental_wsc == pytest.approx(expected)


def test_moisture_variants_and_unclamped_output():
    a = calculate(16,20,20,10,SoilIndex(0,"index",True),MoistureMode.INCREASING)
    b = calculate(16,20,20,10,SoilIndex(0,"index",True),MoistureMode.DECREASING)
    assert a.moisture_effect == -8
    assert b.moisture_effect == 8
    negative = calculate(0,30,0,0,SoilIndex(0,"index",True),MoistureMode.INCREASING)
    assert negative.experimental_wsc < 0
    assert "implausible_percentage_unclamped" in negative.warnings


def test_unknown_uncalibrated_and_assumed():
    for soil in (None, SoilIndex(30,"VWC percent"), SoilIndex(.4,"assumption",True,True)):
        result = calculate(15,20,20,None,soil,MoistureMode.DECREASING)
        assert result.development is None and result.experimental_wsc is None
        assert result.radiation_effect is not None
    result = calculate(15,20,20,1,SoilIndex(.4,"assumption",True,True),MoistureMode.DECREASING,scenario=True)
    assert result.status == "scenario"
    assert calculate(15,20,20,1,SoilIndex(.4,"index",True)).experimental_wsc is None


@pytest.mark.parametrize("kwargs", [{"daylength":25}, {"temperature":float('nan')}, {"radiation":-1}, {"spechr":-1}])
def test_invalid(kwargs):
    inputs = dict(daylength=12, temperature=20, radiation=20, spechr=1)
    inputs.update(kwargs)
    with pytest.raises(ValueError):
        calculate(**inputs)
