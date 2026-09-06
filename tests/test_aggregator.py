from afferent.aggregator import (
    _co2_bucket,
    _factors,
    _focus_label,
    _gate_ppi_sample,
    _hrv_bucket,
    _intervention_for,
    _plausible,
    _rmssd,
    _session_minutes,
)


def test_plausible_accepts_in_range() -> None:
    assert _plausible(950, 200, 10000) is True
    assert _plausible(950.5, 200, 10000) is True


def test_plausible_rejects_out_of_range() -> None:
    assert _plausible(50, 200, 10000) is False
    assert _plausible(20000, 200, 10000) is False


def test_plausible_rejects_wrong_type() -> None:
    assert _plausible("950", 200, 10000) is False
    assert _plausible(None, 200, 10000) is False


def test_plausible_rejects_bool() -> None:
    # bool is a subclass of int in Python -- must not slip through a
    # numeric-range check meant for real sensor values.
    assert _plausible(True, 200, 10000) is False


def test_gate_ppi_sample_clean() -> None:
    assert _gate_ppi_sample({"invalid": False, "skin_contact": True}) is True


def test_gate_ppi_sample_invalid() -> None:
    assert _gate_ppi_sample({"invalid": True, "skin_contact": True}) is False


def test_gate_ppi_sample_no_skin_contact() -> None:
    assert _gate_ppi_sample({"invalid": False, "skin_contact": False}) is False


def test_rmssd_known_value() -> None:
    # successive diffs [10, -20] -> sqrt(mean([100, 400])) = sqrt(250)
    result = _rmssd([900.0, 910.0, 890.0], gated_count=0, max_gated_fraction=0.3)
    assert result is not None
    assert round(result, 3) == round(250**0.5, 3)


def test_rmssd_too_few_samples() -> None:
    assert _rmssd([900.0], gated_count=0, max_gated_fraction=0.3) is None
    assert _rmssd([], gated_count=0, max_gated_fraction=0.3) is None


def test_rmssd_too_many_gated() -> None:
    # 4 gated out of 6 total (0.667) exceeds the 0.3 max
    assert _rmssd([900.0, 910.0], gated_count=4, max_gated_fraction=0.3) is None


def test_rmssd_gated_within_tolerance() -> None:
    # 1 gated out of 4 total (0.25) is within the 0.3 max
    result = _rmssd([900.0, 910.0, 890.0], gated_count=1, max_gated_fraction=0.3)
    assert result is not None


def test_co2_bucket_normal() -> None:
    assert _co2_bucket(800, elevated=1000, high=1200) == "normal"


def test_co2_bucket_approaching() -> None:
    assert _co2_bucket(1000, elevated=1000, high=1200) == "approaching"
    assert _co2_bucket(1199, elevated=1000, high=1200) == "approaching"


def test_co2_bucket_high() -> None:
    assert _co2_bucket(1200, elevated=1000, high=1200) == "high"
    assert _co2_bucket(1800, elevated=1000, high=1200) == "high"


def test_hrv_bucket_warming_before_baseline() -> None:
    assert _hrv_bucket(rmssd=42.0, baseline=None, drop_pct=30) == "warming"


def test_hrv_bucket_insufficient_data() -> None:
    assert _hrv_bucket(rmssd=None, baseline=40.0, drop_pct=30) == "insufficient data"


def test_hrv_bucket_at_baseline() -> None:
    assert _hrv_bucket(rmssd=38.0, baseline=40.0, drop_pct=30) == "at baseline"


def test_hrv_bucket_below_baseline() -> None:
    # 40 -> 20 is a 50% drop, past the 30% threshold
    assert _hrv_bucket(rmssd=20.0, baseline=40.0, drop_pct=30) == "below baseline"


def test_hrv_bucket_boundary_exactly_at_threshold() -> None:
    # 40 -> 28 is exactly a 30% drop
    assert _hrv_bucket(rmssd=28.0, baseline=40.0, drop_pct=30) == "below baseline"


def test_focus_label_warming() -> None:
    assert _focus_label("warming", session_minutes=1.0, fatigue_minutes=90) == "warming"


def test_focus_label_unknown_on_insufficient_data() -> None:
    label = _focus_label("insufficient data", session_minutes=30.0, fatigue_minutes=90)
    assert label == "unknown"


def test_focus_label_focused_at_baseline() -> None:
    label = _focus_label("at baseline", session_minutes=30.0, fatigue_minutes=90)
    assert label == "focused"


def test_focus_label_scattered_below_baseline_short_session() -> None:
    label = _focus_label("below baseline", session_minutes=30.0, fatigue_minutes=90)
    assert label == "scattered"


