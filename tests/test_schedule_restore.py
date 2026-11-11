"""After a restart, a schedule that was running carries on, unless today's mark says that very run already ended."""
from runtime.shadow import snapshot_finished


def test_no_mark_carries_on():
    assert not snapshot_finished(None, {"job": "20261111_150000_daily_dev", "t": 100})


def test_the_runs_own_mark_means_it_ended():
    assert snapshot_finished({"run": "20261111_150000_daily_dev", "t": 90}, {"job": "20261111_150000_daily_dev", "t": 100})


def test_an_earlier_failed_run_does_not_stop_a_run_now_restart():
    # failed in the morning, started again by hand: the morning's mark must not drop the new run
    mark = {"run": "20261111_080000_daily_dev", "t": 50, "result": "failed"}
    assert not snapshot_finished(mark, {"job": "20261111_150000_daily_dev", "t": 100})


def test_without_ids_the_times_decide():
    assert snapshot_finished({"t": 120}, {"t": 100})
    assert not snapshot_finished({"t": 50}, {"t": 100})
