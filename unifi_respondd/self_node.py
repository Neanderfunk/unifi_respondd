"""Lokaler Zusatz (Neanderfunk): der Rechner selbst als respondd-Knoten.

Ein Kartenserver haengt mit einem Tunnel in jedem Mesh, das er misst, und
steht dort als batman-Originator. Beantwortet er respondd nicht, ist er fuer
jede andere Karte ein "dunkler Knoten": im Mesh sichtbar, aber ohne Namen
und ohne Kontakt (adorfer 26.09.2026). Deshalb antwortet er je
Mesh-Interface als eigener Knoten, mit Namen, Kontakt und seinem Tunnel.

- node_id ist die MAC der batman-Instanz, wie bei Gluon die primaere MAC.
- Die Tunnel (lower_* der batman-Instanz) stehen als mesh.tunnel, damit
  Collector die Nachbarschaft zum Supernode dem Knoten zuordnen.
- Die batman-Nachbarn liest nur root. Ein root-Timer schreibt sie in eine
  Datei (neighbours_file); ist sie aelter als MAX_AGE, bleiben sie weg.
"""

import json
import os
import time

SYS_NET = "/sys/class/net"
PROC = "/proc"
MAX_AGE = 600


class Info:
    """Wie die Dataclasses der APs: node_id und to_dict()."""

    def __init__(self, node_id, data):
        self.node_id = node_id
        self.data = data

    def to_dict(self):
        return self.data


def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def mesh_macs(ifname, sys_net=SYS_NET):
    """MACs der Interfaces unter der batman-Instanz (lower_*), sortiert."""
    try:
        eintraege = os.listdir(os.path.join(sys_net, ifname))
    except OSError:
        return []
    macs = []
    for e in sorted(eintraege):
        if e.startswith("lower_"):
            mac = _read(os.path.join(sys_net, e[len("lower_"):], "address"))
            if mac:
                macs.append(mac)
    return macs


def meminfo(proc=PROC):
    werte = {}
    for zeile in (_read(os.path.join(proc, "meminfo")) or "").splitlines():
        name, _, rest = zeile.partition(":")
        teile = rest.split()
        if teile and teile[0].isdigit():
            werte[name] = int(teile[0])
    return {
        "total": werte.get("MemTotal", 0),
        "free": werte.get("MemFree", 0),
        "available": werte.get("MemAvailable", 0),
        "buffers": werte.get("Buffers", 0),
        "cached": werte.get("Cached", 0),
    }


def _first_float(path):
    try:
        return float((_read(path) or "").split()[0])
    except (IndexError, ValueError):
        return None


def neighbours_of(path, ifname, now=None):
    """{Tunnel-MAC: {Nachbar-MAC: {tq, lastseen}}} aus der Datei des Timers."""
    if not path:
        return {}
    try:
        with open(path) as f:
            daten = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(daten, dict):
        return {}
    zeit = daten.get("time", 0)
    if not isinstance(zeit, (int, float)) or (now or time.time()) - zeit > MAX_AGE:
        return {}
    werte = daten.get("interfaces", {}).get(ifname, {})
    return werte if isinstance(werte, dict) else {}


def build(cfg, ifname, site_codes, sys_net=SYS_NET, proc=PROC, now=None):
    """Antworten fuer nodeinfo, statistics, neighbours; {} ohne Konfiguration."""
    if not isinstance(cfg, dict) or not cfg:
        return {}
    bat_mac = _read(os.path.join(sys_net, ifname, "address"))
    if not bat_mac:
        return {}
    node_id = bat_mac.replace(":", "")
    code = ifname[len("bat-"):] if ifname.startswith("bat-") else ifname
    site_code = (list(site_codes or []) or [code])[0]
    tunnel = mesh_macs(ifname, sys_net)

    nodeinfo = {
        "node_id": node_id,
        "hostname": cfg.get("hostname_prefix", "") + code,
        "network": {
            "mac": bat_mac,
            "mesh": {"bat0": {"interfaces": {"tunnel": tunnel}}},
        },
        "system": {"site_code": site_code, "domain_code": code},
        "hardware": {"model": cfg.get("model", ""), "nproc": os.cpu_count() or 1},
        "software": {
            "firmware": {
                "base": cfg.get("firmware_base", ""),
                "release": cfg.get("firmware_release", ""),
            }
        },
        "vpn": False,
    }
    if cfg.get("contact"):
        nodeinfo["owner"] = {"contact": cfg["contact"]}

    statistics = {
        "node_id": node_id,
        "memory": meminfo(proc),
        "clients": {"total": 0, "wifi": 0, "wifi24": 0, "wifi5": 0},
    }
    uptime = _first_float(os.path.join(proc, "uptime"))
    if uptime is not None:
        statistics["uptime"] = uptime
    load = _first_float(os.path.join(proc, "loadavg"))
    if load is not None:
        statistics["loadavg"] = load

    nb = neighbours_of(cfg.get("neighbours_file"), ifname, now)
    neighbours = {
        "node_id": node_id,
        "batadv": {mac: {"neighbours": nb.get(mac, {})} for mac in tunnel},
    }
    return {
        "nodeinfo": Info(node_id, nodeinfo),
        "statistics": Info(node_id, statistics),
        "neighbours": Info(node_id, neighbours),
    }
