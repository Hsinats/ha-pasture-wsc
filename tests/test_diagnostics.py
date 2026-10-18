from datetime import date
from types import SimpleNamespace

from custom_components.pasture_wsc.paddocks import diagnostic_summary
from tests.test_paddocks import state, DAY
from tests.test_ha_phase2 import ha_contract


def result():
    return {"day":DAY.isoformat(),"status":"pending_soil","primary":{"experimental_wsc":None},
            "scenario":{"experimental_wsc":13.7},"history_gap":True,"scenario_history_gap":False,
            "selected_moisture_method":"held_assumption","estimated_soil":{"assumed_days":3},
            "scenario_days":10,"scenario_valid_development_days":10}


def test_ready_estimate_overrides_missing_measured_route():
    p = state(scenario_enabled=True,moisture_mode="one_minus_wi_over_reference")
    summary = diagnostic_summary(result(),p["settings"])
    assert summary["calculation_status"] == "ready_estimated"
    assert summary["wsc_method"] == "estimated"
    assert summary["moisture_method"] == "held_assumption"
    assert summary["calculated_through"] == DAY.isoformat()
    assert summary["data_gaps"] == "3 days used assumed moisture"


def test_measured_selection_and_preference_change_diagnostics():
    settings = state(scenario_enabled=True)["settings"]
    p = result()
    p["primary"]["experimental_wsc"] = 12
    summary = diagnostic_summary(p,settings)
    assert summary["calculation_status"] == "ready_measured"
    assert summary["moisture_method"] == "measured"
    assert summary["assumed_moisture_days"] == 0
    settings["wsc_preference"] = "scenario"
    assert diagnostic_summary(p,settings)["calculation_status"] == "ready_estimated"
    settings["scenario_enabled"] = False
    assert diagnostic_summary(p,settings)["calculation_status"] == "ready_measured"


def test_pending_disabled_and_no_sensor_are_distinct():
    settings = state(moisture_mode="one_minus_wi_over_reference")["settings"]
    p = result()
    summary = diagnostic_summary(p,settings)
    assert summary["calculation_status"] == "waiting_for_soil"
    assert summary["moisture_method"] == "no_sensor_configured"
    assert summary["wsc_method"] == "no_result"
    assert summary["calculated_through"] is None
    settings["enabled"] = False
    assert diagnostic_summary(p,settings)["calculation_status"] == "disabled"
    settings.update(enabled=True,scenario_enabled=True)
    p["scenario"]["experimental_wsc"] = None
    p["scenario_history_gap"] = True
    p["scenario_valid_development_days"] = 8
    summary = diagnostic_summary(p,settings)
    assert summary["calculation_status"] == "missing_history"
    assert "2 days missing development inputs" in summary["data_gaps"]
    settings["moisture_mode"] = "unset"
    assert diagnostic_summary(p,settings)["calculation_status"] == "choose_moisture_response"


def test_fao_method_and_first_day():
    settings = state(scenario_enabled=True)["settings"]
    p = result()
    p["selected_moisture_method"] = "weather_estimate"
    assert diagnostic_summary(p,settings)["moisture_method"] == "fao_estimate"
    p.update(status="awaiting_first_completed_day",scenario={})
    assert diagnostic_summary(p,settings)["calculation_status"] == "waiting_first_day"


def test_sensor_labels_match_auto_route(ha_contract):
    from custom_components.pasture_wsc.sensor import PaddockSensor, PADDOCK_SENSORS
    settings = state(scenario_enabled=True)["settings"]
    coordinator = SimpleNamespace(entry=SimpleNamespace(entry_id="entry"),last_update_success=True,
        store=SimpleNamespace(data={"paddocks":{"summer":{"settings":settings}}}),
        data={"paddocks":{"summer":result()}})
    expected = {"paddock_status":"ready_estimated","input_quality":"estimated",
                "moisture_source":"held_assumption","paddock_last_completed_day":date(2026,6,1),
                "data_gaps":"3 days used assumed moisture","measured_model_status":"pending_soil"}
    for key,value in expected.items():
        sensor = PaddockSensor(coordinator,"summer",next(d for d in PADDOCK_SENSORS if d.key == key))
        assert sensor.native_value == value
