"""While something started by hand runs on a device (a panel button, 試走), its main scripts wait - as for a schedule."""
from types import SimpleNamespace as R

from runtime.shadow import scripts_wait_for


def test_a_hand_started_run_makes_the_main_scripts_wait():
    assert scripts_wait_for(R(result=None, origin={"manual": True, "script_name": "手動執行(面板)"})) == (None, "手動執行(面板)")
    assert scripts_wait_for(R(result="success", origin={"manual": True, "script_name": "x"})) == (None, None)   # it ended


def test_a_schedule_as_before_and_a_scripts_own_run_does_not_hold():
    assert scripts_wait_for(R(result=None, origin={"schedule": "s", "schedule_name": "排程「日程」", "pause_others": True})) == ("排程「日程」", None)
    assert scripts_wait_for(R(result=None, origin={"schedule": "s", "schedule_name": "排程「日程」", "pause_others": False})) == (None, None)
    assert scripts_wait_for(R(result=None, origin={"script": "patrol", "script_name": "自動巡邏"})) == (None, None)
    assert scripts_wait_for(None) == (None, None)
