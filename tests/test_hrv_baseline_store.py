from afferent.hrv_baseline_store import (
    baseline_for_bucket,
    daypart_bucket,
    update_baseline,
)


def test_daypart_bucket_start_of_day() -> None:
    assert daypart_bucket(0) == "00-03"


def test_daypart_bucket_mid_bucket() -> None:
    assert daypart_bucket(14) == "12-15"


def test_daypart_bucket_last_hour() -> None:
    assert daypart_bucket(23) == "21-24"


def test_daypart_bucket_on_a_boundary() -> None:
    assert daypart_bucket(9) == "09-12"


def test_baseline_for_bucket_none_when_empty() -> None:
    assert baseline_for_bucket({}, "09-12") is None


def test_baseline_for_bucket_mean_of_samples() -> None:
    store = {"09-12": [40.0, 42.0, 44.0]}
    assert baseline_for_bucket(store, "09-12") == 42.0


def test_baseline_for_bucket_ignores_other_buckets() -> None:
    store = {"09-12": [40.0], "12-15": [100.0]}
    assert baseline_for_bucket(store, "09-12") == 40.0


def test_update_baseline_appends_to_new_bucket() -> None:
    updated = update_baseline({}, "09-12", 41.0)
    assert updated == {"09-12": [41.0]}


def test_update_baseline_appends_to_existing_bucket() -> None:
    updated = update_baseline({"09-12": [40.0]}, "09-12", 42.0)
    assert updated == {"09-12": [40.0, 42.0]}


def test_update_baseline_does_not_mutate_input() -> None:
    original = {"09-12": [40.0]}
    update_baseline(original, "09-12", 42.0)
    assert original == {"09-12": [40.0]}


def test_update_baseline_caps_at_max_samples() -> None:
    store = {"09-12": [float(i) for i in range(14)]}
    updated = update_baseline(store, "09-12", 99.0)
    assert len(updated["09-12"]) == 14
    assert updated["09-12"][0] == 1.0  # oldest (0.0) dropped
    assert updated["09-12"][-1] == 99.0  # newest kept
