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
@patch("unifi_respondd.unifi_client.Nominatim")
@patch("unifi_respondd.unifi_client.get_client_count_for_ap")
@patch("unifi_respondd.unifi_client.get_ap_channel_usage")
@patch("unifi_respondd.unifi_client.get_location_by_address")
def test_router_je_ap_vor_router_der_site(
    mock_loc, mock_chan, mock_clients, mock_nominatim, mock_controller,
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

