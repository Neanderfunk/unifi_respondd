#!/usr/bin/env python3

import dataclasses
import json
import re
from typing import List
from urllib.parse import unquote

from pyunifi.controller import Controller
from requests import get as rget

from unifi_respondd import config, logger

ffnodes = None


@dataclasses.dataclass
class Accesspoint:
    """This class contains the information of an AP.
    Attributes:
        name: The name of the AP (alias in the unifi controller).
        mac: The MAC address of the AP.
        snmp_location: The location of the AP (SNMP location in the unifi controller).
        client_count: The number of clients connected to the AP.
        client_count24: The number of clients connected to the AP via 2,4 GHz.
        client_count5: The number of clients connected to the AP via 5 GHz.
        latitude: The latitude of the AP.
        longitude: The longitude of the AP.
        model: The hardware model of the AP.
        firmware: The firmware information of the AP.
        uptime: The uptime of the AP.
        contact: The contact of the AP for example an email address.
        load_avg: The load average of the AP.
        mem_used: The used memory of the AP.
        mem_total: The total memory of the AP.
        mem_buffer: The buffer memory of the AP.
        tx_bytes: The transmitted bytes of the AP.
        rx_bytes: The received bytes of the AP."""

    name: str
    mac: str
    snmp_location: str
    client_count: int
    client_count24: int
    client_count5: int
    channel5: int
    rx_bytes5: bytes
    tx_bytes5: bytes
    channel24: int
    rx_bytes24: bytes
    tx_bytes24: bytes
    latitude: float
    longitude: float
    model: str
    firmware: str
    uptime: int
    contact: str
    load_avg: float
    mem_used: int
    mem_total: int
    mem_buffer: int
    tx_bytes: int
    rx_bytes: int
    gateway: str
    gateway6: str
    gateway_nexthop: str
    neighbour_macs: List[str]
    domain_code: str


@dataclasses.dataclass
class Accesspoints:
    """This class contains the information of all APs.
    Attributes:
        accesspoints: A list of Accesspoint objects."""

    accesspoints: List[Accesspoint]


def get_client_count_for_ap(ap_mac, clients, cfg):
    """This function returns the number total clients, 2,4Ghz clients and 5Ghz clients connected to an AP."""
    client5_count = 0
    client24_count = 0
    for client in clients:
        if re.search(cfg.ssid_regex, client.get("essid", ""), re.IGNORECASE):
            if client.get("ap_mac", "No mac") == ap_mac:
                if client.get("channel", 0) > 14:
                    client5_count += 1
                else:
                    client24_count += 1
    return client24_count + client5_count, client24_count, client5_count


def get_ap_channel_usage(ssids, cfg):
    """This function returns the channels used for the Freifunk SSIDs"""
    channel5 = None
    rx_bytes5 = None
    tx_bytes5 = None
    channel24 = None
    rx_bytes24 = None
    tx_bytes24 = None
    for ssid in ssids:
        if re.search(cfg.ssid_regex, ssid.get("essid", ""), re.IGNORECASE):
            channel = ssid.get("channel", 0)
            rx_bytes = ssid.get("rx_bytes", 0)
            tx_bytes = ssid.get("tx_bytes", 0)
            if channel > 14:
                channel5 = channel
                rx_bytes5 = rx_bytes
                tx_bytes5 = tx_bytes
            else:
                channel24 = channel
                rx_bytes24 = rx_bytes
                tx_bytes24 = tx_bytes

    return channel5, rx_bytes5, tx_bytes5, channel24, rx_bytes24, tx_bytes24


