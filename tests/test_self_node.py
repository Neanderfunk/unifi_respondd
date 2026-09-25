#!/usr/bin/env python3
"""Tests fuer den Rechner selbst als respondd-Knoten (Neanderfunk)."""

import json
import os

from unifi_respondd import self_node
from unifi_respondd.config import Config

CFG = {
    "hostname_prefix": "map-neanderfunk-",
    "contact": "projekt@neanderfunk.de",
    "model": "Kartenserver (VM)",
    "firmware_base": "Debian",
    "firmware_release": "13",
}


def _welt(tmp_path, zeit=1000.0, nachbarn=None):
    net = tmp_path / "net"
    (net / "bat-ffe").mkdir(parents=True)
    (net / "bat-ffe" / "address").write_text("02:45:4e:00:01:81\n")
    (net / "bat-ffe" / "lower_td-ffe").mkdir()
    (net / "td-ffe").mkdir()
    (net / "td-ffe" / "address").write_text("02:45:4e:00:00:81\n")
    proc = tmp_path / "proc"
    proc.mkdir()
    (proc / "meminfo").write_text("MemTotal: 2471936 kB\nMemFree: 600000 kB\n"
                                  "MemAvailable: 1200000 kB\nBuffers: 1000 kB\nCached: 500000 kB\n")
    (proc / "uptime").write_text("12345.67 999.0\n")
    (proc / "loadavg").write_text("0.42 0.30 0.20 1/300 4242\n")
    datei = tmp_path / "neighbours.json"
    datei.write_text(json.dumps({"time": zeit, "interfaces": nachbarn or {}}))
    return str(net), str(proc), str(datei)


def test_ohne_konfiguration_aus(tmp_path):
    net, proc, _ = _welt(tmp_path)
    assert self_node.build({}, "bat-ffe", ["ffe"], net, proc) == {}
    assert self_node.build(None, "bat-ffe", ["ffe"], net, proc) == {}


def test_unbekanntes_interface(tmp_path):
    net, proc, _ = _welt(tmp_path)
    assert self_node.build(CFG, "bat-gibtsnicht", [], net, proc) == {}


def test_knoten_mit_namen_kontakt_und_tunnel(tmp_path):
    net, proc, datei = _welt(tmp_path, nachbarn={
        "bat-ffe": {"02:45:4e:00:00:81": {"92:d1:5c:a4:e5:e9": {"tq": 251, "lastseen": 0.5}}},
    })
    cfg = dict(CFG, neighbours_file=datei)
    a = self_node.build(cfg, "bat-ffe", ["ffe"], net, proc, now=1030.0)
    ni = a["nodeinfo"].to_dict()
    assert ni["node_id"] == "02454e000181"
    assert ni["hostname"] == "map-neanderfunk-ffe"
    assert ni["owner"] == {"contact": "projekt@neanderfunk.de"}
    assert ni["network"]["mac"] == "02:45:4e:00:01:81"
    assert ni["network"]["mesh"]["bat0"]["interfaces"]["tunnel"] == ["02:45:4e:00:00:81"]
    assert ni["system"] == {"site_code": "ffe", "domain_code": "ffe"}
    assert ni["vpn"] is False
    assert "location" not in ni
    st = a["statistics"].to_dict()
    assert st["uptime"] == 12345.67 and st["loadavg"] == 0.42
    assert st["memory"]["total"] == 2471936 and st["clients"]["total"] == 0
    nb = a["neighbours"].to_dict()["batadv"]
    assert nb == {"02:45:4e:00:00:81": {"neighbours": {"92:d1:5c:a4:e5:e9": {"tq": 251, "lastseen": 0.5}}}}
    assert {a[k].node_id for k in a} == {"02454e000181"}


def test_site_code_aus_der_liste(tmp_path):
    net, proc, _ = _welt(tmp_path)
    os.rename(os.path.join(net, "bat-ffe"), os.path.join(net, "bat-11_lvr"))
    a = self_node.build(CFG, "bat-11_lvr", ["nef-11_lvr", "nef-11_lvr_EOL", "11_lvr"], net, proc)
    assert a["nodeinfo"].to_dict()["system"] == {"site_code": "nef-11_lvr", "domain_code": "11_lvr"}
    assert a["nodeinfo"].to_dict()["hostname"] == "map-neanderfunk-11_lvr"


