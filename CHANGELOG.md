# Changelog

## 0.2.2

- Diagnose: die Vorschlagsliste-Karte lädt über `add_extra_js_url`
  unabhängig vom Dashboard-Rendering nach, statt wie eine reguläre
  Lovelace-Ressource vor dem Kartenrendern abgewartet zu werden - bei
  höherer Latenz (z.B. Nabu-Casa-Fernzugriff) kann das Element sich beim
  Neuladen der Seite knapp zu spät registrieren, Home Assistant baut die
  Karte danach aber automatisch neu auf (`ll-rebuild`), kein dauerhafter
  Fehler. README dokumentiert das jetzt inkl. Alternative (manueller
  Ressourcen-Eintrag, dann kein Wettlauf mehr, wie bei HACS-Karten).
- Fix: `customElements.define`/`window.customCards.push` gegen doppeltes
  Laden abgesichert (z.B. wenn zusätzlich zur Auto-Registrierung noch
  manuell eine Ressource eingetragen wird) - vorher hätte ein zweiter
  `customElements.define`-Aufruf für denselben Tag-Namen das ganze Modul
  zum Absturz gebracht.

## 0.2.1

- Fix: Vorschlagsliste-Karte registrierte sich nicht im Browser ("Custom
  element not found"), obwohl die Datei direkt abrufbar war und die
  Integration fehlerfrei lief - Ursache: fehlender/falscher Content-Type auf
  `action-suggestion-card.js`. `add_extra_js_url` lädt die Datei als
  `<script type="module">`, und Browser verweigern die Ausführung eines
  Modul-Skripts still, wenn der Server nicht exakt einen JS-MIME-Type
  liefert. Content-Type jetzt explizit auf `text/javascript` gesetzt statt
  der (auf manchen Systemen unzuverlässigen) automatischen Erkennung zu
  vertrauen.

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
