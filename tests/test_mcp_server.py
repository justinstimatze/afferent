from afferent.mcp_server import _apply_biometric_policy


def test_biometric_policy_passes_through_when_exposed() -> None:
    state = {
        "hr_bpm": 62.0, "hrv_rmssd_ms": 41.5, "co2_ppm": 900, "hrv_bucket": "warming",
    }
    assert _apply_biometric_policy(state, expose_raw_biometrics=True) == state


def test_biometric_policy_strips_raw_fields_when_not_exposed() -> None:
    state = {
        "hr_bpm": 62.0, "hrv_rmssd_ms": 41.5, "co2_ppm": 900, "hrv_bucket": "warming",
    }
    result = _apply_biometric_policy(state, expose_raw_biometrics=False)
    assert result == {"co2_ppm": 900, "hrv_bucket": "warming"}


def test_biometric_policy_tolerates_missing_raw_fields() -> None:
    state = {"co2_ppm": 900, "hrv_bucket": "warming"}
    assert _apply_biometric_policy(state, expose_raw_biometrics=False) == state


def test_biometric_policy_does_not_mutate_input() -> None:
    state = {"hr_bpm": 62.0, "hrv_rmssd_ms": 41.5}
    _apply_biometric_policy(state, expose_raw_biometrics=False)
    assert state == {"hr_bpm": 62.0, "hrv_rmssd_ms": 41.5}
