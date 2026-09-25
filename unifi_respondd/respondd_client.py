#!/usr/bin/env python3

import dataclasses
import json
import socket
import struct
import time
import zlib
from typing import Dict, List

from dataclasses_json import config, dataclass_json

from unifi_respondd import logger, unifi_client


@dataclasses.dataclass
class FirmwareInfo:
    """This class contains the firmware information of an AP.
    Attributes:
        base: The base version of the firmware.
        release: The release version of the firmware."""

    base: str
    release: str


@dataclasses.dataclass
class LocationInfo:
    """This class contains the location information of an AP.
    Attributes:
        latitude: The latitude of the AP.
        longitude: The longitude of the AP."""

    latitude: float
    longitude: float


@dataclasses.dataclass
class HardwareInfo:
    """This class contains the hardware information of an AP.
    Attributes:
        model: The hardware model of the AP."""

    model: str
    nproc: int = 1


@dataclasses.dataclass
class OwnerInfo:
    """This class contains the owner information of an AP.
    Attributes:
        contact: The contact of the AP for example an email address."""

    contact: str


@dataclasses.dataclass
class SoftwareInfo:
    """This class contains the software information of an AP.
    Attributes:
        firmware: The firmware information of the AP."""

    firmware: FirmwareInfo


@dataclasses.dataclass
class InterfacesInfo:
    other: List[str]


@dataclasses.dataclass
class IntInfo:
    interfaces: InterfacesInfo


@dataclasses.dataclass
class NetworkInfo:
    """This class contains the network information of an AP.
    Attributes:
        mac: The MAC address of the AP."""

    mac: str
    mesh: Dict[str, IntInfo]


@dataclasses.dataclass
class SystemInfo:
    domain_code: str
    # Lokaler Zusatz (Neanderfunk): auch als site_code melden. Karten, die
    # je Ort nach site_code filtern, liessen die APs sonst heraus, so wie sie
    # es mit Supernodes tun, die nur domain_code melden. Der Wert ist der des
    # Freifunk-Knotens, hinter dem der AP haengt: in der nodelist steht unter
    # "domain" dessen gemeldeter Code (nef-05_mon, dus-15_mrh_EOL), und genau
    # den erbt der AP.
    site_code: str = ""


@dataclass_json
@dataclasses.dataclass
class NodeInfo:
    """This class contains the node information of an AP.
    Attributes:
        software: The software information of the AP.
        hostname: The hostname of the AP.
        node_id: The node id of the AP. This is the same as the MAC address (without :).
        location: The location information of the AP.
        hardware: The hardware information of the AP.
        owner: The owner information of the AP.
        network: The network information of the AP."""

    software: SoftwareInfo
    hostname: str
    node_id: str
    # Lokaler Zusatz (Neanderfunk): ohne Koordinaten fehlt der Ort ganz,
    # statt als 0/0 gemeldet zu werden
    location: LocationInfo = dataclasses.field(
        metadata=config(exclude=lambda wert: wert is None)
    )
    hardware: HardwareInfo
    owner: OwnerInfo
    network: NetworkInfo
    system: SystemInfo


@dataclasses.dataclass
class ClientInfo:
    """This class contains the client information of an AP.
    Attributes:
        total: The total number of clients.
        wifi: The number of clients connected via WiFi.
        wifi24: The number of clients connected via 2,4ghz WiFi.
        wifi5: The number of clients connected via 5ghz WiFi."""

    total: int
    wifi: int
    wifi24: int
    wifi5: int


@dataclasses.dataclass
class WirelessInfo:
    """This class contains the Wireless information of an AP.
    Attributes:
        frequency:
        noise:
        active:
        busy:
        rx:
        tx:"""

    frequency: int
    # noise: int
    rx: int
    tx: int
    # Lokaler Zusatz (Neanderfunk): Airtime-Zaehler in Millisekunden wie bei
    # Gluon; yanic bildet aus zwei Abfragen die Auslastung in Prozent.
    active: int = 0
    busy: int = 0


