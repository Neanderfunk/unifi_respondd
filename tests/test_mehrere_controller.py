#!/usr/bin/env python3
"""Lokaler Zusatz (Neanderfunk): mehrere Controller (controllers)."""

from unittest.mock import Mock, patch

from unifi_respondd.unifi_client import get_infos, zugaenge

ROUTER_A = "b0:19:21:8c:7f:c6"
ROUTER_B = "80:af:ca:82:13:67"


def _cfg(controllers):
    cfg = Mock()
    cfg.controller_url = "unifi.example.invalid"
    cfg.controller_port = 8443
    cfg.username = "leser"
    cfg.password = "geheim"
    cfg.version = "v5"
    cfg.ssl_verify = True
    cfg.offloader_mac = {"Default": ROUTER_A}
    cfg.controllers = controllers
    cfg.nodelist = "http://example.invalid/meshviewer.json"
    cfg.ssid_regex = ".*freifunk.*"
    cfg.fallback_domain = "unifi_respondd_fallback"
    cfg.offloader_by_ap = ""
    cfg.location_bbox = []
    return cfg


def _ap(name, mac):
    return {
        "name": name,
        "mac": mac,
        "state": 1,
        "type": "uap",
        "model": "U6-Lite",
        "version": "6.6.77",
        "uptime": 3600,
        "sys_stats": {"loadavg_1": 0.1, "mem_used": 1, "mem_buffer": 1, "mem_total": 2},
        "vap_table": [{"essid": "Freifunk", "channel": 6, "rx_bytes": 1, "tx_bytes": 2}],
    }


class TestZugaenge:
    def test_ohne_liste_nur_der_eine(self):
        z = zugaenge(_cfg([]))
        assert [x.controller_url for x in z] == ["unifi.example.invalid"]
        assert z[0].offloader_mac == {"Default": ROUTER_A}

    def test_keine_liste_wirkt_wie_leer(self):
        assert len(zugaenge(_cfg(Mock()))) == 1

    def test_fehlendes_vom_ersten(self):
        z = zugaenge(_cfg([{
            "name": "zweiter", "controller_url": "10.0.0.2",
            "username": "u", "password": "p", "version": "UDMP-unifiOS",
            "offloader_mac": {"Default": ROUTER_B},
        }]))
        assert len(z) == 2
        assert z[1].name == "zweiter"
        assert z[1].controller_port == 8443
        assert z[1].ssl_verify is True
        assert z[1].version == "UDMP-unifiOS"
        # Router je Site gelten nur fuer ihren Controller
        assert z[1].offloader_mac == {"Default": ROUTER_B}

    def test_ohne_router_leer_nicht_vom_ersten(self):
        z = zugaenge(_cfg([{"controller_url": "10.0.0.2", "username": "u", "password": "p"}]))
        assert z[1].offloader_mac == {}
        assert z[1].name == "10.0.0.2"

    @patch("unifi_respondd.unifi_client.logger.error")
    def test_unvollstaendig_wird_uebersprungen(self, mock_log):
        z = zugaenge(_cfg([{"controller_url": "10.0.0.2"}, "kaputt"]))
        assert len(z) == 1
        assert mock_log.call_count == 2


def _controller_fabrik(je_host):
    """Controller-Ersatz: je Host eine Liste von APs oder eine Ausnahme."""
    def fabrik(host, **_):
        wert = je_host[host]
        if isinstance(wert, Exception):
            raise wert
        c = Mock()
        c.get_sites.return_value = [{"name": "default", "desc": "Default"}]
        c.get_aps.return_value = wert
        c.get_clients.return_value = []
        return c
    return fabrik


ZWEITER = [{
    "name": "WIR-Haus", "controller_url": "10.0.0.2",
    "username": "u", "password": "p", "version": "UDMP-unifiOS",
    "offloader_mac": {"Default": ROUTER_B},
}]
NODES = {"nodes": [
    {"mac": ROUTER_A, "gateway": "gw-a", "gateway6": "gw6-a", "domain": "11_lvr"},
    {"mac": ROUTER_B, "gateway": "gw-b", "gateway6": "gw6-b", "domain": "10_wlf"},
]}


@patch("unifi_respondd.unifi_client.config.load_config", return_value={})
@patch("unifi_respondd.unifi_client.config.Config.from_dict")
@patch("unifi_respondd.unifi_client.scrape", return_value=NODES)
@patch("unifi_respondd.unifi_client.Controller")
def test_aps_beider_controller_mit_eigenem_router(mock_controller, _scrape, mock_from_dict, _load):
    mock_from_dict.return_value = _cfg(ZWEITER)
    mock_controller.side_effect = _controller_fabrik({
        "unifi.example.invalid": [_ap("ap-a", "0c:ea:14:00:00:0a")],
        "10.0.0.2": [_ap("ap-b", "0c:ea:14:00:00:0b")],
    })
    aps = {a.name: a for a in get_infos().accesspoints}
    assert aps["ap-a"].domain_code == "11_lvr"
    assert aps["ap-b"].domain_code == "10_wlf"
    assert aps["ap-b"].gateway_nexthop == ROUTER_B.replace(":", "")
    assert aps["ap-b"].neighbour_macs[0] == ROUTER_B


@patch("unifi_respondd.unifi_client.config.load_config", return_value={})
@patch("unifi_respondd.unifi_client.config.Config.from_dict")
@patch("unifi_respondd.unifi_client.scrape", return_value=NODES)
@patch("unifi_respondd.unifi_client.Controller")
@patch("unifi_respondd.unifi_client.logger.error")
def test_ein_controller_faellt_aus(mock_log, mock_controller, _scrape, mock_from_dict, _load):
    mock_from_dict.return_value = _cfg(ZWEITER)
    mock_controller.side_effect = _controller_fabrik({
        "unifi.example.invalid": [_ap("ap-a", "0c:ea:14:00:00:0a")],
        "10.0.0.2": Exception("Tunnel weg"),
    })
    aps = get_infos()
    assert [a.name for a in aps.accesspoints] == ["ap-a"]
    assert "WIR-Haus" in mock_log.call_args[0][0]


@patch("unifi_respondd.unifi_client.config.load_config", return_value={})
@patch("unifi_respondd.unifi_client.config.Config.from_dict")
@patch("unifi_respondd.unifi_client.scrape", return_value=NODES)
@patch("unifi_respondd.unifi_client.Controller")
@patch("unifi_respondd.unifi_client.logger.error")
def test_keiner_erreichbar_none(_log, mock_controller, _scrape, mock_from_dict, _load):
    mock_from_dict.return_value = _cfg(ZWEITER)
    mock_controller.side_effect = Exception("aus")
    assert get_infos() is None


@patch("unifi_respondd.unifi_client.config.load_config", return_value={})
@patch("unifi_respondd.unifi_client.config.Config.from_dict")
@patch("unifi_respondd.unifi_client.scrape", return_value=NODES)
@patch("unifi_respondd.unifi_client.Controller")
@patch("unifi_respondd.unifi_client.logger.error")
def test_sites_scheitern(_log, mock_controller, _scrape, mock_from_dict, _load):
    mock_from_dict.return_value = _cfg([])
    c = Mock()
    c.get_sites.side_effect = Exception("401")
    mock_controller.return_value = c
    assert get_infos() is None
