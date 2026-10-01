#!/usr/bin/env python3
"""Lokaler Zusatz (Neanderfunk): Modellnamen statt Codes (model_names)."""

import json
from unittest.mock import Mock

from unifi_respondd.unifi_client import MODELLE, modellname


def _cfg(an):
    cfg = Mock()
    cfg.model_names = an
    return cfg


def test_aus_bleibt_der_code():
    assert modellname("U7MSH", _cfg(False)) == "U7MSH"


def test_mock_zaehlt_nicht_als_an():
    # Nur ein echtes True schaltet um, ein fehlender Schluessel nicht
    assert modellname("U7MSH", Mock()) == "U7MSH"


def test_an_uebersetzt():
    assert modellname("U7MSH", _cfg(True)) == "Ubiquiti UniFi AC Mesh"
    assert modellname("UAPA693", _cfg(True)) == "Ubiquiti UniFi U7 Lite"


def test_unbekannt_und_leer_bleiben():
    assert modellname("XYZ123", _cfg(True)) == "XYZ123"
    assert modellname(None, _cfg(True)) is None


def test_namen_wie_gluon():
    # Dieselbe Hardware heisst mit Gluon so; Statistik und Geraetebilder
    # haengen am genauen Namen
    t = json.load(open(MODELLE))
    assert t["U7PG2"] == "Ubiquiti UniFi AC Pro"
    assert t["U7LT"] == "Ubiquiti UniFi AC Lite"
    assert t["U7LR"] == "Ubiquiti UniFi AC LR"
    assert t["U7MP"] == "Ubiquiti UniFi AC Mesh Pro"
