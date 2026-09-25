#!/usr/bin/env python3
"""Tests fuer den lokalen Zusatz "interfaces" (Neanderfunk).

Auf mehreren Schnittstellen lauschen und je Schnittstelle nur die APs melden,
deren Router in deren Domain steht. Controllerdaten zwischengespeichert.
"""

import json
import socket
import struct
import zlib
from unittest.mock import Mock, patch

from unifi_respondd.respondd_client import ResponddClient
from unifi_respondd.unifi_client import Accesspoint, Accesspoints


def _ap(mac, code):
    return Accesspoint(
        name="ap-" + mac[-2:], mac=mac, snmp_location="",
        client_count=0, client_count24=0, client_count5=0, channel5=None,
        rx_bytes5=None, tx_bytes5=None, channel24=6, rx_bytes24=1, tx_bytes24=2,
        latitude=None, longitude=None, model="U6-Lite", firmware="6.6.77",
        uptime=1, contact="", load_avg=0.1, mem_used=1, mem_total=2, mem_buffer=1,
        tx_bytes=2, rx_bytes=1, gateway="gw", gateway6="gw6",
        gateway_nexthop="aabbccddeeff", neighbour_macs=["aa:bb:cc:dd:ee:ff"],
        domain_code=code,
    )


def _client(aps, **cfg):
    c = ResponddClient.__new__(ResponddClient)
    c._config = Mock(**cfg)
    c._aps = Accesspoints(accesspoints=aps)
    c._aps_zeit = 0.0
    c._sock = Mock()
    return c


APS = [
    _ap("0c:ea:14:00:00:01", "lvrmo-33_lvrmo"),
    _ap("0c:ea:14:00:00:02", "lvrmo-33_lvrmo"),
    _ap("0c:ea:14:00:00:03", "lvrno-31_lvrno"),
]


def test_ids_nur_aus_der_eigenen_domain():
    c = _client(APS)
    assert c.ids_fuer(["lvrmo-33_lvrmo", "33_lvrmo"]) == {"0cea14000001", "0cea14000002"}
    assert c.ids_fuer(["lvrno-31_lvrno"]) == {"0cea14000003"}
    assert c.ids_fuer(["nef-05_mon"]) == set()
    assert c.ids_fuer([]) == set()


def test_sendstruct_schickt_nur_die_erlaubten():
    c = _client(APS)
    struktur = {"nodeinfo": c.getNodeInfos()}
    c.sendStruct(("fe80::1", 40000, 0, 5), struktur, True, {"0cea14000003"})
    assert c._sock.sendto.call_count == 1
    daten, ziel = c._sock.sendto.call_args[0]
    knoten = json.loads(zlib.decompress(daten, -15))
    assert knoten["nodeinfo"]["node_id"] == "0cea14000003"
    assert ziel == ("fe80::1", 40000, 0, 5)


def test_sendstruct_ohne_filter_wie_bisher():
    c = _client(APS)
    c.sendStruct(("fe80::1", 40000, 0, 5), {"nodeinfo": c.getNodeInfos()}, True)
    assert c._sock.sendto.call_count == 3


def test_schnittstelle_aus_pktinfo():
    lo = socket.if_indextoname(1)
    daten = socket.inet_pton(socket.AF_INET6, "::1") + struct.pack("I", 1)
    assert ResponddClient.schnittstelle_aus(
        [(socket.IPPROTO_IPV6, socket.IPV6_PKTINFO, daten)]) == lo
    assert ResponddClient.schnittstelle_aus([]) is None


def test_echter_socket_erkennt_ankunftsschnittstelle():
    """Ueber Loopback: recvmsg mit IPV6_RECVPKTINFO nennt die Schnittstelle."""
    c = ResponddClient.__new__(ResponddClient)
    c._sock = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
    c._sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_RECVPKTINFO, 1)
    c._sock.bind(("::1", 0))
    c._sock.settimeout(3)
    port = c._sock.getsockname()[1]
    s = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
    s.sendto(b"GET nodeinfo statistics", ("::1", port))
    teile, quelle, ifname = c.listenMulti()
    assert teile == ["GET", "nodeinfo", "statistics"]
    assert ifname == socket.if_indextoname(1)
    assert quelle[0] == "::1"
    c._sock.close()
    s.close()


def test_controller_hoechstens_einmal_je_zeitfenster():
    c = _client(APS, cache_seconds=60)
    c._aps = None
    with patch("unifi_respondd.respondd_client.unifi_client.get_infos",
               return_value=Accesspoints(accesspoints=APS)) as holen, \
         patch("unifi_respondd.respondd_client.time.time") as uhr:
        uhr.return_value = 1000.0
        c.frische_aps()
        uhr.return_value = 1030.0
        c.frische_aps()
        assert holen.call_count == 1
        uhr.return_value = 1061.0
        c.frische_aps()
        assert holen.call_count == 2


def test_controller_fehler_behaelt_alte_daten():
    c = _client(APS, cache_seconds=60)
    with patch("unifi_respondd.respondd_client.unifi_client.get_infos",
               return_value=None), \
         patch("unifi_respondd.respondd_client.time.time", return_value=9999.0):
        assert c.frische_aps().accesspoints == APS


def test_port_wird_geteilt():
    """Zwei Dienste auf demselben Port bekommen beide die Multicast-Anfragen;
    dafuer muessen beide SO_REUSEADDR setzen (mesh-announce tut es)."""
    andere = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
    andere.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    andere.bind(("::", 0))
    port = andere.getsockname()[1]
    c = ResponddClient.__new__(ResponddClient)
    c._config = Mock(interfaces={}, multicast_port=port, multicast_address="ff02::1")
    c._sock = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
    with patch.object(ResponddClient, "listenMulti", side_effect=StopIteration):
        try:
            c.startMulti()
        except StopIteration:
            pass
    assert c._sock.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR) == 1
    assert c._sock.getsockname()[1] == port
    c._sock.close()
    andere.close()


def test_sendefehler_beendet_nicht_den_dienst():
    """sendto scheitert (volle Nachbartabelle: EINVAL); die uebrigen Knoten
    gehen trotzdem raus, und es gibt keine Ausnahme."""
    c = _client(APS)
    c._sock.sendto.side_effect = [OSError(22, "Invalid argument"), None, None]
    c.sendStruct(("fe80::1", 40000, 0, 5), {"nodeinfo": c.getNodeInfos()}, True)
    assert c._sock.sendto.call_count == 3
