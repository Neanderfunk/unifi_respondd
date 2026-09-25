#!/usr/bin/env python3
"""Tests fuer die Airtime aus dem Controller (Neanderfunk)."""

from unittest.mock import patch

from unifi_respondd.respondd_client import ResponddClient
from unifi_respondd.unifi_client import Accesspoint, Accesspoints, get_ap_airtime


def _ap(airtime):
    return Accesspoint(
        name="ap", mac="0c:ea:14:00:00:01", snmp_location="",
        client_count=0, client_count24=0, client_count5=0, channel5=48,
        rx_bytes5=123456, tx_bytes5=654321, channel24=11, rx_bytes24=1, tx_bytes24=2,
        latitude=None, longitude=None, model="U6-Lite", firmware="6.6.77",
        uptime=1, contact="", load_avg=0.1, mem_used=1, mem_total=2048, mem_buffer=1,
        tx_bytes=2, rx_bytes=1, gateway="gw", gateway6="gw6",
        gateway_nexthop="aabbccddeeff", neighbour_macs=[], domain_code="x",
        airtime=airtime,
    )


def _client(ap):
    c = ResponddClient.__new__(ResponddClient)
    c._aps = Accesspoints(accesspoints=[ap])
    return c


def test_get_ap_airtime():
    ap = {"radio_table_stats": [
        {"radio": "ng", "channel": 11, "cu_total": 9, "cu_self_rx": 0, "cu_self_tx": 6},
        {"radio": "na", "channel": "48", "cu_total": "2", "cu_self_rx": None, "cu_self_tx": 2},
        {"radio": "6e", "channel": 37, "cu_total": 5, "cu_self_rx": 1, "cu_self_tx": 1},
        {"radio": "ng", "channel": 6},  # ohne cu_total: kaputt, bleibt weg
    ]}
    assert get_ap_airtime(ap) == {"ng": (11, 9.0, 0.0, 6.0), "na": (48, 2.0, 0.0, 2.0)}
    assert get_ap_airtime({}) == {}
    assert get_ap_airtime({"radio_table_stats": None}) == {}


def test_zaehler_ergeben_die_prozente():
    """Wie yanic rechnet: Differenz busy / Differenz active."""
    c = _client(_ap({"ng": (11, 17.0, 3.0, 6.0), "na": (48, 2.0, 0.0, 2.0)}))
    with patch("unifi_respondd.respondd_client.time.monotonic") as uhr:
        uhr.return_value = 1000.0
        vorher = {w.frequency: w for w in c.getStatistics()[0].wireless}
        uhr.return_value = 1060.0
        nachher = {w.frequency: w for w in c.getStatistics()[0].wireless}
    assert set(nachher) == {2462, 5240}
    g, v = nachher[2462], vorher[2462]
    aktiv = g.active - v.active
    assert aktiv == 60000
    assert 100 * (g.busy - v.busy) / aktiv == 17
    assert 100 * (g.rx - v.rx) / aktiv == 3
    assert 100 * (g.tx - v.tx) / aktiv == 6


def test_zaehler_steigen_auch_bei_neuen_prozenten():
    ap = _ap({"ng": (11, 50.0, 10.0, 10.0)})
    c = _client(ap)
    with patch("unifi_respondd.respondd_client.time.monotonic") as uhr:
        uhr.return_value = 0.0
        c.getStatistics()
        uhr.return_value = 60.0
        a = c.getStatistics()[0].wireless[0]
        ap.airtime = {"ng": (11, 10.0, 0.0, 0.0)}
        uhr.return_value = 120.0
        b = c.getStatistics()[0].wireless[0]
    assert b.active > a.active and b.busy > a.busy
    assert 100 * (b.busy - a.busy) / (b.active - a.active) == 10


def test_ohne_airtime_wie_bisher_nur_kanal():
    c = _client(_ap({}))
    frequenzen = {w.frequency for w in c.getStatistics()[0].wireless}
    assert frequenzen == {2462, 5240}


def test_json_wie_gluon():
    c = _client(_ap({"na": (48, 2.0, 0.0, 2.0)}))
    w = c.getStatistics()[0].to_dict()["wireless"][0]
    assert set(w) >= {"frequency", "active", "busy", "rx", "tx"}