@dataclasses.dataclass
class MemoryInfo:
    """This class contains the memory information of an AP.
    Attributes:
        total: The total memory of the AP.
        free: The free memory of the AP.
        buffers: The buffer memory of the AP."""

    total: int
    free: int
    buffers: int


@dataclasses.dataclass
class txInfo:
    """This class contains the tx information of an AP.
    Attributes:
        bytes: The number of bytes transmitted."""

    bytes: int


@dataclasses.dataclass
class rxInfo:
    """This class contains the rx information of an AP.
    Attributes:
        bytes: The number of bytes received."""

    bytes: int


@dataclasses.dataclass
class TrafficInfo:
    """This class contains the traffic information of an AP.
    Attributes:
        tx: The tx information of the AP.
        rx: The rx information of the AP."""

    tx: txInfo
    rx: rxInfo


@dataclass_json
@dataclasses.dataclass
class StatisticsInfo:
    """This class contains the statistics information of an AP.
    Attributes:
        clients: The client information of the AP.
        uptime: The uptime of the AP.
        node_id: The node id of the AP. This is the same as the MAC address (without :).
        loadavg: The load average of the AP.
        memory: The memory information of the AP.
        traffic: The traffic information of the AP.
        gateway: The MAC of the IPv4 Gateway
        gateway6: The MAC of the IPv6 Gateway
        gateway_nexthop: The MAC of the nexthop Gateway
        wireless: The WirelessInfos of the AP"""

    clients: ClientInfo
    uptime: int
    node_id: str
    loadavg: float
    memory: MemoryInfo
    traffic: TrafficInfo
    gateway: str
    gateway6: str
    gateway_nexthop: str
    wireless: List[WirelessInfo]


@dataclasses.dataclass
class NeighbourDetails:
    tq: int
    lastseen: float


@dataclasses.dataclass
class Neighbours:
    neighbours: Dict[str, NeighbourDetails]


@dataclass_json
@dataclasses.dataclass
class NeighboursInfo:
    node_id: str
    batadv: Dict[str, Neighbours]


