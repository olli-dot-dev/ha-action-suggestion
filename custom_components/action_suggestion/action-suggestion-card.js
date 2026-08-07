/* Action Suggestion - "Vorschlagsliste" card.
 *
 * Collects and shows every currently-active suggestion sensor in one card,
 * so a dashboard doesn't need one manually-wired conditional card per
 * suggestion entity (see README "Spätere Erweiterungen"). Tapping a row
 * calls the integration's own `execute_suggestion` service, exactly like
 * the single-entity button-card example in the README.
 *
 * There is deliberately no config option naming specific entities: which
 * suggestion sensors exist (and their entity_ids) is entirely up to Home
 * Assistant's own slugification of "Vorschlag <target friendly name>" at
 * creation time (see sensor.py `name`), so hand-picking entity_ids in the
 * card config would be fragile. Instead this card recognises suggestion
 * sensors purely by their state-attribute shape (see FINGERPRINT_ATTRS
 * below), the same attributes documented in the README - true for every
 * entity this integration ever creates, regardless of its entity_id.
 */

const FINGERPRINT_ATTRS = [
  "target_entity_id",
  "action",
  "new_state",
  "confidence",
  "observations",
  "reason",
];

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

class ActionSuggestionListCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    // Cheap re-render guard: `hass` is re-assigned on *every* state change
    // anywhere in the system, not just on our own sensors, since a card has
    // no way to subscribe to a subset of entities. Rebuilding the DOM on
    // every one of those would be wasteful - only actually re-render when
    // the set of active suggestions (or their attributes) changed.
    this._lastSignature = null;
  }

  setConfig(config) {
    this._config = config || {};
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() {
    return Math.max(1, this._activeSuggestions().length + 1);
  }

  static getStubConfig() {
    return {};
  }

  _activeSuggestions() {
    if (!this._hass) return [];
    const suggestions = Object.values(this._hass.states).filter(
      (s) =>
        s.entity_id.startsWith("sensor.") &&
        s.state === "active" &&
        FINGERPRINT_ATTRS.every((attr) => attr in s.attributes)
    );
    // Most confident first; observations as a tiebreaker so a well-attested
    // pattern outranks a barely-qualifying one at the same confidence.
    suggestions.sort((a, b) => {
      const byConfidence = (b.attributes.confidence ?? 0) - (a.attributes.confidence ?? 0);
      if (byConfidence !== 0) return byConfidence;
      return (b.attributes.observations ?? 0) - (a.attributes.observations ?? 0);
    });
    return suggestions;
  }

  _tap(entityId) {
    if (!this._hass) return;
    this._hass.callService("action_suggestion", "execute_suggestion", { entity_id: entityId });
  }

  _signature(suggestions) {
    // Not just entity_ids - a suggestion can flip its target action/state
    // (e.g. now suggests "off" instead of "on" for the same context) without
    // the entity_id itself changing, and that needs to be reflected too.
    return suggestions
      .map((s) => `${s.entity_id}|${s.attributes.action}|${s.attributes.new_state}|${s.attributes.confidence}|${s.attributes.observations}`)
      .join(";");
  }

  _render() {
    if (!this.shadowRoot || !this._config) return;
    const suggestions = this._activeSuggestions();
    const signature = this._signature(suggestions);
    if (signature === this._lastSignature) return;
    this._lastSignature = signature;

    const title = this._config.title ?? "Vorschläge";
    const body =
      suggestions.length === 0
        ? `<div class="empty">Aktuell keine Vorschläge.</div>`
        : suggestions.map((s) => this._rowHtml(s)).join("");

    this.shadowRoot.innerHTML = `
      <style>
        ha-card { padding-bottom: 4px; }
        .empty {
          padding: 16px;
          color: var(--secondary-text-color);
          font-style: italic;
        }
        .suggestion-row {
          display: flex;
          align-items: center;
          gap: 12px;
          width: 100%;
          padding: 12px 16px;
          background: none;
          border: none;
          border-top: 1px solid var(--divider-color);
          font: inherit;
          color: inherit;
          text-align: left;
          cursor: pointer;
        }
        .suggestion-row:first-child { border-top: none; }
        .suggestion-row:hover { background: var(--secondary-background-color, rgba(0, 0, 0, 0.04)); }
        .suggestion-row ha-icon { color: var(--state-icon-color, var(--primary-color)); flex-shrink: 0; }
        .row-text { min-width: 0; }
        .row-title { font-weight: 500; }
        .row-detail {
          font-size: 0.85em;
          color: var(--secondary-text-color);
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
      </style>
      <ha-card header="${escapeHtml(title)}">
        <div class="content">${body}</div>
      </ha-card>
    `;

    this.shadowRoot.querySelectorAll("[data-entity]").forEach((el) => {
      el.addEventListener("click", () => this._tap(el.dataset.entity));
    });
  }

  _rowHtml(state) {
    const targetState = this._hass.states[state.attributes.target_entity_id];
    const targetName = targetState ? targetState.attributes.friendly_name || targetState.entity_id : state.attributes.target_entity_id;
    const confidencePct = Math.round((state.attributes.confidence ?? 0) * 100);
    const reason = state.attributes.reason ? `${escapeHtml(state.attributes.reason)} · ` : "";
    return `
      <button class="suggestion-row" data-entity="${escapeHtml(state.entity_id)}">
        <ha-icon icon="mdi:lightbulb-on-outline"></ha-icon>
        <div class="row-text">
          <div class="row-title">${escapeHtml(targetName)}</div>
          <div class="row-detail">${reason}${confidencePct}% · ${escapeHtml(state.attributes.observations ?? 0)} Beobachtungen</div>
        </div>
      </button>
    `;
  }
}

customElements.define("action-suggestion-list-card", ActionSuggestionListCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "action-suggestion-list-card",
  name: "Action Suggestion – Vorschlagsliste",
  description: "Sammelt automatisch alle gerade aktiven Vorschläge der Action-Suggestion-Integration in einer Karte.",
  preview: false,
});
