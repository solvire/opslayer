from pathlib import Path

from opslayer.operations import nut

FIXTURE = """battery.charge: 100
battery.charge.low: 10
battery.mfr.date: 2020/07/15
battery.runtime: 1056
device.model: Back-UPS ES 850G2
ups.load: 29
ups.status: OL
input.voltage: 121.0
"""


def test_status_parse(monkeypatch):
    monkeypatch.setattr(nut.runners, "upsc", lambda *a, **k: FIXTURE)
    result = nut.status()
    assert result["model"] == "Back-UPS ES 850G2"
    assert result["status"]["online"] is True
    assert result["status"]["on_battery"] is False
    assert result["battery_charge_percent"] == 100.0
    assert result["battery_runtime_seconds"] == 1056
    assert result["load_percent"] == 29.0


def test_on_battery_flags(monkeypatch):
    monkeypatch.setattr(nut.runners, "upsc", lambda *a, **k: "ups.status: OB DISCHRG\nbattery.charge: 45.2\n")
    result = nut.status()
    assert result["status"]["on_battery"] is True
    assert result["status"]["online"] is False
    assert result["status"]["discharging"] is True
    assert result["battery_charge_percent"] == 45.2


def test_low_battery_flags(monkeypatch):
    monkeypatch.setattr(nut.runners, "upsc", lambda *a, **k: "ups.status: OB LB RB\n")
    result = nut.status()
    assert result["status"]["low_battery"] is True
    assert result["status"]["replace_battery"] is True


def test_compact(monkeypatch):
    monkeypatch.setattr(nut.runners, "upsc", lambda *a, **k: FIXTURE)
    compact = nut.compact()
    assert compact["power"] == "online"
    assert compact["alerts"] == []
    assert compact["runtime_minutes"] == 17.6
