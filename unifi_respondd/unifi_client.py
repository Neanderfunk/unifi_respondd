#!/usr/bin/env python3

import dataclasses
import json
import re
from typing import Dict, List, Tuple
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
    # Lokaler Zusatz (Neanderfunk): je Band ("ng", "na") Kanal und
    # Kanalauslastung in Prozent (gesamt, eigener Empfang, eigenes Senden)
    airtime: Dict[str, Tuple[int, float, float, float]] = dataclasses.field(
        default_factory=dict
    )


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


def get_ap_airtime(ap):
    """Lokaler Zusatz (Neanderfunk): Kanalauslastung je Band aus dem Controller.

    radio_table_stats nennt je Funkmodul cu_total (Kanal belegt, samt
    fremder Netze), cu_self_rx und cu_self_tx in Prozent. 6 GHz ("6e") bleibt
    vorerst draussen: yanic kennt nur 11g und 11a, ein drittes Band
    ueberschriebe die 5-GHz-Werte.
    """
    ergebnis = {}
    for radio in ap.get("radio_table_stats") or []:
        band = radio.get("radio")
        if band not in ("ng", "na"):
            continue
        try:
            ergebnis[band] = (
                int(radio["channel"]),
                float(radio["cu_total"]),
                float(radio.get("cu_self_rx") or 0),
                float(radio.get("cu_self_tx") or 0),
            )
        except (KeyError, TypeError, ValueError):
            continue
    return ergebnis


# Lokaler Zusatz (Neanderfunk): Koordinaten nur aus dem Feld selbst, keine
# Adresssuche bei Nominatim. Die schickte jeden unlesbaren Text an einen
# fremden Dienst und nahm, was zurueckkam, auch einen Ort am anderen Ende der
# Welt. Getippt wird das Feld von Hand, deshalb werden die ueblichen
# Schreibweisen vorher gesaeubert: Dezimalpunkt oder -komma, getrennt durch
# Komma, Semikolon oder Leerzeichen. Nachkommastellen sind Pflicht, sonst
# waere "51,6" nicht eindeutig. Vorn und hinten faellt alles weg, was weder
# Ziffer noch Buchstabe ist (Leerzeichen, "&" und "?" aus kopierten URLs,
# Klammern, Anfuehrungszeichen). Buchstaben bleiben stehen und werden als
# Himmelsrichtung gelesen, siehe _mit_richtung().
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


# Himmelsrichtungen, vor oder hinter der Zahl, dazu Grad/Minuten/Sekunden,
# wie Google Maps sie anzeigt (51°17'14.8"N 6°21'13.7"E). N/S legt die
# Breite fest, E/O/W die Laenge, S und W machen sie negativ. Gelesen wird
# nur, was eindeutig ist: kein Minuszeichen zusaetzlich zur Richtung, keine zwei
# Breiten, Minuten und Sekunden unter 60.
_R = r"([NSEOW])"
_WERT = (
    r"(?:(\d+)\s*[°º˚]\s*"
    r"(?:(\d+(?:[.,]\d+)?)\s*['′’´]\s*"
    r"(?:(\d+(?:[.,]\d+)?)\s*(?:[\"″”]|'')?)?)?"
    r"|(-?\d+(?:[.,]\d+)?)\s*[°º˚]?)"
)
_TRENNER = r"(?:\s*[,;]\s*|\s+)"
_RICHTUNG = [
    re.compile(r"^" + _R + r"\s*" + _WERT + _TRENNER + _R + r"?\s*" + _WERT + r"$", re.I),
    re.compile(r"^" + _R + r"?\s*" + _WERT + _TRENNER + _R + r"\s*" + _WERT + r"$", re.I),
    re.compile(r"^" + _WERT + r"\s*" + _R + r"?" + _TRENNER + _WERT + r"\s*" + _R + r"?$", re.I),
]


def _zahl(z):
    return float(z.replace(",", "."))


def _teil(richtung, grad, minuten, sekunden, dezimal):
    """Ein Wert mit Himmelsrichtung als (Achse, Zahl), Achse None/lat/lon."""
    if dezimal is not None:
        wert = _zahl(dezimal)
        # Ganze Zahlen nur mit Richtung, sonst waere "51,6" nicht eindeutig
        if not re.search(r"[.,]", dezimal) and not richtung:
            return None
    else:
        m = _zahl(minuten) if minuten else 0.0
        sek = _zahl(sekunden) if sekunden else 0.0
        if m >= 60 or sek >= 60:
            return None
        wert = int(grad) + m / 60 + sek / 3600
    if not richtung:
        return None, wert
    # Minus und Richtung zugleich widersprechen sich oder sind doppelt
    if wert < 0:
        return None
    richtung = richtung.upper()
    if richtung in "SW":
        wert = -wert
    return ("lat" if richtung in "NS" else "lon"), wert


def _mit_richtung(text):
    for muster in _RICHTUNG:
        m = muster.match(text)
        if not m:
            continue
        g = m.groups()
        if muster is _RICHTUNG[2]:
            a, b = _teil(g[4], *g[0:4]), _teil(g[9], *g[5:9])
        else:
            a, b = _teil(g[0], *g[1:5]), _teil(g[5], *g[6:10])
        if a is None or b is None:
            return None
        if a[0] and a[0] == b[0]:
            return None
        if a[0] == "lon" or b[0] == "lat":
            a, b = b, a
        return _pruefen(a[1], b[1])
    return None


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
        return _mit_richtung(text)
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
                            airtime=get_ap_airtime(ap),
                        )
                    )
    return aps


def main():
    """This function is the main function, it's only executed if we aren't imported."""
    print(get_infos())


if __name__ == "__main__":
    main()
