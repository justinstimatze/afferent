from polar_python.models import HRData, PPIData

from afferent.polar_poller import _hr_reading, _ppi_readings


def test_hr_reading() -> None:
    reading = _hr_reading(HRData(heartrate=62, rr_intervals=[968.75, 972.5]))
    assert reading["hr_bpm"] == 62
    assert reading["rr_intervals_ms"] == [968.75, 972.5]
    assert "ts" in reading


def test_ppi_readings_maps_all_samples() -> None:
    data = PPIData(
        timestamp=0,
        samples=[
            PPIData.PPISample(
                ppi=812,
                error_estimate=12,
                hr=74,
                invalid_ppi=False,
                skin_contact_status=True,
                skin_contact_supported=True,
            ),
            PPIData.PPISample(
                ppi=0,
                error_estimate=511,
                hr=0,
                invalid_ppi=True,
                skin_contact_status=False,
                skin_contact_supported=True,
            ),
        ],
    )
    readings = _ppi_readings(data)
    assert len(readings) == 2
    assert readings[0] == {
        "ppi_ms": 812,
        "error_estimate_ms": 12,
        "hr_bpm": 74,
        "invalid": False,
        "skin_contact": True,
        "skin_contact_supported": True,
        "ts": readings[0]["ts"],
    }
    assert readings[1]["invalid"] is True
    assert readings[1]["skin_contact"] is False
