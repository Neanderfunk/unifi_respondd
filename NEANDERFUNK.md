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

Alle neuen Konfigurationsschlüssel sind optional. Ohne sie verhält sich der
Zweig wie das Original.

Lizenz wie das Original: GPL-3.0.

Aktualisieren auf einen neuen Upstream-Stand:

```bash
git fetch upstream
git rebase <neuer-upstream-commit> neanderfunk
python -m pytest tests
```
