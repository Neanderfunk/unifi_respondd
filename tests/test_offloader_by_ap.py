#!/usr/bin/env python3
"""Tests fuer den lokalen Zusatz offloader_by_ap (Neanderfunk).

Der Router je Accesspoint kommt aus einer Datei, die der Kartenserver aus
der batman-Uebersetzungstabelle erzeugt. Er gilt vor dem Router der Site.
"""

import json
from unittest.mock import Mock, patch

from unifi_respondd.unifi_client import get_infos, load_offloader_by_ap

SITE_ROUTER = "aa:aa:aa:aa:aa:01"
ECHTER_ROUTER = "bb:bb:bb:bb:bb:02"


class TestLoadOffloaderByAp:
    def test_ohne_pfad(self):
        assert load_offloader_by_ap("") == {}

    def test_kein_text(self):
        # Ein falsch gesetzter Wert wirkt wie ein fehlender
        assert load_offloader_by_ap(Mock()) == {}
        assert load_offloader_by_ap(None) == {}

    def test_datei_fehlt(self, tmp_path):
        assert load_offloader_by_ap(str(tmp_path / "gibt-es-nicht.json")) == {}

    def test_kaputtes_json(self, tmp_path):
        p = tmp_path / "zuordnung.json"
        p.write_text("{ kein json")
        assert load_offloader_by_ap(str(p)) == {}

    def test_gueltig_und_klein(self, tmp_path):
        p = tmp_path / "zuordnung.json"
        p.write_text(json.dumps({"aps": {
            "0C:EA:14:65:42:03": {"router": "B0:19:21:8C:7F:C6", "name": "x"},
            "0c:ea:14:00:00:01": {"name": "ohne router"},
            "0c:ea:14:00:00:02": "kein objekt",
        }}))
        assert load_offloader_by_ap(str(p)) == {
            "0c:ea:14:65:42:03": "b0:19:21:8c:7f:c6"
        }


def _ap(name, mac):
    return {
        "name": name,
        "mac": mac,
        "state": 1,
        "type": "uap",
        "snmp_location": "51.2506, 6.9746",
        "model": "U6-Lite",
        "version": "6.6.77",
        "uptime": 3600,
        "sys_stats": {"loadavg_1": 0.1, "mem_used": 1, "mem_buffer": 1, "mem_total": 2},
        "vap_table": [{"essid": "Freifunk", "channel": 6, "rx_bytes": 1, "tx_bytes": 2}],
    }


@patch("unifi_respondd.unifi_client.config.load_config")
@patch("unifi_respondd.unifi_client.config.Config.from_dict")
@patch("unifi_respondd.unifi_client.scrape")
@patch("unifi_respondd.unifi_client.Controller")
@patch("unifi_respondd.unifi_client.get_client_count_for_ap")
@patch("unifi_respondd.unifi_client.get_ap_channel_usage")
@patch("unifi_respondd.unifi_client.parse_location")
def test_router_je_ap_vor_router_der_site(
    mock_loc, mock_chan, mock_clients, mock_controller,
    mock_scrape, mock_from_dict, mock_load, tmp_path,
):
    zuordnung = tmp_path / "zuordnung.json"
    zuordnung.write_text(json.dumps({"aps": {
        "0c:ea:14:00:00:0a": {"router": ECHTER_ROUTER},
    }}))

    cfg = Mock()
    cfg.nodelist = "http://example.invalid/meshviewer.json"
    cfg.ssid_regex = ".*freifunk.*"
    cfg.version = "v5"
    cfg.offloader_mac = {"fflvr": SITE_ROUTER}
    cfg.fallback_domain = "unifi_respondd_fallback"
    cfg.offloader_by_ap = str(zuordnung)
    mock_from_dict.return_value = cfg
    mock_load.return_value = {}

    mock_scrape.return_value = {"nodes": [
        {"mac": SITE_ROUTER, "gateway": "gw-site", "gateway6": "gw6-site", "domain": "11_lvr"},
        {"mac": ECHTER_ROUTER, "gateway": "gw-echt", "gateway6": "gw6-echt", "domain": "33_lvrmo"},
    ]}
    c = Mock()
    mock_controller.return_value = c
    c.get_sites.return_value = [{"name": "default", "desc": "fflvr"}]
    c.get_aps.return_value = [
        _ap("mit-messung", "0C:EA:14:00:00:0A"),   # Grossschreibung wie im Controller
        _ap("ohne-messung", "0c:ea:14:00:00:0b"),
    ]
    c.get_clients.return_value = []
    mock_clients.return_value = (0, 0, 0)
    mock_chan.return_value = (None, None, None, 6, 1, 2)
    mock_loc.return_value = (51.2506, 6.9746)

    aps = {a.name: a for a in get_infos().accesspoints}

    gemessen = aps["mit-messung"]
    assert gemessen.gateway_nexthop == ECHTER_ROUTER.replace(":", "")
    assert gemessen.neighbour_macs[0] == ECHTER_ROUTER
    assert gemessen.domain_code == "33_lvrmo"
    assert gemessen.gateway == "gw-echt"

    # Ohne Eintrag bleibt es beim Router der Site, wie ohne Zusatz
    ungemessen = aps["ohne-messung"]
    assert ungemessen.gateway_nexthop == SITE_ROUTER.replace(":", "")
    assert ungemessen.neighbour_macs[0] == SITE_ROUTER
    assert ungemessen.domain_code == "11_lvr"


