# Changelog

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