def test_alte_nachbardatei_wird_ignoriert(tmp_path):
    net, proc, datei = _welt(tmp_path, zeit=1000.0, nachbarn={
        "bat-ffe": {"02:45:4e:00:00:81": {"92:d1:5c:a4:e5:e9": {"tq": 251, "lastseen": 0.5}}},
    })
    cfg = dict(CFG, neighbours_file=datei)
    a = self_node.build(cfg, "bat-ffe", ["ffe"], net, proc, now=1000.0 + self_node.MAX_AGE + 1)
    assert a["neighbours"].to_dict()["batadv"] == {"02:45:4e:00:00:81": {"neighbours": {}}}


def test_kaputte_nachbardatei(tmp_path):
    net, proc, datei = _welt(tmp_path)
    open(datei, "w").write("{ kein json")
    a = self_node.build(dict(CFG, neighbours_file=datei), "bat-ffe", ["ffe"], net, proc)
    assert a["neighbours"].to_dict()["batadv"] == {"02:45:4e:00:00:81": {"neighbours": {}}}


def test_ohne_kontakt_kein_owner(tmp_path):
    net, proc, _ = _welt(tmp_path)
    cfg = dict(CFG)
    del cfg["contact"]
    assert "owner" not in self_node.build(cfg, "bat-ffe", ["ffe"], net, proc)["nodeinfo"].to_dict()


def test_konfiguration_liest_self_node():
    grund = {
        "controller_url": "c", "controller_port": 443, "username": "u", "password": "p",
        "ssid_regex": ".*", "offloader_mac": {}, "nodelist": "n", "version": "v5",
        "ssl_verify": True, "multicast_enabled": True, "multicast_address": "ff02::1",
        "multicast_port": 1001, "unicast_address": "::1", "unicast_port": 10001,
        "interface": "lo", "verbose": False,
    }
    assert Config.from_dict(grund).self_node == {}
    assert Config.from_dict(dict(grund, self_node=CFG)).self_node == CFG


def _client(tmp_path, aps_da=True):
    import zlib
    from unittest.mock import Mock, patch
    from unifi_respondd.respondd_client import ResponddClient
    from unifi_respondd.unifi_client import Accesspoints
    net, proc, _ = _welt(tmp_path)
    c = ResponddClient.__new__(ResponddClient)
    c._config = Mock(interfaces={"bat-ffe": ["ffe"]}, self_node=CFG, cache_seconds=60)
    c._aps = Accesspoints(accesspoints=[]) if aps_da else None
    c._aps_zeit = 1e12 if aps_da else 0.0
    c._sock = Mock()
    echt = self_node.build

    def gebaut(cfg, ifname, codes):
        return echt(cfg, ifname, codes, net, proc)

    return c, patch("unifi_respondd.respondd_client.self_node.build", side_effect=gebaut), zlib


def test_antwortet_als_knoten_ohne_aps(tmp_path):
    c, p, zlib = _client(tmp_path, aps_da=True)
    with p:
        c.beantworte(["GET", "nodeinfo", "statistics", "neighbours"], ("fe80::1", 4000, 0, 7), "bat-ffe")
    assert c._sock.sendto.call_count == 1
    daten, ziel = c._sock.sendto.call_args[0]
    knoten = json.loads(zlib.decompress(daten, -15))
    assert knoten["nodeinfo"]["hostname"] == "map-neanderfunk-ffe"
    assert set(knoten) == {"nodeinfo", "statistics", "neighbours"}
    assert ziel == ("fe80::1", 4000, 0, 7)


def test_antwortet_auch_wenn_der_controller_fehlt(tmp_path):
    from unittest.mock import patch
    c, p, zlib = _client(tmp_path, aps_da=False)
    with p, patch("unifi_respondd.respondd_client.unifi_client.get_infos", return_value=None):
        c.beantworte(["GET", "nodeinfo"], ("fe80::1", 4000, 0, 7), "bat-ffe")
    assert c._sock.sendto.call_count == 1
    knoten = json.loads(zlib.decompress(c._sock.sendto.call_args[0][0], -15))
    assert knoten["nodeinfo"]["node_id"] == "02454e000181"
