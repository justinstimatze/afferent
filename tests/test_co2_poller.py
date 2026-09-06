from afferent.co2_poller import _parse_line


def test_parse_line_valid() -> None:
    reading = _parse_line("co2=966,temp=24.3,rh=64")
    assert reading is not None
    assert reading["co2"] == 966
    assert reading["temp"] == 24.3
    assert reading["rh"] == 64.0
    assert "ts" in reading


def test_parse_line_malformed() -> None:
    assert _parse_line("garbage") is None


def test_parse_line_empty() -> None:
    assert _parse_line("") is None


def test_parse_line_negative_temp() -> None:
    reading = _parse_line("co2=420,temp=-3.2,rh=12")
    assert reading is not None
    assert reading["temp"] == -3.2
