# Action Suggestion

> **Beta:** Diese Integration ist noch in aktiver Entwicklung. Funktioniert im
> Alltag, aber Konfigurationsoptionen, Schwellenwerte und das Datenbankschema
> können sich zwischen Versionen noch ändern – vor einem Update ggf. `patterns.db`
> sichern. Feedback und Issues sind willkommen.

Home-Assistant-Integration, die aus deinen vergangenen **manuellen** Schaltvorgängen
Muster nach Wochentag, Uhrzeit und Zustand anderer Entities im selben Bereich lernt
und passende Aktionen als **Vorschlag im Dashboard** anbietet – nicht als automatisch
ausgeführte Automation.

## Was es nicht ist

- Keine KI/ML-Modelle, kein LLM-Call, keine Cloud-Abhängigkeit – reine
  Häufigkeits-/Konsistenz-Zählung, läuft komplett lokal
- Keine automatische Erstellung oder Ausführung von Automationen
- Keine automatische Ausführung der vorgeschlagenen Aktion – du tippst sie aktiv im
  Dashboard an
- Kein Sammeln von Kontext-Daten außerhalb des jeweiligen Bereichs (Area) einer Person

## Funktionsweise

1. **Nur echte manuelle Aktionen zählen.** Ein Zustandswechsel fließt nur ein, wenn
   Home Assistant ihn eindeutig einer Person zuordnen kann (`context.user_id`
   gesetzt – App, UI, Sprachassistent). Von einer Automation/einem Script ausgelöste
   Wechsel sowie Wechsel ohne zuordenbaren Kontext (typischerweise ein physischer
   Schalter) werden verworfen – letzteres ist für v1 eine bewusste Einschränkung,
   siehe [Spätere Erweiterungen](#spätere-erweiterungen).
2. **Kontext-Snapshot.** Bei jeder gewerteten manuellen Aktion wird der Zustand aller
   *anderen* Entities im selben Bereich mit erfasst (numerische Werte gerundet, um
   Rauschen zu reduzieren), zusammen mit Wochentag und einem konfigurierbaren
   Zeitfenster (15 oder 30 Minuten).
3. **Häufigkeits-/Konsistenz-Engine.** Für jede Kombination aus Entity, Wochentag,
   Zeitfenster und Kontext wird gezählt, wie oft sie vorkam und wie *konsistent*
   dabei immer dasselbe passiert ist (nicht nur "kommt oft vor", sondern "kommt fast
   immer zum selben Ergebnis"). Ältere, nicht mehr bestätigte Ausprägungen verlieren
   über einen Decay-Faktor an Gewicht gegenüber aktuelleren.
4. **Vorschlags-Entity.** Erreicht ein Muster die konfigurierten Schwellenwerte
   (Mindestanzahl Beobachtungen, Mindest-Konsistenz) *und* passen gerade Wochentag,
   Zeitfenster und Kontext, wird eine Vorschlags-Entity aktiv. Ihr Name ist
   `Vorschlag <Anzeigename der Ziel-Entity>`; daraus leitet Home Assistant beim
   erstmaligen Anlegen automatisch eine `entity_id` ab (typischerweise
   `sensor.vorschlag_<slugifizierter Anzeigename>`, siehe Beispiel unten - bei
   Namenskollisionen mit Suffix `_2` usw., und einmal vergeben bleibt sie auch nach
   späterer Umbenennung der Ziel-Entity bestehen). Die tatsächliche ID also im
   Entity-Register nachsehen, statt sie zu erraten.
5. **Tippst du den Vorschlag an**, wird die vorgeschlagene Aktion ausgeführt – das
   erzeugt wieder ein ganz normales `context.user_id`-Event und verstärkt das
   erkannte Muster automatisch weiter.

## Installation

### Via HACS (empfohlen)

Als benutzerdefiniertes Repository hinzufügen (`https://github.com/olli-dot-dev/ha-action-suggestion`,
Kategorie „Integration“), dann „Action Suggestion“ installieren und Home Assistant
neu starten.

### Manuell

`custom_components/action_suggestion` in dein Home-Assistant-`config`-Verzeichnis
kopieren und neu starten.

## Einrichtung

**Einstellungen → Geräte & Dienste → Integration hinzufügen → Action Suggestion.**
Danach die Bereiche (Areas) auswählen, aus denen gelernt werden soll – nur
Entities in diesen Bereichen werden überhaupt beobachtet, und ein Kontext-Snapshot
reicht nie über den Bereich der geänderten Entity hinaus.

Über **Konfigurieren** an der Integration lassen sich anschließend anpassen:

| Option | Standard | Bedeutung |
| --- | --- | --- |
| Zeitfenster-Größe | 30 Min | Wie grob Uhrzeiten zusammengefasst werden |
| Rundungsschritt (numerischer Kontext) | 2 | z.B. Temperatur in 2°-Schritten |
| Mindestanzahl Beobachtungen | 3 | Ab wann ein Muster überhaupt zählt |
| Mindest-Konsistenz | 0.7 (70 %) | Wie zuverlässig dasselbe passieren muss |
| Decay-Faktor | 0.9 | Wie schnell veraltete Ausprägungen an Gewicht verlieren |

Eine Änderung lädt die Integration neu; bereits gelernte Daten bleiben erhalten
(eigene SQLite-Datenbank unter `<config>/action_suggestion/patterns.db`, nicht die
Recorder-DB).

## Lovelace-Karten

Jede Vorschlags-Entity hat den Zustand `active`/`inactive` und die Attribute
`target_entity_id`, `action`, `new_state`, `confidence`, `observations` und `reason`.

### Vorschlagsliste (empfohlen)

Die Integration bringt eine eigene Custom Card **"Action Suggestion –
Vorschlagsliste"** (`custom:action-suggestion-list-card`) mit, die automatisch
*alle* gerade aktiven Vorschläge sammelt und anzeigt - kein Kartenverdrahten
pro Vorschlags-Entity nötig, und neue Vorschläge tauchen von selbst auf.
Erkannt werden Vorschlags-Entitäten rein an der Attribut-Kombination oben
(nicht an der `entity_id`, die sich wie beschrieben pro Ziel-Anzeigename
unterscheidet). Die Karte wird beim Start der Integration automatisch als
Lovelace-Ressource registriert - kein manuelles Eintragen unter
**Einstellungen → Dashboards → Ressourcen** nötig, einfach im
Dashboard-Editor unter "Karte hinzufügen" nach "Vorschlagsliste" suchen oder
direkt eintragen:

```yaml
type: custom:action-suggestion-list-card
title: Vorschläge  # optional, Default: "Vorschläge"
```

Ein Tap auf einen Eintrag führt die vorgeschlagene Aktion aus, genau wie beim
manuellen Beispiel unten. Ohne aktive Vorschläge zeigt die Karte einen
Platzhaltertext statt zu verschwinden, damit sie im Dashboard nicht ständig
auftaucht und wieder wegspringt.

### Einzelne Vorschlags-Entity (für gezielt platzierte Karten)

Für einen bestimmten Vorschlag fest an einer Stelle im Dashboard (statt in
der gesammelten Liste) funktioniert auch eine normale Button-Card unverändert
für **jede** Vorschlags-Entity, da der Tap den generischen
`action_suggestion.execute_suggestion`-Service auf die Entity selbst aufruft,
statt eine bestimmte Aktion fest zu verdrahten. `sensor.vorschlag_wohnzimmer_licht`
im folgenden Beispiel ist ein Platzhalter (setzt eine Ziel-Entity mit
Anzeigenamen "Wohnzimmer Licht" voraus, siehe oben) - die tatsächliche
`entity_id` in **Entwicklertools → Zustände** nachsehen (Filter `vorschlag`)
und entsprechend anpassen:

```yaml
type: button
entity: sensor.vorschlag_wohnzimmer_licht
name: "{{ state_attr('sensor.vorschlag_wohnzimmer_licht', 'reason') }}"
icon: mdi:lightbulb-on-outline
show_state: false
tap_action:
  action: call-service
  service: action_suggestion.execute_suggestion
  target:
    entity_id: sensor.vorschlag_wohnzimmer_licht
```

Damit die Karte nur auftaucht, wenn wirklich etwas vorgeschlagen wird, in eine
[conditional card](https://www.home-assistant.io/dashboards/conditional/) packen:

```yaml
type: conditional
conditions:
  - entity: sensor.vorschlag_wohnzimmer_licht
    state: "active"
card:
  type: button
  entity: sensor.vorschlag_wohnzimmer_licht
  tap_action:
    action: call-service
    service: action_suggestion.execute_suggestion
    target:
      entity_id: sensor.vorschlag_wohnzimmer_licht
```

## Services

- `action_suggestion.execute_suggestion` – führt die aktuell vorgeschlagene Aktion
  der Ziel-Entity(s) aus (siehe Lovelace-Beispiel oben).
- `action_suggestion.reset` – löscht alle gelernten Events und Muster. Hauptsächlich
  zum Testen/Troubleshooting, nicht für den täglichen Gebrauch gedacht.

## v1-Umfang

1. Kontext-basierte Erkennung manueller Schaltvorgänge (Person vs. Automation)
2. Bereichs-basierter Kontext-Snapshot
3. Häufigkeits-/Konsistenz-Engine mit konfigurierbaren Schwellenwerten
4. Eine Vorschlags-Entity pro erkanntem Muster
5. Beispiel-Lovelace-Konfiguration (siehe oben)

## Spätere Erweiterungen

- Erkennung physischer Schalter-Events (kein `context.user_id`, kein `parent_id`)
- Konfigurierbare Kontext-Sensoren zusätzlich zum Bereichs-Scoping
- UI-gestützte Vorschlagsverwaltung (Verwerfen/Feedback direkt im Frontend)

## Bekannte Grenzen (v1)

- Vorschläge werden nur für Entities erzeugt, deren Zielzustand sich sicher als
  Service-Aufruf ausdrücken lässt (aktuell: `light`/`switch`/`fan`/`input_boolean`/
  `humidifier` `on`/`off`, `cover` `open`/`closed`, `lock` `locked`/`unlocked`).
  Andere Domains (z.B. `climate`-Modi, `cover`-Positionen) werden weiterhin gelernt,
  aber nicht als Vorschlag angezeigt.
- Die Zuordnung "durch eine Automation ausgelöst" vs. "physischer Schalter" ist eine
  grobe Heuristik (siehe `classification.py`) – für die eigentliche Filterung
  (lernen ja/nein) reicht das, für Diagnose-Zwecke ist sie nicht als verlässliche
  Quelle "welche Automation genau" gedacht.
- Der Kontext-Snapshot nimmt aktuell **alle** anderen Entities im Bereich mit,
  ungefiltert. Bei Bereichen mit vielen unruhigen/diagnostischen Sensoren (WLAN-Signal,
  Uptime, Leistungsmessung, ...) kann das dazu führen, dass sich kaum je exakt
  derselbe Kontext wiederholt und entsprechend selten genug Beobachtungen für einen
  Schwellenwert zusammenkommen – numerisches Runden hilft nur bei Sensoren, die sich
  in engen Bahnen bewegen, nicht bei grundsätzlich hochfrequent schwankenden Werten.
  Eine gezielte Auswahl relevanter Kontext-Sensoren statt des kompletten Bereichs ist
  bewusst auf später verschoben (siehe "Spätere Erweiterungen") – bis dahin am besten
  mit klar abgegrenzten, wenig "lauten" Bereichen anfangen und beobachten, ob
  überhaupt Muster mit genug Beobachtungen entstehen.

## Entwicklung

Diese Integration wird gemeinsam mit [Claude Code](https://claude.com/claude-code)
entwickelt – von der Spec über die Implementierung bis zu Tests und Doku. Claude
ist dementsprechend in den Commits als Co-Author geführt.