def test_focus_label_fatigued_below_baseline_long_session() -> None:
    label = _focus_label("below baseline", session_minutes=95.0, fatigue_minutes=90)
    assert label == "fatigued"


def test_intervention_fires_on_high_co2() -> None:
    assert _intervention_for(1300, elevated=1000, high=1200) == "crack a window"


def test_intervention_none_below_high_threshold() -> None:
    assert _intervention_for(1100, elevated=1000, high=1200) is None


def test_intervention_none_when_co2_unknown() -> None:
    assert _intervention_for(None, elevated=1000, high=1200) is None


def test_session_minutes() -> None:
    assert _session_minutes(start_monotonic=0.0, now_monotonic=90.0) == 1.5


def test_factors_empty_when_all_normal() -> None:
    factors = _factors(
        co2_bucket="normal",
        hrv_bucket="at baseline",
        session_minutes=10.0,
        fatigue_minutes=90,
        gated_fraction=0.0,
        low_confidence_gated_fraction=0.15,
    )
    assert factors == []


def test_factors_co2_approaching() -> None:
    factors = _factors(
        co2_bucket="approaching",
        hrv_bucket="at baseline",
        session_minutes=10.0,
        fatigue_minutes=90,
        gated_fraction=0.0,
        low_confidence_gated_fraction=0.15,
    )
    assert factors == ["co2_approaching"]


def test_factors_co2_high() -> None:
    factors = _factors(
        co2_bucket="high",
        hrv_bucket="at baseline",
        session_minutes=10.0,
        fatigue_minutes=90,
        gated_fraction=0.0,
        low_confidence_gated_fraction=0.15,
    )
    assert factors == ["co2_high"]


def test_factors_hrv_below_baseline() -> None:
    factors = _factors(
        co2_bucket="normal",
        hrv_bucket="below baseline",
        session_minutes=10.0,
        fatigue_minutes=90,
        gated_fraction=0.0,
        low_confidence_gated_fraction=0.15,
    )
    assert factors == ["hrv_below_baseline"]


def test_factors_hrv_warming() -> None:
    factors = _factors(
        co2_bucket="normal",
        hrv_bucket="warming",
        session_minutes=10.0,
        fatigue_minutes=90,
        gated_fraction=0.0,
        low_confidence_gated_fraction=0.15,
    )
    assert factors == ["hrv_warming"]


def test_factors_hrv_insufficient_data_adds_nothing() -> None:
    # "insufficient data" isn't a factor on its own -- focus_label already
    # reports "unknown" for it, and there's nothing actionable to name.
    factors = _factors(
        co2_bucket="normal",
        hrv_bucket="insufficient data",
        session_minutes=10.0,
        fatigue_minutes=90,
        gated_fraction=0.0,
        low_confidence_gated_fraction=0.15,
    )
    assert factors == []


def test_factors_session_over_fatigue_threshold() -> None:
    factors = _factors(
        co2_bucket="normal",
        hrv_bucket="at baseline",
        session_minutes=95.0,
        fatigue_minutes=90,
        gated_fraction=0.0,
        low_confidence_gated_fraction=0.15,
    )
    assert factors == ["session_over_fatigue_threshold"]


def test_factors_low_confidence_boundary() -> None:
    below = _factors(
        co2_bucket="normal",
        hrv_bucket="below baseline",
        session_minutes=10.0,
        fatigue_minutes=90,
        gated_fraction=0.14,
        low_confidence_gated_fraction=0.15,
    )
    assert "hrv_low_confidence" not in below

    at = _factors(
        co2_bucket="normal",
        hrv_bucket="below baseline",
        session_minutes=10.0,
        fatigue_minutes=90,
        gated_fraction=0.15,
        low_confidence_gated_fraction=0.15,
    )
    assert "hrv_low_confidence" in at


def test_factors_low_confidence_none_gated_fraction_adds_nothing() -> None:
    # No PPI events at all yet -- gated_fraction is None, not 0 -- must not
    # be misread as "perfectly clean data".
    factors = _factors(
        co2_bucket="normal",
        hrv_bucket="warming",
        session_minutes=10.0,
        fatigue_minutes=90,
        gated_fraction=None,
        low_confidence_gated_fraction=0.15,
    )
    assert factors == ["hrv_warming"]


def test_factors_combine() -> None:
    factors = _factors(
        co2_bucket="high",
        hrv_bucket="below baseline",
        session_minutes=95.0,
        fatigue_minutes=90,
        gated_fraction=0.2,
        low_confidence_gated_fraction=0.15,
    )
    assert factors == [
        "co2_high",
        "hrv_below_baseline",
        "session_over_fatigue_threshold",
        "hrv_low_confidence",
    ]
