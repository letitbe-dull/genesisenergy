// genesisenergy-powershout-card.js
// Genesis Energy — Power Shout Lovelace Card

const CARD_VERSION = "1.0.0";
const DOMAIN = "genesisenergy";

// ─── helpers ────────────────────────────────────────────────────────────────

function fmtHour(isoStr) {
  if (!isoStr) return "—";
  try {
    return new Date(isoStr)
      .toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
      .toLowerCase();
  } catch {
    return "—";
  }
}

function fmtNum(val, decimals = 2) {
  const n = parseFloat(val);
  return isNaN(n) ? null : n.toFixed(decimals);
}

function fmtDate(isoStr) {
  if (!isoStr) return null;
  const d = new Date(isoStr);
  return isNaN(d) ? null : d.toLocaleDateString([], { day: "numeric", month: "short" });
}

function buildStartOptions() {
  const now = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  const opts = [];
  for (let h = now.getHours(); h <= 23; h++) {
    const d = new Date(now.getFullYear(), now.getMonth(), now.getDate(), h);
    const label = d
      .toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
      .toLowerCase();
    const value = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(
      d.getDate()
    )} ${pad(h)}:00:00`;
    opts.push({ label, value });
  }
  return opts;
}

// ─── styles ─────────────────────────────────────────────────────────────────

const CARD_CSS = `
  @import url('https://fonts.googleapis.com/css2?family=Gabarito:wght@400;700;800&family=Figtree:wght@400;600;700&display=swap');

  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  :host { display: block; font-family: "Figtree", system-ui, sans-serif; -webkit-font-smoothing: antialiased; }

  /* ── flip container ── */
  .flip { position: relative; width: 100%; }

  .face {
    border-radius: 20px;
    background: var(--card-background-color, #fff);
    box-shadow: 0 1px 3px rgba(80,40,0,.06), 0 14px 44px rgba(90,50,10,.11);
    overflow: hidden;
    transition: opacity .35s ease, transform .5s cubic-bezier(.4,.15,.2,1);
  }
  @media (prefers-color-scheme: dark) {
    .face { box-shadow: 0 14px 44px rgba(0,0,0,.45); }
  }

  /* front — in normal flow, drives container height */
  .face.front { position: relative; opacity: 1; transform: rotateY(0deg); }
  /* back — overlaid, hidden until flipped */
  .face.back { position: absolute; inset: 0; opacity: 0; transform: rotateY(-180deg); pointer-events: none; }

  .flip.flipped .face.front { opacity: 0; transform: rotateY(180deg); pointer-events: none; }
  .flip.flipped .face.back  { opacity: 1; transform: rotateY(0deg);   pointer-events: auto; }

  @media (max-width: 440px) {
    .face.back { display: none; }
    .flip.flipped .face.front { opacity: 1; transform: none; pointer-events: auto; }
  }

  /* ── card shell ── */
  .card { display: flex; flex-direction: column; padding: 20px 22px 22px; color: var(--primary-text-color, #201a15); }

  /* ── hero ── */
  .hero { display: flex; align-items: center; gap: 12px; margin-top: 4px; }
  .hero img { width: 46px; height: 46px; display: block; flex: none; }
  .balwrap { display: flex; align-items: flex-end; gap: 7px; line-height: .85; }
  .balwrap .n { font-family: "Gabarito", system-ui, sans-serif; font-weight: 800; font-size: 76px; letter-spacing: -.03em; }
  .balwrap .u { font-family: "Gabarito", system-ui, sans-serif; font-weight: 700; font-size: 24px; color: var(--secondary-text-color, #8a8078); padding-bottom: 10px; }

  /* ── subline ── */
  .subline { display: flex; align-items: center; justify-content: space-between; margin-top: 10px; gap: 8px; }
  .subline .cap { font-size: 13px; color: var(--secondary-text-color, #8a8078); }
  .subline .cap b { color: var(--primary-text-color, #201a15); font-weight: 700; }
  .elig { flex: none; background: #fbe9d7; color: #b4531a; font-weight: 700; font-size: 12px; padding: 5px 12px; border-radius: 999px; white-space: nowrap; }
  @media (prefers-color-scheme: dark) { .elig { background: #3a2410; color: #f0a860; } }
  .elig.ok { background: #e3f4e4; color: #2e7d32; }
  @media (prefers-color-scheme: dark) { .elig.ok { background: #16331b; color: #7fd48a; } }

  /* ── live bar ── */
  .live { position: relative; overflow: hidden; margin: 16px -22px 0; padding: 13px 22px; color: #fff; display: flex; align-items: center; justify-content: space-between; background: #E24E1B; }
  .live[hidden] { display: none; }
  .live::before, .live::after { content: ""; position: absolute; inset: -70%; z-index: 0; filter: blur(5px); will-change: transform; }
  .live::before {
    background:
      radial-gradient(38% 150% at 20% 40%, #FFCE6E 0%, rgba(255,206,110,0) 55%),
      radial-gradient(34% 150% at 62% 55%, #C9350C 0%, rgba(201,53,12,0) 52%),
      radial-gradient(40% 150% at 90% 35%, #FF9A33 0%, rgba(255,154,51,0) 54%);
    animation: blobA 3.6s ease-in-out infinite alternate;
  }
  .live::after {
    background:
      radial-gradient(36% 150% at 45% 65%, #FFB347 0%, rgba(255,179,71,0) 54%),
      radial-gradient(32% 150% at 82% 42%, #B92E08 0%, rgba(185,46,8,0) 50%),
      radial-gradient(40% 150% at  8% 58%, #FFDD8C 0%, rgba(255,221,140,0) 55%);
    animation: blobB 4.8s ease-in-out infinite alternate;
  }
  @keyframes blobA { 0% { transform: translate(-16%,-8%) scale(1.15); } 100% { transform: translate(18%,8%) scale(1.6); } }
  @keyframes blobB { 0% { transform: translate(15%,7%) scale(1.5) rotate(0deg); } 100% { transform: translate(-18%,-7%) scale(1.1) rotate(6deg); } }
  @media (prefers-reduced-motion: reduce) { .live::before, .live::after { animation: none; } }
  .live .ll, .live .lr { position: relative; z-index: 1; text-shadow: 0 1px 3px rgba(120,40,0,.35); }
  .live .ll { font-weight: 700; font-size: 15px; display: flex; align-items: center; gap: 9px; }
  .live .dot { width: 9px; height: 9px; border-radius: 50%; background: #fff; }
  .live .lr { font-size: 13px; opacity: .94; }

  /* ── booking ── */
  .lbl { font-size: 11px; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; color: var(--secondary-text-color, #9a9088); margin: 18px 0 9px; }
  .seg { display: flex; gap: 7px; }
  .seg button { flex: 1; appearance: none; border: 0; cursor: pointer; font: inherit; font-weight: 700; padding: 12px 0; border-radius: 13px; font-size: 16px; background: #f4efe9; color: #5c534b; transition: transform .12s, background .15s, color .15s; }
  @media (prefers-color-scheme: dark) { .seg button { background: #26211c; color: #c7bcb0; } }
  .seg button:active { transform: scale(.95); }
  .seg button.sel { background: #201a15; color: #fff; }
  @media (prefers-color-scheme: dark) { .seg button.sel { background: #f0e9e2; color: #201a15; } }

  /* ── CTA — div so it can host the time <select> ── */
  .cta {
    display: flex; align-items: center; justify-content: center;
    cursor: pointer; font-family: inherit; font-size: 16px; font-weight: 700;
    width: 100%; padding: 15px 18px; border-radius: 14px;
    background: #F15B29; color: #fff;
    margin-top: 11px;
    transition: transform .12s, filter .15s;
    user-select: none;
  }
  .cta:hover { filter: brightness(1.06); }
  .cta:active { transform: scale(.985); }
  /* transparent select embedded in the button */
  .cta-sel {
    appearance: none; -webkit-appearance: none;
    background: transparent; border: 0;
    border-bottom: 1.5px solid rgba(255,255,255,.55);
    color: #fff; font: inherit; font-size: inherit; font-weight: 700;
    cursor: pointer; padding: 0 2px; outline: none; margin: 0 4px;
  }
  .cta-sel option { color: #201a15; background: #fff; }

  /* ── offer row ── */
  .offer { margin-top: 11px; border: 1.5px dashed #e7b483; background: #fff8f0; border-radius: 14px; padding: 12px 14px; display: flex; align-items: center; justify-content: space-between; gap: 10px; }
  .offer[hidden] { display: none; }
  @media (prefers-color-scheme: dark) { .offer { background: #241a10; border-color: #5a4222; } }
  .offer .ot { font-size: 14px; font-weight: 600; color: #7a4a1a; }
  @media (prefers-color-scheme: dark) { .offer .ot { color: #e0b184; } }
  .offer .ot b { color: #F15B29; }
  .offer .add-btn { flex: none; appearance: none; border: 0; cursor: pointer; font: inherit; font-weight: 700; font-size: 13px; background: #E8A13C; color: #3a2606; padding: 9px 14px; border-radius: 11px; white-space: nowrap; }

  /* ── forecast ── */
  .cost { padding-top: 16px; margin-top: 16px; border-top: 1px solid #efe9e2; display: flex; align-items: flex-end; justify-content: space-between; gap: 12px; }
  @media (prefers-color-scheme: dark) { .cost { border-color: #2a241e; } }
  .cost .big { font-family: "Gabarito", system-ui, sans-serif; font-weight: 800; font-size: 30px; letter-spacing: -.02em; }
  .cost .sub { font-size: 12px; color: var(--secondary-text-color, #9a9088); margin-top: 2px; }
  .toggle { flex: none; display: inline-flex; border-radius: 10px; overflow: hidden; background: #f4efe9; }
  @media (prefers-color-scheme: dark) { .toggle { background: #26211c; } }
  .toggle button { appearance: none; border: 0; cursor: pointer; font: inherit; font-weight: 700; font-size: 12px; padding: 7px 12px; color: var(--secondary-text-color, #8a8078); }
  .toggle button.sel { background: #201a15; color: #fff; }
  @media (prefers-color-scheme: dark) { .toggle button.sel { background: #f0e9e2; color: #201a15; } }

  /* ── footer ── */
  .footrow { display: flex; justify-content: space-between; align-items: center; margin-top: 11px; }
  .est { font-size: 13px; color: var(--secondary-text-color, #8a8078); }
  .est b { color: var(--primary-text-color, #201a15); font-weight: 700; }
  .flipbtn, .backbtn { appearance: none; border: 0; background: transparent; cursor: pointer; font: inherit; font-size: 12.5px; font-weight: 700; color: #b4531a; padding: 4px 0; }
  @media (prefers-color-scheme: dark) { .flipbtn, .backbtn { color: #f0a860; } }

  /* ── back face ── */
  .bhead { display: flex; align-items: center; gap: 10px; }
  .bhead img { width: 22px; height: 22px; }
  .bhead span { font-weight: 700; font-size: 12px; text-transform: uppercase; letter-spacing: .04em; color: #8a6b4a; }
  .back h3 { font-family: "Gabarito", system-ui, sans-serif; font-weight: 700; font-size: 18px; margin: 14px 0 6px; }
  .ubar { margin: 9px 0; }
  .ubar .t { display: flex; justify-content: space-between; font-size: 13px; font-weight: 600; margin-bottom: 5px; }
  .ubar .track { height: 8px; border-radius: 6px; overflow: hidden; background: #f1ece5; }
  @media (prefers-color-scheme: dark) { .ubar .track { background: #26211c; } }
  .ubar .fill { height: 100%; transition: width .4s ease; }
  .mini { display: flex; gap: 10px; margin-top: 16px; }
  .mini .box { flex: 1; background: #faf6f1; border-radius: 13px; padding: 12px; }
  @media (prefers-color-scheme: dark) { .mini .box { background: #1d1813; } }
  .mini .k { font-size: 11px; color: var(--secondary-text-color, #9a9088); font-weight: 700; text-transform: uppercase; letter-spacing: .03em; }
  .mini .v { font-family: "Gabarito", system-ui, sans-serif; font-weight: 800; font-size: 20px; margin-top: 4px; }
  .backfoot { margin-top: 20px; display: flex; justify-content: center; }
`;

// ─── HTML template ───────────────────────────────────────────────────────────

function buildTemplate(logoUrl) {
  const opts = buildStartOptions()
    .map((o) => `<option value="${o.value}">${o.label}</option>`)
    .join("");

  return `
    <style>${CARD_CSS}</style>
    <div class="flip" id="flip">

      <!-- FRONT -->
      <div class="face front"><div class="card">
        <div class="hero">
          <img src="${logoUrl}" alt="Power Shout">
          <div class="balwrap">
            <span class="n" id="bal-num">—</span>
            <span class="u">hr</span>
          </div>
        </div>

        <div class="subline">
          <span class="cap" id="bill-balance-cap">Bill balance</span>
          <span class="elig" id="bill-due-pill" style="display:none">Due —</span>
        </div>

        <div class="live" id="live-bar" hidden>
          <span class="ll"><span class="dot"></span>Free power now</span>
          <span class="lr" id="live-end">—</span>
        </div>

        <div class="lbl">Book a shout · duration</div>
        <div class="seg" id="dur-seg">
          <button data-dur="1">1</button>
          <button data-dur="2" class="sel">2</button>
          <button data-dur="3">3</button>
          <button data-dur="4">4</button>
        </div>

        <div class="cta" id="book-cta" role="button" tabindex="0">
          Book from&nbsp;<select id="start-sel" class="cta-sel">${opts}</select>&nbsp;→
        </div>

        <div class="offer" id="offer-row" hidden>
          <span class="ot" id="offer-lbl"><b>—</b> offer for you</span>
          <button class="add-btn" id="offer-btn">Add to balance</button>
        </div>

        <div class="cost">
          <div>
            <div class="big" id="cost-val">—</div>
            <div class="sub" id="cost-sub">forecast today</div>
          </div>
          <div class="toggle" id="unit-toggle">
            <button class="sel" data-unit="money">$</button>
            <button data-unit="kwh">kWh</button>
          </div>
        </div>

        <div class="footrow">
          <span class="est" id="est-bill">Est. bill <b>—</b> this period</span>
          <button class="flipbtn" id="flip-btn">More usage ↻</button>
        </div>
      </div></div>

      <!-- BACK -->
      <div class="face back"><div class="card">
        <div class="bhead">
          <img src="${logoUrl}" alt="">
          <span>Last billing period</span>
        </div>
        <h3>Where it's going</h3>

        <div class="ubar">
          <div class="t"><span>Appliances</span><span id="bar-appliances-lbl">—</span></div>
          <div class="track"><div class="fill" id="bar-appliances" style="width:0%;background:#F15B29"></div></div>
        </div>
        <div class="ubar">
          <div class="t"><span>Electronics</span><span id="bar-electronics-lbl">—</span></div>
          <div class="track"><div class="fill" id="bar-electronics" style="width:0%;background:#F68D23"></div></div>
        </div>
        <div class="ubar">
          <div class="t"><span>Lighting</span><span id="bar-lighting-lbl">—</span></div>
          <div class="track"><div class="fill" id="bar-lighting" style="width:0%;background:#E8A13C"></div></div>
        </div>
        <div class="ubar">
          <div class="t"><span>Heating</span><span id="bar-heating-lbl">—</span></div>
          <div class="track"><div class="fill" id="bar-heating" style="width:0%;background:#C9350C"></div></div>
        </div>
        <div class="ubar">
          <div class="t"><span>Hot Water</span><span id="bar-hot_water-lbl">—</span></div>
          <div class="track"><div class="fill" id="bar-hot_water" style="width:0%;background:#FF9A33"></div></div>
        </div>
        <div class="ubar">
          <div class="t"><span>Other</span><span id="bar-other-lbl">—</span></div>
          <div class="track"><div class="fill" id="bar-other" style="width:0%;background:#d9b48a"></div></div>
        </div>

        <div class="mini">
          <div class="box" id="ev-box" style="display:none">
            <div class="k">EV savings</div>
            <div class="v" id="ev-val">—</div>
          </div>
        </div>

        <div class="backfoot">
          <button class="backbtn" id="back-btn">↺ Back to Power Shout</button>
        </div>
      </div></div>

    </div>`;
}

// ─── card element ────────────────────────────────────────────────────────────

class GenesisPowerShoutCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._hass = null;
    this._unit = "money";
    this._selectedDuration = 2;
    this._offerId = null;
    this._built = false;
    this._lastStartHour = -1;
    this._entities = null;
  }

  setConfig(config) {
    this._config = config;
  }

  getCardSize() {
    return 5;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._built) this._build();
    this._update();
  }

  // ─── entity discovery ────────────────────────────────────────────────────
  //
  // Prefers explicit config keys. Falls back to scanning hass.states for any
  // sensor ending in _power_shout_balance, then derives all other IDs from
  // the same device slug. Works with zero YAML config for single-account setups.

  _resolveEntities() {
    let prefix;

    if (this._config.entity_balance) {
      // Strip platform prefix and entity suffix to get the device slug
      prefix = this._config.entity_balance
        .replace(/^sensor\./, "")
        .replace(/_power_shout_balance$/, "");
    } else {
      // Auto-discover: find the balance sensor in hass.states
      const balId = Object.keys(this._hass.states).find(
        (id) =>
          id.startsWith("sensor.") && id.endsWith("_power_shout_balance")
      );
      if (!balId) return null;
      prefix = balId.replace(/^sensor\./, "").replace(/_power_shout_balance$/, "");
    }

    // Merge auto-derived IDs with any explicit overrides from config
    return {
      entity_balance:               `sensor.${prefix}_power_shout_balance`,
      entity_bill_balance:          `sensor.${prefix}_bill_balance`,
      entity_bill_due_date:         `sensor.${prefix}_bill_due_date`,
      entity_booking_in_progress:   `binary_sensor.${prefix}_power_shout_booking_in_progress`,
      entity_booking_upcoming:      `binary_sensor.${prefix}_power_shout_booking_upcoming`,
      entity_offers_available:      `binary_sensor.${prefix}_power_shout_offers_available`,
      entity_forecast_cost:         `sensor.${prefix}_today_s_forecast_cost`,
      entity_forecast_usage:        `sensor.${prefix}_today_s_forecast_usage`,
      entity_estimated_bill:        `sensor.${prefix}_genesis_bill_estimated_total`,
      entity_generation_mix:        `sensor.${prefix}_grid_generation_eco_friendly`,
      entity_ev_savings:            `sensor.${prefix}_ev_plan_savings`,
      entity_breakdown_appliances:  `sensor.${prefix}_usage_breakdown_appliances`,
      entity_breakdown_electronics: `sensor.${prefix}_usage_breakdown_electronics`,
      entity_breakdown_lighting:    `sensor.${prefix}_usage_breakdown_lighting`,
      entity_breakdown_heating:     `sensor.${prefix}_usage_breakdown_heating`,
      entity_breakdown_hot_water:   `sensor.${prefix}_usage_breakdown_hot_water`,
      entity_breakdown_other:       `sensor.${prefix}_usage_breakdown_other`,
      ...this._config, // explicit keys in YAML override the derived ones
    };
  }

  // ─── DOM setup (once) ────────────────────────────────────────────────────

  _build() {
    const logoUrl = new URL("./powershout.png", import.meta.url).href;
    this.shadowRoot.innerHTML = buildTemplate(logoUrl);
    this._built = true;
    this._wireListeners();
  }

  _el(id) {
    return this.shadowRoot.getElementById(id);
  }

  _wireListeners() {
    this._el("flip-btn").addEventListener("click", () =>
      this._el("flip").classList.toggle("flipped")
    );
    this._el("back-btn").addEventListener("click", () =>
      this._el("flip").classList.remove("flipped")
    );

    this.shadowRoot.querySelectorAll("#dur-seg button").forEach((btn) => {
      btn.addEventListener("click", () => {
        this.shadowRoot
          .querySelectorAll("#dur-seg button")
          .forEach((b) => b.classList.remove("sel"));
        btn.classList.add("sel");
        this._selectedDuration = parseInt(btn.dataset.dur, 10);
      });
    });

    this.shadowRoot.querySelectorAll("#unit-toggle button").forEach((btn) => {
      btn.addEventListener("click", () => {
        this.shadowRoot
          .querySelectorAll("#unit-toggle button")
          .forEach((b) => b.classList.remove("sel"));
        btn.classList.add("sel");
        this._unit = btn.dataset.unit;
        this._updateForecast();
      });
    });

    // Book: click the div but not the select inside it
    this._el("book-cta").addEventListener("click", (e) => {
      if (e.target.id === "start-sel") return;
      this._book();
    });
    this._el("book-cta").addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") this._book();
    });

    this._el("offer-btn").addEventListener("click", () => this._acceptOffer());
  }

  // ─── service calls ───────────────────────────────────────────────────────

  _book() {
    if (!this._hass) return;
    const startVal = this._el("start-sel").value;
    if (!startVal) return;
    this._hass.callService(DOMAIN, "add_powershout_booking", {
      start_datetime: startVal,
      duration_hours: this._selectedDuration,
    });
  }

  _acceptOffer() {
    if (!this._hass || !this._offerId) return;
    this._hass.callService(DOMAIN, "accept_powershout_offer", {
      offer_id: this._offerId,
    });
  }

  // ─── data update ─────────────────────────────────────────────────────────

  _update() {
    if (!this._built || !this._hass) return;
    this._entities = this._resolveEntities();
    if (!this._entities) return; // integration not yet loaded
    this._refreshStartOptions();
    this._updateBalance();
    this._updateLiveBar();
    this._updateOffer();
    this._updateForecast();
    this._updateEstBill();
    this._updateBreakdown();
    this._updateEcoEV();
  }

  _refreshStartOptions() {
    const hour = new Date().getHours();
    if (hour === this._lastStartHour) return;
    this._lastStartHour = hour;
    const sel = this._el("start-sel");
    const prev = sel.value;
    sel.innerHTML = buildStartOptions()
      .map((o) => `<option value="${o.value}">${o.label}</option>`)
      .join("");
    if (Array.from(sel.options).some((o) => o.value === prev)) sel.value = prev;
  }

  _st(key) {
    const id = this._entities?.[key];
    return id ? this._hass.states[id] : null;
  }

  _updateBalance() {
    const st = this._st("entity_balance");
    const num = st ? parseFloat(st.state) : null;
    this._el("bal-num").textContent =
      num != null && !isNaN(num) ? num : "—";

    // Bill balance
    const bal = fmtNum(this._st("entity_bill_balance")?.state, 2);
    this._el("bill-balance-cap").innerHTML =
      bal != null ? `Bill balance · <b>$${bal}</b>` : "Bill balance";

    // Bill due date — green before the due date, red on/after it
    const dueStr = this._st("entity_bill_due_date")?.state;
    const due = fmtDate(dueStr);
    const pill = this._el("bill-due-pill");
    if (due) {
      pill.textContent = `Due ${due}`;
      pill.style.display = "";
      const dueDate = new Date(dueStr);
      const today = new Date();
      dueDate.setHours(0, 0, 0, 0);
      today.setHours(0, 0, 0, 0);
      pill.classList.toggle("ok", !isNaN(dueDate) && today < dueDate);
    } else {
      pill.style.display = "none";
    }
  }

  _updateLiveBar() {
    const st = this._st("entity_booking_in_progress");
    const on = st?.state === "on";
    const bar = this._el("live-bar");
    if (on) {
      bar.removeAttribute("hidden");
      const b = st?.attributes?.current_booking;
      if (b?.startDateTime) {
        const end = new Date(
          new Date(b.startDateTime).getTime() +
            parseFloat(b.duration || 1) * 3600000
        );
        this._el("live-end").textContent = `ends ${fmtHour(end.toISOString())}`;
      }
    } else {
      bar.setAttribute("hidden", "");
    }
  }

  _updateOffer() {
    const row = this._el("offer-row");
    if (this._st("entity_offers_available")?.state !== "on") {
      row.setAttribute("hidden", "");
      this._offerId = null;
      return;
    }
    const offers = this._st("entity_balance")?.attributes?.active_offers;
    if (!offers?.length) {
      row.setAttribute("hidden", "");
      this._offerId = null;
      return;
    }
    const offer = offers[0];
    const hrs = offer?.loyaltyOffer?.amount ?? "?";
    this._offerId = offer?.loyaltyOffer?.guid ?? null;
    this._el("offer-lbl").innerHTML = `<b>+${hrs} hr</b> offer for you`;
    row.removeAttribute("hidden");
  }

  _updateForecast() {
    if (this._unit === "money") {
      const st = this._st("entity_forecast_cost");
      const val = fmtNum(st?.state, 2);
      const lo = fmtNum(st?.attributes?.prediction_low_cost, 2);
      const hi = fmtNum(st?.attributes?.prediction_high_cost, 2);
      this._el("cost-val").textContent = val != null ? `$${val}` : "—";
      this._el("cost-sub").textContent =
        lo != null && hi != null
          ? `forecast today · $${lo}–$${hi}`
          : "forecast today";
    } else {
      const st = this._st("entity_forecast_usage");
      const val = fmtNum(st?.state, 1);
      const lo = fmtNum(st?.attributes?.prediction_low_kwh, 0);
      const hi = fmtNum(st?.attributes?.prediction_high_kwh, 0);
      this._el("cost-val").textContent = val != null ? `${val} kWh` : "—";
      this._el("cost-sub").textContent =
        lo != null && hi != null
          ? `forecast today · ${lo}–${hi} kWh`
          : "forecast today";
    }
  }

  _updateEstBill() {
    const val = fmtNum(this._st("entity_estimated_bill")?.state, 0);
    this._el("est-bill").innerHTML = `Est. bill <b>${
      val != null ? `$${val}` : "—"
    }</b> this period`;
  }

  _updateBreakdown() {
    const bars = [
      { key: "appliances",  cfg: "entity_breakdown_appliances",  color: "#F15B29" },
      { key: "electronics", cfg: "entity_breakdown_electronics", color: "#F68D23" },
      { key: "lighting",    cfg: "entity_breakdown_lighting",    color: "#E8A13C" },
      { key: "heating",     cfg: "entity_breakdown_heating",     color: "#C9350C" },
      { key: "hot_water",   cfg: "entity_breakdown_hot_water",   color: "#FF9A33" },
      { key: "other",       cfg: "entity_breakdown_other",       color: "#d9b48a" },
    ];
    for (const bar of bars) {
      const st = this._st(bar.cfg);
      const kwh = fmtNum(st?.state, 0);
      const pct = st?.attributes?.percentage ?? null;
      this._el(`bar-${bar.key}-lbl`).textContent =
        kwh != null && pct != null ? `${kwh} kWh · ${pct}%` : "—";
      this._el(`bar-${bar.key}`).style.width = pct != null ? `${pct}%` : "0%";
    }
  }

  _updateEcoEV() {
    const ev = fmtNum(this._st("entity_ev_savings")?.state, 2);
    const box = this._el("ev-box");
    if (ev != null) {
      this._el("ev-val").textContent = `$${ev}`;
      box.style.display = "";
    } else {
      box.style.display = "none";
    }
  }
}

customElements.define("genesisenergy-powershout-card", GenesisPowerShoutCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "genesisenergy-powershout-card",
  name: "Genesis Energy — Power Shout",
  description:
    "Power Shout balance, live booking bar, duration booking, offers, forecast, and usage breakdown. Auto-discovers entities — no config needed.",
  preview: false,
});

console.info(
  `%c GENESISENERGY-POWERSHOUT-CARD %c v${CARD_VERSION} `,
  "color:#fff;background:#F15B29;font-weight:700;padding:2px 4px;",
  "color:#F15B29;background:#fff;font-weight:700;padding:2px 4px;"
);
