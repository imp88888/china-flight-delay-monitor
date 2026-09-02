import os
from adapters.scrape_variflight import VariflightAdapter


def test_parse_variflight_fixture():
    path = os.path.join(os.path.dirname(__file__), "fixtures", "variflight_flight.html")
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()
    a = VariflightAdapter()
    data = a.parse(html)
    assert data["source"] == "variflight"
    assert data["status"] is not None
    assert "延误" in data["status"]
    assert data["scheduled_dep"] is not None