class ResponddClient:
    """This class receives a request from the respondd server and returns the response."""

    def __init__(self, config):
        self._config = config
        self._aps = None
        self._aps_zeit = 0.0
        self._timeStart = time.time()
        self._timeStop = time.time()
        self._sock = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)

    @property
    def _nodeinfos(self):
        return self.getNodeInfos()

    @property
    def _statistics(self):
        return self.getStatistics()

    @property
    def _neighbours(self):
        return self.getNeighbours()

    @staticmethod
    def joinMCAST(sock, addr, ifname):
        """Joins a multicast group on a socket."""
        group = socket.inet_pton(socket.AF_INET6, addr)
        if_idx = socket.if_nametoindex(ifname)
        sock.setsockopt(
            socket.IPPROTO_IPV6,
            socket.IPV6_JOIN_GROUP,
            group + struct.pack("I", if_idx),
        )

    def getNodeInfos(self):
        """This method returns the node information of all APs."""
        aps = self._aps
        nodes = []
        for ap in aps.accesspoints:
            nodes.append(
                NodeInfo(
                    software=SoftwareInfo(
                        firmware=FirmwareInfo(base="UniFi", release=ap.firmware)
                    ),
                    hostname=ap.name,
                    node_id=ap.mac.replace(":", ""),
                    location=(
                        LocationInfo(latitude=ap.latitude, longitude=ap.longitude)
                        if ap.latitude is not None and ap.longitude is not None
                        else None
                    ),
                    hardware=HardwareInfo(model=ap.model),
                    owner=OwnerInfo(contact=ap.contact),
                    network=NetworkInfo(
                        mac=ap.mac,
                        mesh={
                            "bat0": IntInfo(interfaces=InterfacesInfo(other=[ap.mac]))
                        },
                    ),
                    system=SystemInfo(
                        domain_code=ap.domain_code, site_code=ap.domain_code
                    ),
                )
            )
        return nodes

    @staticmethod
    def frequency_from_channel(channel):
        if channel >= 36:
            return 5000 + (channel) * 5
        else:
            if channel == 14:
                return 2484
            elif channel < 14:
                return 2407 + (channel) * 5

    def airtime_zaehler(self, ap):
        """Lokaler Zusatz (Neanderfunk): Kanalauslastung als Airtime-Zaehler.

        Gluon meldet je Funkmodul fortlaufende Zaehler (active, busy, rx, tx
        in Millisekunden), yanic rechnet aus der Differenz zweier Abfragen die
        Auslastung in Prozent. Der Controller liefert stattdessen Prozente
        (cu_total, cu_self_rx, cu_self_tx). Hier laufen die Zaehler mit der
        Uhr weiter, jeweils mit dem zuletzt bekannten Prozentwert; die
        Differenz, die yanic bildet, ergibt so genau diese Prozente. Der
        Controller erneuert die Werte nur alle paar Minuten, als Anhaltspunkt
        reicht das (adorfer 25.09.2026).
        """
        zaehler = self.__dict__.setdefault("_airtime", {})
        jetzt = time.monotonic()
        infos = []
        for band, (kanal, gesamt, rx, tx) in sorted(ap.airtime.items()):
            z = zaehler.get((ap.mac, band))
            if z is None:
                z = zaehler[(ap.mac, band)] = {
                    "zeit": jetzt, "active": 0.0, "busy": 0.0, "rx": 0.0, "tx": 0.0
                }
            ms = (jetzt - z["zeit"]) * 1000
            z["zeit"] = jetzt
            z["active"] += ms
            z["busy"] += ms * min(gesamt, 100) / 100
            z["rx"] += ms * min(rx, 100) / 100
            z["tx"] += ms * min(tx, 100) / 100
            infos.append(
                WirelessInfo(
                    frequency=self.frequency_from_channel(kanal),
                    active=int(z["active"]),
                    busy=int(z["busy"]),
                    rx=int(z["rx"]),
                    tx=int(z["tx"]),
                )
            )
        return infos

    def getStatistics(self):
        """This method returns the statistics information of all APs."""
        aps = self._aps
        statistics = []
        for ap in aps.accesspoints:
            wirelessinfos = []

            # Lokaler Zusatz (Neanderfunk): mit Kanalauslastung aus dem
            # Controller echte Airtime; die Bytezaehler, die hier bisher als
            # rx/tx standen, sind keine Airtime.
            if getattr(ap, "airtime", None):
                wirelessinfos = self.airtime_zaehler(ap)
            nur_kanal = not wirelessinfos

            if nur_kanal and ap.channel5:
                frequency5 = self.frequency_from_channel(ap.channel5)
                wirelessinfos.append(
                    WirelessInfo(
                        frequency=frequency5,
                        rx=ap.rx_bytes5,
                        tx=ap.tx_bytes5,
                    )
                )

            if nur_kanal and ap.channel24:
                frequency24 = self.frequency_from_channel(ap.channel24)
                wirelessinfos.append(
                    WirelessInfo(
                        frequency=frequency24,
                        rx=ap.rx_bytes5,
                        tx=ap.tx_bytes5,
                    )
                )

            statistics.append(
                StatisticsInfo(
                    clients=ClientInfo(
                        total=ap.client_count,
                        wifi=ap.client_count,
                        wifi24=ap.client_count24,
                        wifi5=ap.client_count5,
                    ),
                    uptime=ap.uptime,
                    node_id=ap.mac.replace(":", ""),
                    loadavg=ap.load_avg,
                    memory=MemoryInfo(
                        total=int(ap.mem_total / 1024),
                        free=int((ap.mem_total - ap.mem_used) / 1024),
                        buffers=int(ap.mem_buffer / 1024),
                    ),
                    traffic=TrafficInfo(
                        tx=txInfo(bytes=int(ap.tx_bytes)),
                        rx=rxInfo(bytes=int(ap.rx_bytes)),
                    ),
                    gateway=ap.gateway,
                    gateway6=ap.gateway6,
                    gateway_nexthop=ap.gateway_nexthop,
                    wireless=wirelessinfos,
                )
            )
        return statistics

    def getNeighbours(self):
        """This method returns the neighbour information of all APs."""
        aps = self._aps
        neighbours = []
        for ap in aps.accesspoints:
            nbs = {}
            for neighbour_mac in ap.neighbour_macs:
                if neighbour_mac is not None:
                    nbs[neighbour_mac] = NeighbourDetails(tq=255, lastseen=0.45)
            neighbours.append(
                NeighboursInfo(
                    node_id=ap.mac.replace(":", ""),
                    batadv={ap.mac: Neighbours(neighbours=nbs)},
                )
            )
        return neighbours

    # --- Lokaler Zusatz (Neanderfunk): mehrere Schnittstellen, je Domain gefiltert ---

    def frische_aps(self):
        """Controllerdaten holen, aber hoechstens alle cache_seconds."""
        alter = time.time() - self._aps_zeit
        if self._aps is None or alter >= getattr(self._config, "cache_seconds", 0):
            aps = unifi_client.get_infos()
            if aps is not None:
                self._aps = aps
                self._aps_zeit = time.time()
        return self._aps

    def ids_fuer(self, site_codes):
        """node_ids der APs, deren Router einen dieser site_codes meldet."""
        erlaubt = set(site_codes or [])
        return {
            ap.mac.replace(":", "")
            for ap in (self._aps.accesspoints if self._aps else [])
            if ap.domain_code in erlaubt
        }

    @staticmethod
    def schnittstelle_aus(ancdata):
        """Ankunftsschnittstelle aus IPV6_PKTINFO (in6_addr, ifindex)."""
        for ebene, art, daten in ancdata:
            if ebene == socket.IPPROTO_IPV6 and art == socket.IPV6_PKTINFO:
                ifindex = struct.unpack("I", daten[16:20])[0]
                try:
                    return socket.if_indextoname(ifindex)
                except OSError:
                    return None
        return None

    def listenMulti(self):
        """Wie listenMulticast, liefert zusaetzlich die Ankunftsschnittstelle."""
        msg, ancdata, _flags, sourceAddress = self._sock.recvmsg(
            2048, socket.CMSG_SPACE(20)
        )
        return str(msg, "UTF-8").split(" "), sourceAddress, self.schnittstelle_aus(ancdata)

    def startMulti(self):
        """Auf allen Schnittstellen aus "interfaces" lauschen.

        Jede Anfrage wird mit genau den APs beantwortet, deren Router in der
        Domain der Ankunftsschnittstelle steht. So sieht jeder Sammler in
        jedem Mesh, was dorthin gehoert, wie bei einem echten Knoten; auch
        fremde Sammler, die im Mesh fragen (adorfer 25.09.2026).
        """
        schnittstellen = self._config.interfaces
        self._sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_RECVPKTINFO, 1)
        # Port 1001 teilen, etwa mit mesh-announce, das fuer den Rechner selbst
        # antwortet. Multicast-Anfragen bekommen dann beide; eine
        # Unicast-Anfrage nur einer von beiden.
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("::", self._config.multicast_port))
        for ifname in schnittstellen:
            try:
                self.joinMCAST(self._sock, self._config.multicast_address, ifname)
            except OSError as ex:
                logger.error("join %s: %s" % (ifname, ex))
        while True:
            msgSplit, sourceAddress, ifname = self.listenMulti()
            if ifname not in schnittstellen:
                continue
            self._timeStart = time.time()
            if self.frische_aps() is None:
                continue
            nur = self.ids_fuer(schnittstellen[ifname])
            if not nur:
                continue
            responseStruct = {}
            if msgSplit[0] == "GET":
                for request in msgSplit[1:]:
                    responseStruct[request] = self.buildStruct(request)
                self.sendStruct(sourceAddress, responseStruct, True, nur)
            else:
                responseStruct = self.buildStruct(msgSplit[0])
                self.sendStruct(sourceAddress, responseStruct, False, nur)
            self._timeStop = time.time()

    def listenMulticast(self):
        msg, sourceAddress = self._sock.recvfrom(2048)
        logger.info("Using multicast method")
        msgSplit = str(msg, "UTF-8").split(" ")

        return msgSplit, sourceAddress

    def sendUnicast(self):
        logger.info("Using unicast method")

        timeSleep = int(60 - (self._timeStop - self._timeStart) % 60)
        if self._config.verbose:
            logger.debug("will now sleep " + str(timeSleep) + " seconds")
        time.sleep(timeSleep)

    def start(self):
        """This method starts the respondd client."""
        if getattr(self._config, "interfaces", None) and self._config.multicast_enabled:
            return self.startMulti()
        self._sock.setsockopt(
            socket.SOL_SOCKET,
            socket.SO_BINDTODEVICE,
            bytes(self._config.interface.encode()),
        )
        if self._config.multicast_enabled:
            self._sock.bind(("::", self._config.multicast_port))

            self.joinMCAST(
                self._sock, self._config.multicast_address, self._config.interface
            )

        while True:
            responseStruct = {}
            sourceAddress = (self._config.unicast_address, self._config.unicast_port)
            msgSplit = ["GET", "nodeinfo", "statistics", "neighbours"]

            if self._config.multicast_enabled:
                msgSplit, sourceAddress = self.listenMulticast()
            else:
                self.sendUnicast()
            self._timeStart = time.time()
            self._aps = unifi_client.get_infos()
            if self._aps is None:
                continue
            if msgSplit[0] == "GET":  # multi_request
                for request in msgSplit[1:]:
                    responseStruct[request] = self.buildStruct(request)
                self.sendStruct(sourceAddress, responseStruct, True)
            else:  # single_request
                responseStruct = self.buildStruct(msgSplit[0])
                self.sendStruct(sourceAddress, responseStruct, False)
            self._timeStop = time.time()

    def merge_node(self, responseStruct):
        """This method merges the node information of all APs to their corresponding node_id."""
        merged = {}
        for key in responseStruct.keys():
            if responseStruct[key]:
                for info in responseStruct[key]:
                    if info.node_id not in merged:
                        merged[info.node_id] = {key: info}
                    else:
                        merged[info.node_id].update({key: info})
        return merged

    def buildStruct(self, responseType):
        """This method builds the response structure."""

        responseClass = None
        if responseType == "statistics":
            responseClass = self._statistics
        elif responseType == "nodeinfo":
            responseClass = self._nodeinfos
        elif responseType == "neighbours":
            responseClass = self._neighbours
        else:
            logger.warning("unknown command: " + responseType)
            return

        return responseClass

    def sendStruct(self, destAddress, responseStruct, withCompression, nur=None):
        """This method sends the response structure to the respondd server.

        Lokaler Zusatz: mit nur (Menge von node_ids) gehen nur diese Knoten raus.
        """
        logger.debug(
            str(destAddress[0]) + " " + str(destAddress[1]) + " " + str(responseStruct)
        )

        merged = self.merge_node(responseStruct)
        if nur is not None:
            merged = {k: v for k, v in merged.items() if k in nur}
        for infos in merged.values():
            node = {}
            for key, info in infos.items():
                node.update({key: info.to_dict()})
            responseData = bytes(json.dumps(node), "UTF-8")
            logger.info(str(responseData))

            if withCompression:
                encoder = zlib.compressobj(
                    zlib.Z_DEFAULT_COMPRESSION, zlib.DEFLATED, -15
                )
                responseData = encoder.compress(responseData)
                responseData += encoder.flush()

            # Lokaler Zusatz (Neanderfunk): ein Paket, das nicht rausgeht,
            # darf den Dienst nicht beenden. Am 25.09.2026 lief die
            # IPv6-Nachbartabelle ueber, sendto scheiterte mit EINVAL, und
            # der Dienst stuerzte alle fuenf Minuten ab.
            try:
                self._sock.sendto(responseData, destAddress)
            except OSError as ex:
                logger.warning("sendto %s: %s" % (destAddress[0], ex))
