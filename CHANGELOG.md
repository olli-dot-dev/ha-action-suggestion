# Changelog

## 0.2.0

- Neue Custom Card "Action Suggestion – Vorschlagsliste"
  (`custom:action-suggestion-list-card`): sammelt automatisch alle gerade
  aktiven Vorschläge in einer Karte, erkannt an der Attribut-Kombination der
  Vorschlags-Entitäten statt an ihrer (variablen) `entity_id`. Wird beim
  Integrationsstart automatisch als Lovelace-Ressource registriert, kein
  manueller Eintrag unter Dashboards → Ressourcen nötig.

## 0.1.0

Erste Version.

- Kontext-basierte Erkennung manueller Schaltvorgänge (`context.user_id`)
- Bereichs-basierter Kontext-Snapshot (numerische Werte gebinnt, Wochentag +
  konfigurierbares Zeitfenster)
- Eigene SQLite-Datenbank, unabhängig von der Recorder-DB
- Häufigkeits-/Konsistenz-Engine mit Decay und konfigurierbaren Schwellenwerten
- Eine Vorschlags-Entity pro erkanntem, aktuell zutreffendem Muster
- `execute_suggestion`-Service für generische Lovelace-Karten, `reset`-Service
- Deutsche + englische Übersetzung
