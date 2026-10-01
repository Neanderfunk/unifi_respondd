# Zweig `neanderfunk`

Dieser Fork von [freifunkMUC/unifi_respondd](https://github.com/freifunkMUC/unifi_respondd)
wird von Freifunk Neanderland für die Karte `neander.map.freifunk.space` betrieben.
Der Zweig `main` folgt unverändert dem Original, unsere Änderungen liegen im
Zweig `neanderfunk`, je Funktion ein Commit auf dem Upstream-Stand
`6976651` (18.09.2026). Jeder Commit besteht die Tests für sich, sie lassen sich
also einzeln übernehmen oder bei einem Upstream-Update einzeln nachziehen.

| Commit | Was |
| --- | --- |
| Router je Accesspoint (`offloader_by_ap`) | Router je AP aus einer gemessenen Zuordnung statt einem je Site |
| Ortscode als `site_code` | APs erscheinen auf Karten, die je Ort filtern |
| Kein Ort statt 0/0 | APs ohne Koordinaten landen nicht auf "Null Island" |
| Alle Schnittstellen, je Domain gefiltert | ein Prozess für viele Domains; Controller zwischengespeichert |
| Koordinaten ohne Adresssuche | keine Anfragen an Nominatim; gängige Schreibweisen und aus Google Maps kopierte Adressen werden gesäubert |
| Airtime aus dem Controller | Kanalauslastung je Band (cu_total, cu_self_rx/tx) als Airtime-Zähler wie bei Gluon; vorher standen Bytezähler in den Airtime-Feldern |
| Port 1001 teilen | `SO_REUSEADDR`, damit mesh-announce für den Rechner selbst daneben laufen kann |
| Sendefehler beenden nicht den Dienst | ein Paket, das nicht rausgeht, wird protokolliert statt den Prozess zu beenden |
| Mehrere Controller (`controllers`) | weitere Controller neben dem ersten, je mit eigenem Router je Site; fällt einer aus, kommen die APs der anderen trotzdem |
| Keine Zertifikatswarnung bei `ssl_verify` aus | bewusst abgeschaltete Prüfung (selbstsigniert, hinter einem Tunnel) schreibt nicht mehr je Anfrage eine Warnung ins Log |
| Modellnamen statt Codes (`model_names`) | "Ubiquiti UniFi AC Mesh" statt "U7MSH", wie dieselbe Hardware mit Gluon heißt; Tabelle `unifi_respondd/modelle.json` aus Ubiquitis Gerätedatenbank, erneuern mit `werkzeug/modelle-erzeugen.py` |

Alle neuen Konfigurationsschlüssel sind optional. Ohne sie verhält sich der
Zweig wie das Original, mit zwei Ausnahmen: APs ohne Koordinaten bekommen
keinen Ort statt 0/0, und das Feld SNMP Location wird nur noch als Koordinate
gelesen, nie mehr als Adresse bei Nominatim nachgeschlagen.

Weitere Controller stehen unter `controllers`; Port, Version und
`ssl_verify` gelten wie beim ersten, wenn sie fehlen. `offloader_mac` gilt nur
für den eigenen Controller, Site-Namen wie `Default` kommen bei jedem vor:

```yaml
controllers:
  - name: Beispiel
    controller_url: 192.0.2.10
    username: leser
    password: geheim
    version: UDMP-unifiOS
    ssl_verify: false
    offloader_mac:
      Default: "80:af:ca:00:00:01"
```

Lesbar sind im Feld SNMP Location unter anderem `51.2874, 6.3538`,
`51,2874 6,3538`, `51,2874,6,3538`, dazu Leerzeichen, `&`, `?`, Klammern
und Anführungszeichen an den Rändern sowie aus Google Maps kopierte Adressen
(`!3d…!4d…`, `?q=…`, `/@…,17z`). Himmelsrichtungen vor oder hinter der Zahl
(`51.2874 N, 6.3538 E`, `O` für Ost) und Grad/Minuten/Sekunden
(`51°17'14.8"N 6°21'13.7"E`) gehen ebenfalls; mit Richtung darf die
Reihenfolge vertauscht sein. Unlesbar bleibt nur, was sich widerspricht
(Minus und Richtung zugleich, zwei Breiten, Minuten ab 60) und Kurzlinks
ohne Koordinaten.

Lizenz wie das Original: GPL-3.0.

Aktualisieren auf einen neuen Upstream-Stand, per Merge, nicht per Rebase:
auf die Commits dieses Zweigs verweisen veröffentlichte Links (etwa aus
Forenbeiträgen), ein Rebase würde ihre IDs ändern und einen Force-Push
brauchen (Regel seit 28.09.2026; bis dahin gab es upstream nichts Neues).

```bash
git fetch upstream
git merge upstream/main
python -m pytest tests
```
