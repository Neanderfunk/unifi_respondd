#!/usr/bin/env python3
"""Lokaler Zusatz (Neanderfunk): Modellnamen der UniFi-Accesspoints.

  python3 werkzeug/modelle-erzeugen.py > unifi_respondd/modelle.json

Der Controller nennt das Modell nur mit seinem internen Code (U7PG2, U7MSH,
UAPA693). Auf der Karte fuehrt das zu Rueckfragen: U7MSH ist kein U7, sondern
das AC Mesh von 2017, der U7 Lite heisst UAPA693. Diese Tabelle uebersetzt
den Code in den Namen, unter dem dieselbe Hardware mit Gluon gemeldet wird
("Ubiquiti UniFi AC Mesh"); so stehen beide in der Statistik zusammen und
finden dieselben Geraetebilder.

Quelle ist Ubiquitis oeffentliche Geraetedatenbank. Sie wird nur hier beim
Erzeugen gelesen, nicht im Betrieb.
"""
import json
import sys
import urllib.request

QUELLE = "https://static.ui.com/fingerprint/ui/public.json"


def modelle(geraete):
    tabelle = {}
    for g in geraete:
        netz = (g.get("unifi") or {}).get("network") or {}
        code = netz.get("model")
        if netz.get("type") != "uap" or not code:
            continue
        produkt = g.get("product") or {}
        kurz = produkt.get("abbrev") or (produkt.get("name") or "").removeprefix("Access Point ").strip()
        if kurz:
            tabelle[code] = "Ubiquiti UniFi " + kurz
    return dict(sorted(tabelle.items()))


def main():
    with urllib.request.urlopen(QUELLE, timeout=60) as antwort:
        geraete = json.load(antwort)["devices"]
    tabelle = modelle(geraete)
    if len(tabelle) < 20:
        sys.exit(f"nur {len(tabelle)} Accesspoints in der Datenbank, Format geaendert?")
    json.dump(tabelle, sys.stdout, indent=1, ensure_ascii=False)
    print()


if __name__ == "__main__":
    main()