# Lokaler Zusatz (Neanderfunk): Koordinaten nur aus dem Feld selbst, keine
# Adresssuche bei Nominatim. Die schickte jeden unlesbaren Text an einen
# fremden Dienst und nahm, was zurueckkam, auch einen Ort am anderen Ende der
# Welt. Getippt wird das Feld von Hand, deshalb werden die ueblichen
# Schreibweisen vorher gesaeubert: Dezimalpunkt oder -komma, getrennt durch
# Komma, Semikolon oder Leerzeichen. Nachkommastellen sind Pflicht, sonst
# waere "51,6" nicht eindeutig. Vorn und hinten faellt alles weg, was weder
# Ziffer noch Buchstabe ist (Leerzeichen, "&" und "?" aus kopierten URLs,
# Klammern, Anfuehrungszeichen). Buchstaben bleiben stehen: ein verworfenes
# "S" oder "W" drehte stillschweigend das Vorzeichen um, dann lieber
# unlesbar.
_ZAHL = r"(-?\d+[.,]\d+)"
_ORT = re.compile(r"^" + _ZAHL + r"(?:\s*[,;]\s*|\s+)" + _ZAHL + r"$")
_RAND_VORN = re.compile(r"^[^0-9A-Za-z-]+")
_RAND_HINTEN = re.compile(r"[^0-9A-Za-z]+$")
# Unsauber aus der Adresszeile von Google Maps kopiert: zuerst der gesetzte
# Pin (!3d...!4d...), dann ein Parameter (?q=, ll=, ...), zuletzt die
# Kartenmitte (/@Breite,Laenge,17z). Die Mitte ist ungenauer als der Pin,
# aber immer noch dort, wo jemand hingeschaut hat.
_PUNKT = r"(-?\d+\.\d+)"
_GOOGLE = [
    re.compile(r"!3d" + _PUNKT + r"!4d" + _PUNKT),
    re.compile(
        r"(?:^|[?&/])(?:q|query|ll|sll|center|destination|daddr)="
        + _PUNKT + r"(?:\s*[,;]\s*|\s+)" + _PUNKT
    ),
    re.compile(r"@" + _PUNKT + r"\s*,\s*" + _PUNKT),
]


def _pruefen(lat, lon):
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    # 0/0 ist kein Ort, sondern ein Eingabefehler
    if abs(lat) < 0.5 and abs(lon) < 0.5:
        return None
    return lat, lon


def parse_location(text):
    """Liest "Breite, Laenge" aus dem Feld SNMP Location, sonst None."""
    if not isinstance(text, str):
        return None
    # %2C, %20 und + aus URLs zu Komma und Leerzeichen
    text = unquote(text).replace("+", " ").replace("\u00a0", " ")
    for muster in _GOOGLE:
        m = muster.search(text)
        if m:
            return _pruefen(float(m.group(1)), float(m.group(2)))
    text = _RAND_HINTEN.sub("", _RAND_VORN.sub("", text))
    m = _ORT.match(text)
    if not m:
        return None
    lat, lon = (float(z.replace(",", ".")) for z in m.groups())
    return _pruefen(lat, lon)


def scrape(url):
    """returns remote json"""
    try:
        return rget(url).json()
    except Exception as ex:
        logger.error("Error: %s" % (ex))


def load_offloader_by_ap(path):
    """Lokaler Zusatz (Neanderfunk): Router je Accesspoint aus einer Datei.

    Die Datei erzeugt der Kartenserver aus der batman-Uebersetzungstabelle:
    {"aps": {"<ap-mac>": {"router": "<primaere mac des knotens>", ...}}}.
    Damit haengt jeder AP am Router, hinter dem er wirklich steht, und nicht
    am einen Router seiner Site. Fehlt die Datei oder ist sie kaputt, bleibt
    alles wie ohne Zusatz.
    """
    # Nur ein Pfad als Text zaehlt. Ein anders gesetzter Wert soll den Dienst
    # nicht umwerfen, sondern wirken wie ein fehlender.
    if not isinstance(path, str) or not path:
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            aps = json.load(f).get("aps") or {}
    except (OSError, ValueError) as ex:
        logger.error("offloader_by_ap %s: %s" % (path, ex))
        return {}
    return {
        ap.lower(): eintrag["router"].lower()
        for ap, eintrag in aps.items()
        if isinstance(eintrag, dict) and eintrag.get("router")
    }