def test_ap_meldet_ortscode_seines_routers():
    """Der AP meldet den Code seines Routers auch als site_code, sonst fiele
    er aus jeder Ortskarte heraus, die nach site_code filtert."""
    from unifi_respondd.respondd_client import ResponddClient
    from unifi_respondd.unifi_client import Accesspoint, Accesspoints

    ap = Accesspoint(
        name="lvr-ap", mac="0c:ea:14:00:00:0a", snmp_location="51.2506, 6.9746",
        client_count=1, client_count24=1, client_count5=0, channel5=None,
        rx_bytes5=None, tx_bytes5=None, channel24=6, rx_bytes24=1, tx_bytes24=2,
        latitude=51.2506, longitude=6.9746, model="U6-Lite", firmware="6.6.77",
        uptime=1, contact="", load_avg=0.1, mem_used=1, mem_total=2, mem_buffer=1,
        tx_bytes=2, rx_bytes=1, gateway="gw", gateway6="gw6",
        gateway_nexthop=ECHTER_ROUTER.replace(":", ""),
        neighbour_macs=[ECHTER_ROUTER], domain_code="lvrmo-33_lvrmo",
    )
    client = ResponddClient.__new__(ResponddClient)
    client._aps = Accesspoints(accesspoints=[ap])
    knoten = client.getNodeInfos()[0]
    assert knoten.system.site_code == "lvrmo-33_lvrmo"
    assert knoten.system.domain_code == "lvrmo-33_lvrmo"
    assert knoten.to_dict()["system"]["site_code"] == "lvrmo-33_lvrmo"


def _knoten(lat, lon):
    from unifi_respondd.respondd_client import ResponddClient
    from unifi_respondd.unifi_client import Accesspoint, Accesspoints
    ap = Accesspoint(
        name="ap", mac="0c:ea:14:00:00:0c", snmp_location="",
        client_count=0, client_count24=0, client_count5=0, channel5=None,
        rx_bytes5=None, tx_bytes5=None, channel24=6, rx_bytes24=1, tx_bytes24=2,
        latitude=lat, longitude=lon, model="U6-Lite", firmware="6.6.77",
        uptime=1, contact="", load_avg=0.1, mem_used=1, mem_total=2, mem_buffer=1,
        tx_bytes=2, rx_bytes=1, gateway="gw", gateway6="gw6",
        gateway_nexthop="bbbbbbbbbb02", neighbour_macs=[ECHTER_ROUTER],
        domain_code="lvrmo-33_lvrmo",
    )
    client = ResponddClient.__new__(ResponddClient)
    client._aps = Accesspoints(accesspoints=[ap])
    return client.getNodeInfos()[0].to_dict()


def test_ohne_koordinaten_kein_ort():
    """Ohne Koordinaten fehlt der Ort ganz, statt 0/0 (Null Island)."""
    assert "location" not in _knoten(None, None)


def test_mit_koordinaten_ort():
    assert _knoten(51.2506, 6.9746)["location"] == {"latitude": 51.2506, "longitude": 6.9746}


@patch("unifi_respondd.unifi_client.config.load_config")
@patch("unifi_respondd.unifi_client.config.Config.from_dict")
@patch("unifi_respondd.unifi_client.scrape")
@patch("unifi_respondd.unifi_client.Controller")
@patch("unifi_respondd.unifi_client.get_client_count_for_ap")
@patch("unifi_respondd.unifi_client.get_ap_channel_usage")
def test_leeres_und_nulleins_feld_ergibt_keinen_ort(
    mock_chan, mock_clients, mock_controller,
    mock_scrape, mock_from_dict, mock_load,
):
    cfg = Mock()
    cfg.nodelist = "http://example.invalid/meshviewer.json"
    cfg.ssid_regex = ".*freifunk.*"
    cfg.version = "v5"
    cfg.offloader_mac = {"fflvr": SITE_ROUTER}
    cfg.fallback_domain = "unifi_respondd_fallback"
    cfg.offloader_by_ap = ""
    mock_from_dict.return_value = cfg
    mock_load.return_value = {}
    mock_scrape.return_value = {"nodes": [{"mac": SITE_ROUTER, "domain": "11_lvr"}]}
    c = Mock()
    mock_controller.return_value = c
    c.get_sites.return_value = [{"name": "default", "desc": "fflvr"}]
    leer = _ap("leer", "0c:ea:14:00:00:0d")
    leer["snmp_location"] = ""
    null = _ap("null", "0c:ea:14:00:00:0e")
    null["snmp_location"] = "0, 0"
    gut = _ap("gut", "0c:ea:14:00:00:0f")
    c.get_aps.return_value = [leer, null, gut]
    c.get_clients.return_value = []
    mock_clients.return_value = (0, 0, 0)
    mock_chan.return_value = (None, None, None, 6, 1, 2)

    aps = {a.name: a for a in get_infos().accesspoints}
    assert aps["leer"].latitude is None and aps["leer"].longitude is None
    assert aps["null"].latitude is None and aps["null"].longitude is None
    assert (aps["gut"].latitude, aps["gut"].longitude) == (51.2506, 6.9746)