def get_infos():
    """This function gathers all the information and returns a list of Accesspoint objects."""
    cfg = config.Config.from_dict(config.load_config())
    ffnodes = scrape(cfg.nodelist)
    try:
        c = Controller(
            host=cfg.controller_url,
            username=cfg.username,
            password=cfg.password,
            port=cfg.controller_port,
            version=cfg.version,
            ssl_verify=cfg.ssl_verify,
        )
    except Exception as ex:
        logger.error("Error: %s" % (ex))
        return
    offloader_by_ap = load_offloader_by_ap(cfg.offloader_by_ap)
    aps = Accesspoints(accesspoints=[])
    for site in c.get_sites():
        if cfg.version == "UDMP-unifiOS":
            c = Controller(
                host=cfg.controller_url,
                username=cfg.username,
                password=cfg.password,
                port=cfg.controller_port,
                version=cfg.version,
                site_id=site["name"],
                ssl_verify=cfg.ssl_verify,
            )
        else:
            try:
                c.switch_site(site["desc"])
            except Exception as ex:
                logger.error("Error: %s" % (ex))
                continue

        try:
            aps_for_site = c.get_aps()
            clients = c.get_clients()
        except Exception as ex:
            logger.error("Error: %s" % (ex))
            continue
        for ap in aps_for_site:
            if (
                ap.get("name", None) is not None
                and ap.get("state", 0) != 0
                and ap.get("type", "na") == "uap"
            ):
                ssids = ap.get("vap_table", None)
                containsSSID = False
                tx = 0
                rx = 0
                if ssids is not None:
                    for ssid in ssids:
                        if re.search(
                            cfg.ssid_regex, ssid.get("essid", ""), re.IGNORECASE
                        ):
                            containsSSID = True
                            tx = tx + ssid.get("tx_bytes", 0)
                            rx = rx + ssid.get("rx_bytes", 0)
                if containsSSID:
                    (
                        client_count,
                        client_count24,
                        client_count5,
                    ) = get_client_count_for_ap(ap.get("mac", None), clients, cfg)

                    (
                        channel5,
                        rx_bytes5,
                        tx_bytes5,
                        channel24,
                        rx_bytes24,
                        tx_bytes24,
                    ) = get_ap_channel_usage(ssids, cfg)

                    # Lokaler Zusatz (Neanderfunk): ohne Koordinaten kein Ort,
                    # statt 0/0. Ein AP ohne Ort steht dann in Liste und Graph
                    # an seinem Router, aber nicht auf der Karte. Mit 0/0 stand
                    # er auf "Null Island" im Golf von Guinea und zog den
                    # Kartenausschnitt bis nach Afrika auf.
                    lat, lon = None, None
                    neighbour_macs = []
                    ort = parse_location(ap.get("snmp_location"))
                    if ort:
                        lat, lon = ort
                    # Lokaler Zusatz (Neanderfunk): gemessener Router je AP vor
                    # dem Router der Site
                    offloader_mac = offloader_by_ap.get(
                        (ap.get("mac") or "").lower()
                    ) or cfg.offloader_mac.get(site["desc"], "")
                    try:
                        neighbour_macs.append(offloader_mac or None)
                        offloader_id = offloader_mac.replace(":", "")
                        offloader = list(
                            filter(
                                lambda x: x["mac"] == offloader_mac,
                                ffnodes["nodes"],
                            )
                        )[0]
                    except Exception:
                        offloader_id = None
                        offloader = {}
                        pass
                    uplink = ap.get("uplink", None)
                    if uplink is not None and uplink.get("ap_mac", None) is not None:
                        neighbour_macs.append(uplink.get("ap_mac"))
                    lldp_table = ap.get("lldp_table", None)
                    if lldp_table is not None:
                        for lldp_entry in lldp_table:
                            if not lldp_entry.get("is_wired", True):
                                neighbour_macs.append(lldp_entry.get("chassis_id"))
                    aps.accesspoints.append(
                        Accesspoint(
                            name=ap.get("name", None),
                            mac=ap.get("mac", None),
                            snmp_location=ap.get("snmp_location", None),
                            client_count=client_count,
                            client_count24=client_count24,
                            client_count5=client_count5,
                            channel5=channel5,
                            rx_bytes5=rx_bytes5,
                            tx_bytes5=tx_bytes5,
                            channel24=channel24,
                            rx_bytes24=rx_bytes24,
                            tx_bytes24=tx_bytes24,
                            latitude=lat,
                            longitude=lon,
                            model=ap.get("model", None),
                            firmware=ap.get("version", None),
                            uptime=ap.get("uptime", None),
                            contact=ap.get("snmp_contact", None),
                            load_avg=float(
                                ap.get("sys_stats", {}).get("loadavg_1", 0.0)
                            ),
                            mem_used=ap.get("sys_stats", {}).get("mem_used", 0),
                            mem_buffer=ap.get("sys_stats", {}).get("mem_buffer", 0),
                            mem_total=ap.get("sys_stats", {}).get("mem_total", 0),
                            tx_bytes=tx,
                            rx_bytes=rx,
                            gateway=offloader.get("gateway", None),
                            gateway6=offloader.get("gateway6", None),
                            gateway_nexthop=offloader_id,
                            neighbour_macs=neighbour_macs,
                            domain_code=offloader.get("domain", cfg.fallback_domain),
                        )
                    )
    return aps


def main():
    """This function is the main function, it's only executed if we aren't imported."""
    print(get_infos())


if __name__ == "__main__":
    main()
