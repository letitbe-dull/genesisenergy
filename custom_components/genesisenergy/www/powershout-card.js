// genesisenergy-powershout-card.js
// Genesis Energy — Power Shout Lovelace Card

const CARD_VERSION = "1.2.0";
const DOMAIN = "genesisenergy";

const PAST_ERRORS = {
  setup_unavailable: "Genesis could not confirm which past hours you can redeem.",
  recommendations_unavailable: "Genesis could not load past hours just now.",
  recommendations_invalid: "Genesis sent past-hour data we could not read.",
  property_identifiers_missing: "This property is missing details Genesis needs.",
  recommendation_balance_invalid: "Genesis did not send the vouchers for your hours.",
};

const TAB_SHOUT = "shout";
const TAB_PAST = "past";
const TAB_USAGE = "usage";

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

function fmtPastHour(isoStr) {
  if (!isoStr) return "Unknown hour";
  const parsed = new Date(isoStr);
  if (isNaN(parsed)) return isoStr.replace("T", " ");
  return parsed.toLocaleString([], {
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "numeric",
    minute: "2-digit",
  });
}

function fmtWindow(isoStr) {
  if (!isoStr) return null;
  const d = new Date(`${isoStr}T00:00:00`);
  return isNaN(d) ? null : d.toLocaleDateString([], { day: "numeric", month: "short" });
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function buildPastHourOptions() {
  return Array.from({ length: 24 }, (_, hour) => {
    const value = String(hour).padStart(2, "0");
    const date = new Date(2000, 0, 1, hour);
    const label = date
      .toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
      .toLowerCase();
    return `<option value="${value}">${label}</option>`;
  }).join("");
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

// Genesis returns naive local timestamps; keep them naive so the hour is stable.
function endHourLabel(startDatetime, duration) {
  const parsed = new Date(startDatetime);
  if (isNaN(parsed)) return "";
  const end = new Date(parsed.getTime() + Math.max(1, Number(duration) || 1) * 3600000);
  return end
    .toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
    .toLowerCase();
}

function bookingId(booking) {
  return booking?.id ?? null;
}

// Font faces are registered on the document, not in the shadow root, so the
// browser resolves them for every instance of the card.
function ensureFonts(base) {
  const id = "genesisenergy-powershout-fonts";
  if (document.getElementById(id)) return;
  const style = document.createElement("style");
  style.id = id;
  style.textContent = `
    @font-face {
      font-family: "PP Neue Montreal";
      src: url("${base}fonts/PPNeueMontreal-Variable.woff2") format("woff2");
      font-weight: 200 700;
      font-style: normal;
      font-display: swap;
    }
    @font-face {
      font-family: "PP Nikkei Maru";
      src: url("${base}fonts/PPNikkeiMaru-Variable.woff2") format("woff2");
      font-weight: 300 800;
      font-style: normal;
      font-display: swap;
    }
  `;
  document.head.appendChild(style);
}

// ─── styles ─────────────────────────────────────────────────────────────────

const CARD_CSS = `
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  :host {
    --genesis-orange: #f15b29;
    --genesis-plum: #b4531a;
    --genesis-ink: #201a15;
    --genesis-peach: #fbe9d7;
    --genesis-yellow: #e8a13c;
    --genesis-font-primary: "PP Neue Montreal", system-ui, sans-serif;
    --genesis-font-display: "PP Nikkei Maru", "PP Neue Montreal", system-ui, sans-serif;
    --genesis-surface: var(--card-background-color, #fff);
    --genesis-muted: var(--secondary-text-color, #8a8078);
    --genesis-rule: #efe9e2;
    --genesis-well: #faf6f1;
    --genesis-track: #f4efe9;
    display: block;
    font-family: var(--genesis-font-primary);
    -webkit-font-smoothing: antialiased;
  }
  @media (prefers-color-scheme: dark) {
    :host {
      --genesis-rule: #2a241e;
      --genesis-well: #1d1813;
      --genesis-track: #26211c;
    }
  }
  [hidden] { display: none !important; }

  .card {
    border-radius: 20px;
    background: var(--genesis-surface);
    box-shadow: 0 1px 3px rgba(80,40,0,.06), 0 14px 44px rgba(90,50,10,.11);
    color: var(--primary-text-color, var(--genesis-ink));
    overflow: hidden;
    padding: 18px;
  }
  @media (prefers-color-scheme: dark) {
    .card { box-shadow: 0 14px 44px rgba(0,0,0,.45); }
  }

  /* ── hero ── */
  /* Baseline, not centre: an image's baseline is its bottom edge, so the mark
     sits on the same line as the digits instead of floating against the row. */
  .hero { align-items: baseline; display: flex; gap: 12px; }
  .hero img { flex: none; height: 44px; width: auto; }
  .balwrap { align-items: baseline; display: flex; gap: 5px; }
  .balwrap .n { font-family: var(--genesis-font-display); font-size: 52px; font-weight: 800; letter-spacing: -.045em; line-height: .9; }
  .balwrap .u { color: var(--genesis-muted); font-size: 17px; font-weight: 700; }

  .subline { align-items: center; display: flex; gap: 10px; justify-content: space-between; margin-top: 12px; }
  .cap { color: var(--genesis-muted); font-size: 13px; }
  .cap b { color: var(--primary-text-color, var(--genesis-ink)); font-weight: 700; }
  .elig { background: var(--genesis-peach); border-radius: 999px; color: var(--genesis-plum); font-size: 11px; font-weight: 800; letter-spacing: .05em; padding: 5px 11px; text-transform: uppercase; white-space: nowrap; }
  .elig.ok { background: #e7f5e8; color: #245c2a; }
  .elig.bad { background: #fde4dc; color: #8f2f14; }
  @media (prefers-color-scheme: dark) {
    .elig { background: #3a2017; color: #ffb28c; }
    .elig.ok { background: #17331d; color: #9ad8a1; }
    .elig.bad { background: #4a1a10; color: #ff9d7d; }
  }

  /* ── live bar ── */
  .live { align-items: center; background: var(--genesis-orange); border-radius: 12px; color: #fff; display: flex; font-size: 13px; font-weight: 700; justify-content: space-between; margin-top: 12px; padding: 10px 12px; }
  .live .ll { align-items: center; display: flex; gap: 7px; }
  .live .dot { animation: pulse 1.8s ease-in-out infinite; background: #fff; border-radius: 50%; height: 8px; width: 8px; }
  @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: .35; } }
  @media (prefers-reduced-motion: reduce) { .live .dot { animation: none; } }

  /* ── tabs ── */
  .tabs { border-bottom: 1px solid var(--genesis-rule); display: flex; gap: 2px; margin: 16px -18px 0; padding: 0 12px; }
  .tabs button {
    align-items: center; appearance: none; background: none; border: 0;
    border-bottom: 2.5px solid transparent; color: var(--genesis-muted); cursor: pointer;
    display: inline-flex; font: inherit; font-size: 13.5px; font-weight: 700; gap: 6px;
    margin-bottom: -1px; padding: 11px 10px;
  }
  .tabs button[aria-selected="true"] { border-bottom-color: var(--genesis-orange); color: var(--primary-text-color, var(--genesis-ink)); }
  .tabs .cnt { background: var(--genesis-orange); border-radius: 999px; color: #fff; font-size: 10px; font-weight: 800; line-height: 1; padding: 3px 5px; }
  .panel { padding-top: 4px; }

  /* ── labels & duration ── */
  .lbl { color: var(--genesis-muted); font-size: 11px; font-weight: 700; letter-spacing: .07em; margin: 18px 0 8px; text-transform: uppercase; }
  .seg { display: flex; gap: 8px; }
  .seg button { appearance: none; background: var(--genesis-track); border: 0; border-radius: 13px; color: var(--genesis-muted); cursor: pointer; flex: 1; font: inherit; font-size: 17px; font-weight: 700; padding: 15px 0; }
  .seg button.sel { background: var(--genesis-ink); color: #fff; }
  @media (prefers-color-scheme: dark) { .seg button.sel { background: #f0e9e2; color: var(--genesis-ink); } }

  .cta {
    align-items: center; background: var(--genesis-orange); border-radius: 15px; color: #fff;
    cursor: pointer; display: flex; font-size: 17px; font-weight: 700; gap: 4px;
    justify-content: center; margin-top: 12px; padding: 17px 14px;
  }
  .cta:hover { filter: brightness(1.06); }
  .cta:active { transform: scale(.985); }
  .cta-sel {
    appearance: none; -webkit-appearance: none;
    background: transparent; border: 0;
    border-bottom: 1.5px solid rgba(255,255,255,.55);
    color: #fff; font: inherit; font-size: inherit; font-weight: 700;
    cursor: pointer; padding: 0 2px; outline: none; margin: 0 4px;
  }
  .cta-sel option { color: var(--genesis-ink); background: #fff; }

  /* ── offer row ── */
  .offer { align-items: center; background: #fff8f0; border: 1.5px dashed #e7b483; border-radius: 14px; display: flex; gap: 10px; justify-content: space-between; margin-top: 11px; padding: 12px 14px; }
  @media (prefers-color-scheme: dark) { .offer { background: #241a10; border-color: #5a4222; } }
  .offer .ot { color: #7a4a1a; font-size: 14px; font-weight: 600; }
  @media (prefers-color-scheme: dark) { .offer .ot { color: #e0b184; } }
  .offer .ot b { color: var(--genesis-orange); }
  .offer .add-btn { appearance: none; background: var(--genesis-yellow); border: 0; border-radius: 11px; color: #3a2606; cursor: pointer; flex: none; font: inherit; font-size: 13px; font-weight: 700; padding: 9px 14px; white-space: nowrap; }

  /* ── expiring nudge ── */
  .nudge { background: #fff4e6; border-radius: 11px; color: #7a4a1a; font-size: 12.5px; line-height: 1.45; margin-top: 12px; padding: 10px 12px; }
  @media (prefers-color-scheme: dark) { .nudge { background: #2d2011; color: #e6b684; } }

  /* ── booked shouts ── */
  .bk { align-items: center; border-top: 1px solid var(--genesis-rule); display: flex; gap: 10px; padding: 11px 0; }
  .bk:first-of-type { border-top: 0; }
  .bk .w { flex: 1; font-size: 13.5px; font-weight: 600; }
  .bk .w small { color: var(--genesis-muted); display: block; font-size: 11.5px; font-weight: 400; margin-top: 2px; }
  .bk button { appearance: none; background: none; border: 0; color: var(--genesis-muted); cursor: pointer; font: inherit; font-size: 12px; font-weight: 700; padding: 5px 3px; }
  .bk button:hover { color: var(--genesis-orange); }
  .bk button:disabled { cursor: not-allowed; opacity: .5; }
  .bk.busy { opacity: .55; }
  .bk.busy button { color: var(--genesis-orange); opacity: 1; }
  .cta.busy { cursor: progress; filter: saturate(.75); }
  .empty { color: var(--genesis-muted); font-size: 13px; padding: 4px 0 2px; }

  /* ── forecast ── */
  .cost { align-items: flex-end; border-top: 1px solid var(--genesis-rule); display: flex; gap: 12px; justify-content: space-between; margin-top: 16px; padding-top: 16px; }
  .cost .big { font-family: var(--genesis-font-display); font-size: 30px; font-weight: 800; letter-spacing: -.02em; }
  .cost .sub { color: var(--genesis-muted); font-size: 12px; margin-top: 2px; }
  .toggle { background: var(--genesis-track); border-radius: 10px; display: inline-flex; flex: none; overflow: hidden; }
  .toggle button { appearance: none; background: none; border: 0; color: var(--genesis-muted); cursor: pointer; font: inherit; font-size: 12px; font-weight: 700; padding: 7px 12px; }
  .toggle button.sel { background: var(--genesis-ink); color: #fff; }
  @media (prefers-color-scheme: dark) { .toggle button.sel { background: #f0e9e2; color: var(--genesis-ink); } }

  .footrow { align-items: center; display: flex; justify-content: space-between; margin-top: 11px; }
  .est { color: var(--genesis-muted); font-size: 13px; }
  .est b { color: var(--primary-text-color, var(--genesis-ink)); font-weight: 700; }

  /* ── past hours ── */
  .prop { background: var(--genesis-surface); border: 1px solid var(--divider-color, #d7cdd3); border-radius: 10px; color: var(--primary-text-color, var(--genesis-ink)); font: inherit; font-size: 13px; margin-top: 14px; padding: 9px; width: 100%; }

  .ranked-scroll { max-height: 296px; overflow-y: auto; overscroll-behavior: contain; scrollbar-width: thin; }
  .ranked-scroll::-webkit-scrollbar { width: 6px; }
  .ranked-scroll::-webkit-scrollbar-thumb { background: var(--genesis-track); border-radius: 3px; }
  .row { align-items: center; border-top: 1px solid var(--genesis-rule); display: flex; gap: 11px; padding: 11px 0; }
  .row:first-of-type { border-top: 0; }
  .row input { accent-color: var(--genesis-orange); flex: none; height: 18px; margin: 0; width: 18px; }
  .row label { cursor: pointer; flex: 1; }
  .row .when { display: block; font-size: 14px; font-weight: 600; }
  .row small { color: var(--genesis-muted); display: block; font-size: 12px; margin-top: 1px; }
  .row small b { color: #245c2a; font-weight: 800; }
  @media (prefers-color-scheme: dark) { .row small b { color: #9ad8a1; } }
  .rank { border-radius: 6px; color: #fff; flex: none; font-size: 10px; font-weight: 800; letter-spacing: .05em; padding: 3px 6px; text-transform: uppercase; white-space: nowrap; }
  .rank.best { background: #005f60; }
  .rank.genesis { background: #60005f; }

  .selection-help { color: var(--genesis-muted); font-size: 12px; margin-top: 9px; }
  .wide-btn { appearance: none; background: var(--genesis-orange); border: 0; border-radius: 12px; color: #fff; cursor: pointer; font: inherit; font-size: 15px; font-weight: 700; margin-top: 11px; padding: 14px; width: 100%; }
  .wide-btn.ghost { background: rgba(71,45,62,.09); color: var(--primary-text-color, var(--genesis-ink)); }
  @media (prefers-color-scheme: dark) { .wide-btn.ghost { background: rgba(255,255,255,.12); } }
  .wide-btn:disabled { cursor: not-allowed; opacity: .55; }

  .btn-row { display: flex; gap: 8px; }
  .btn-row .wide-btn { flex: 1; min-width: 0; }
  .dialog .manual { margin-top: 14px; }
  .manual { display: grid; gap: 9px; grid-template-columns: 1.4fr 1fr .8fr; margin-top: 10px; }
  .manual label { color: var(--genesis-muted); font-size: 11px; font-weight: 700; }
  .manual input, .manual select { background: var(--genesis-surface); border: 1px solid var(--divider-color, #d7cdd3); border-radius: 8px; color: var(--primary-text-color, var(--genesis-ink)); font: inherit; font-size: 13px; margin-top: 4px; padding: 8px; width: 100%; }
  @media (max-width: 440px) {
    .manual { grid-template-columns: 1fr 1fr; }
    .manual label:first-child { grid-column: 1 / -1; }
  }

  .result { border-radius: 12px; font-size: 13px; line-height: 1.45; margin-top: 12px; padding: 11px 12px; }
  .result.ok { background: #e7f5e8; color: #245c2a; }
  .result.bad { background: #fff0e6; color: #75330f; }
  .result ul { margin: 6px 0 0 18px; }
  @media (prefers-color-scheme: dark) {
    .result.ok { background: #17331d; color: #9ad8a1; }
    .result.bad { background: #3a2017; color: #ffb28c; }
  }
  .panel-actions { align-items: center; display: flex; flex-wrap: wrap; gap: 8px; margin-top: 11px; }
  .panel-actions button { appearance: none; background: var(--genesis-orange); border: 0; border-radius: 10px; color: #fff; cursor: pointer; font: inherit; font-size: 13px; font-weight: 700; padding: 9px 12px; }

  /* ── usage ── */
  .usage-head { color: #8a6b4a; font-size: 12px; font-weight: 700; letter-spacing: .04em; margin-top: 16px; text-transform: uppercase; }
  .usage-title { font-family: var(--genesis-font-display); font-size: 18px; font-weight: 800; margin: 5px 0 10px; }
  .ubar { margin: 9px 0; }
  .ubar .t { display: flex; font-size: 13px; font-weight: 600; justify-content: space-between; margin-bottom: 5px; }
  .ubar .track { background: var(--genesis-track); border-radius: 6px; height: 8px; overflow: hidden; }
  .ubar .fill { height: 100%; transition: width .4s ease; }
  @media (prefers-reduced-motion: reduce) { .ubar .fill { transition: none; } }
  .mini { display: flex; gap: 10px; margin-top: 16px; }
  .mini .box { background: var(--genesis-well); border-radius: 13px; flex: 1; padding: 12px; }
  .mini .k { color: var(--genesis-muted); font-size: 11px; font-weight: 700; letter-spacing: .03em; text-transform: uppercase; }
  .mini .v { font-family: var(--genesis-font-display); font-size: 20px; font-weight: 800; margin-top: 4px; }

  /* ── confirmation ── */
  .modal { align-items: center; background: rgba(24,12,21,.58); display: flex; inset: 0; justify-content: center; padding: 18px; position: fixed; z-index: 10; }
  .dialog { background: var(--genesis-surface); border-radius: 18px; box-shadow: 0 24px 80px rgba(0,0,0,.32); color: var(--primary-text-color, var(--genesis-ink)); max-width: 390px; padding: 20px; width: 100%; }
  .dialog h3 { font-family: var(--genesis-font-display); font-size: 22px; font-weight: 800; }
  .dialog .property { color: var(--genesis-plum); font-size: 13px; font-weight: 700; margin-top: 5px; }
  .dialog ul { font-size: 14px; line-height: 1.45; margin: 14px 0 0 19px; }
  .dialog .warning { background: var(--genesis-peach); border-radius: 10px; color: var(--genesis-ink); font-size: 12px; line-height: 1.45; margin-top: 14px; padding: 10px; }
  .dialog-actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 14px; }
  .dialog button { appearance: none; border: 0; border-radius: 10px; cursor: pointer; font: inherit; font-size: 13px; font-weight: 700; padding: 9px 12px; }
  .primary { background: var(--genesis-orange); color: #fff; }
  .secondary { background: rgba(71,45,62,.1); color: var(--genesis-ink); }
  @media (prefers-color-scheme: dark) { .secondary { background: rgba(255,255,255,.12); color: #fff; } }
  button:disabled { cursor: not-allowed; opacity: .55; }

  .spin {
    animation: spin .7s linear infinite;
    border: 2px solid currentColor; border-radius: 50%; border-right-color: transparent;
    display: inline-block; height: 13px; margin-right: 7px; vertical-align: -2px; width: 13px;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  @media (prefers-reduced-motion: reduce) { .spin { animation-duration: 2.4s; } }

  :where(button, input, select):focus-visible { outline: 2px solid var(--genesis-orange); outline-offset: 2px; }
`;

// ─── HTML template ───────────────────────────────────────────────────────────

function buildTemplate(logoUrl) {
  const opts = buildStartOptions()
    .map((o) => `<option value="${o.value}">${o.label}</option>`)
    .join("");
  const pastHours = buildPastHourOptions();

  return `
    <style>${CARD_CSS}</style>
    <div class="card">

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

      <div class="tabs" role="tablist">
        <button role="tab" id="tab-shout" data-tab="${TAB_SHOUT}" aria-selected="true">Shout</button>
        <button role="tab" id="tab-past" data-tab="${TAB_PAST}" aria-selected="false" hidden>
          Past hours <span class="cnt" id="past-count" hidden>0</span>
        </button>
        <button role="tab" id="tab-usage" data-tab="${TAB_USAGE}" aria-selected="false">Usage</button>
      </div>

      <!-- ── SHOUT ── -->
      <div class="panel" id="panel-${TAB_SHOUT}" role="tabpanel">
        <div class="lbl">Duration</div>
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

        <div class="nudge" id="expiring-note" hidden></div>

        <div class="lbl" id="booked-lbl">Booked</div>
        <div id="booking-list"></div>

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
        </div>
      </div>

      <!-- ── PAST HOURS ── -->
      <div class="panel" id="panel-${TAB_PAST}" role="tabpanel" hidden>
        <select class="prop" id="site-sel" hidden></select>

        <div class="nudge" id="past-notice" hidden></div>

        <div id="past-body">
        <div class="lbl">Ranked by what you get back</div>
        <div class="ranked-scroll"><div id="ranked-list"></div></div>
        <div class="selection-help" id="selection-help"></div>
        <div class="btn-row">
          <button class="wide-btn" id="redeem-selected" disabled>Redeem selected</button>
          <button class="wide-btn ghost" id="manual-open">Any hour…</button>
        </div>
        </div>

        <div class="result" id="past-result" hidden></div>
      </div>

      <!-- ── USAGE ── -->
      <div class="panel" id="panel-${TAB_USAGE}" role="tabpanel" hidden>
        <div class="usage-head">Last billing period</div>
        <div class="usage-title">Where it's going</div>

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
      </div>

    </div>

    <div class="modal" id="manual-modal" hidden>
      <div class="dialog" role="dialog" aria-modal="true" aria-labelledby="manual-title">
        <h3 id="manual-title">Redeem any past hour</h3>
        <div class="property" id="manual-window"></div>
        <div class="manual">
          <label>Date
            <input type="date" id="manual-date">
          </label>
          <label>Starts
            <select id="manual-hour">${pastHours}</select>
          </label>
          <label>Hours
            <select id="manual-duration">
              <option value="1">1</option>
              <option value="2">2</option>
              <option value="3">3</option>
              <option value="4">4</option>
            </select>
          </label>
        </div>
        <div class="result bad" id="manual-error" hidden></div>
        <div class="dialog-actions">
          <button class="secondary" id="manual-cancel">Not now</button>
          <button class="primary" id="manual-review">Review</button>
        </div>
      </div>
    </div>

    <div class="modal" id="confirm-modal" hidden>
      <div class="dialog" role="dialog" aria-modal="true" aria-labelledby="confirm-title">
        <h3 id="confirm-title">Use your Power Shout?</h3>
        <div class="property" id="confirm-property"></div>
        <ul id="confirm-hours"></ul>
        <div class="warning" id="confirm-warning">
          The credit goes onto your next bill. A past Power Shout cannot be changed or cancelled, and may take up to two hours to appear in history.
        </div>
        <div class="dialog-actions">
          <button class="secondary" id="confirm-cancel">Not yet</button>
          <button class="primary" id="confirm-submit">Use Power Shout</button>
        </div>
      </div>
    </div>`;
}

// ─── card element ────────────────────────────────────────────────────────────

class GenesisPowerShoutCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._hass = null;
    this._built = false;
    this._entities = null;
    this._selectedDuration = 2;
    this._unit = "money";
    this._lastStartHour = null;
    this._offerId = null;
    this._tab = TAB_SHOUT;

    this._selectedHours = new Set();
    this._rankedHours = [];
    this._rankedSignature = "";
    this._bookingSignature = "";
    this._siteKeys = [];
    this._activeSiteEntity = null;

    this._pendingRedemption = null;
    this._retrySelection = null;
    this._redeeming = false;
    this._cancelling = null;
    this._booking = false;
  }

  setConfig(config) {
    this._config = config || {};
  }

  getCardSize() {
    return 8;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._built) this._build();
    this._update();
  }

  // ─── entity resolution ───────────────────────────────────────────────────

  _resolveEntities() {
    let prefix;

    if (this._config.entity_balance) {
      prefix = this._config.entity_balance
        .replace(/^sensor\./, "")
        .replace(/_power_shout_balance$/, "");
    } else {
      const balId = Object.keys(this._hass.states).find(
        (id) => id.startsWith("sensor.") && id.endsWith("_power_shout_balance")
      );
      if (!balId) return null;
      prefix = balId.replace(/^sensor\./, "").replace(/_power_shout_balance$/, "");
    }

    // One recommendation entity exists per eligible property.
    const recommendationIds = Object.keys(this._hass.states)
      .filter(
        (id) =>
          id.startsWith("binary_sensor.") &&
          id.includes("_power_shout_highest_savings")
      )
      .sort();
    this._siteKeys = recommendationIds;

    const configured = this._config.entity_highest_savings;
    const preferred =
      (configured && recommendationIds.includes(configured) && configured) ||
      (this._activeSiteEntity &&
        recommendationIds.includes(this._activeSiteEntity) &&
        this._activeSiteEntity) ||
      recommendationIds.find((id) =>
        id.startsWith(`binary_sensor.${prefix}_power_shout_highest_savings`)
      ) ||
      recommendationIds[0] ||
      null;
    this._activeSiteEntity = preferred;

    return {
      entity_balance:               `sensor.${prefix}_power_shout_balance`,
      entity_bill_balance:          `sensor.${prefix}_bill_balance`,
      entity_bill_due_date:         `sensor.${prefix}_bill_due_date`,
      entity_booking_in_progress:   `binary_sensor.${prefix}_power_shout_booking_in_progress`,
      entity_booking_upcoming:      `binary_sensor.${prefix}_power_shout_booking_upcoming`,
      entity_offers_available:      `binary_sensor.${prefix}_power_shout_offers_available`,
      entity_highest_savings:       preferred,
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
      ...this._config,
      // The property picker overrides YAML so switching sites works at runtime.
      ...(preferred ? { entity_highest_savings: preferred } : {}),
    };
  }

  // ─── DOM setup (once) ────────────────────────────────────────────────────

  _build() {
    const base = new URL("./", import.meta.url).href;
    ensureFonts(base);
    this.shadowRoot.innerHTML = buildTemplate(`${base}powershout.svg`);
    this._built = true;
    this._wireListeners();
  }

  _el(id) {
    return this.shadowRoot.getElementById(id);
  }

  _wireListeners() {
    this.shadowRoot.querySelectorAll('[role="tab"]').forEach((tab) => {
      tab.addEventListener("click", () => this._selectTab(tab.dataset.tab));
    });

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

    this._el("booking-list").addEventListener("click", (event) => {
      const btn = event.target.closest("button[data-booking]");
      if (btn) this._cancelBooking(btn.dataset.booking);
    });

    this._el("site-sel").addEventListener("change", (event) => {
      this._activeSiteEntity = event.target.value;
      this._selectedHours.clear();
      this._rankedSignature = "";
      this._update();
    });

    this._el("ranked-list").addEventListener("change", (event) => {
      const checkbox = event.target.closest("input[data-start]");
      if (!checkbox) return;
      const start = checkbox.dataset.start;
      if (checkbox.checked && this._selectedHours.size >= this._selectionLimit()) {
        checkbox.checked = false;
        return;
      }
      if (checkbox.checked) this._selectedHours.add(start);
      else this._selectedHours.delete(start);
      this._syncSelection();
    });

    this._el("redeem-selected").addEventListener("click", () => {
      const starts = this._rankedHours
        .filter((item) => this._selectedHours.has(item.start_datetime))
        .map((item) => item.start_datetime);
      if (starts.length) this._reviewPast({ starts, duration: 1 });
    });

    this._el("manual-open").addEventListener("click", () => this._openManual());
    this._el("manual-cancel").addEventListener("click", () =>
      this._el("manual-modal").setAttribute("hidden", "")
    );
    this._el("manual-modal").addEventListener("click", (event) => {
      if (event.target.id === "manual-modal") {
        this._el("manual-modal").setAttribute("hidden", "");
      }
    });
    this._el("manual-review").addEventListener("click", () =>
      this._reviewManualPast()
    );
    this._el("confirm-cancel").addEventListener("click", () =>
      this._closeConfirmation()
    );
    this._el("confirm-submit").addEventListener("click", () => this._redeemPast());
    this._el("confirm-modal").addEventListener("click", (event) => {
      if (event.target.id === "confirm-modal") this._closeConfirmation();
    });
    this._el("past-result").addEventListener("click", (event) => {
      if (event.target.closest("#retry-past")) this._retryPastFailures();
    });
  }

  _selectTab(tab) {
    if (!tab) return;
    this._tab = tab;
    this.shadowRoot.querySelectorAll('[role="tab"]').forEach((btn) => {
      btn.setAttribute("aria-selected", String(btn.dataset.tab === tab));
    });
    for (const name of [TAB_SHOUT, TAB_PAST, TAB_USAGE]) {
      this._el(`panel-${name}`).toggleAttribute("hidden", name !== tab);
    }
  }

  // ─── service calls ───────────────────────────────────────────────────────

  async _book() {
    if (!this._hass || this._booking) return;
    const startVal = this._el("start-sel").value;
    if (!startVal) return;
    const recommendationState = this._st("entity_highest_savings");
    const siteKey = recommendationState?.attributes?.site_key;
    const configEntryId = recommendationState?.attributes?.config_entry_id;

    this._booking = true;
    const cta = this._el("book-cta");
    // The CTA wraps the start <select>, so keep the choice across the swap.
    const markup = cta.innerHTML;
    cta.classList.add("busy");
    cta.innerHTML = '<span class="spin"></span>Booking…';
    try {
      await this._hass.callService(DOMAIN, "add_powershout_booking", {
        start_datetime: startVal,
        duration_hours: this._selectedDuration,
        ...(siteKey ? { site_key: siteKey } : {}),
        ...(configEntryId ? { config_entry_id: configEntryId } : {}),
      });
    } finally {
      this._booking = false;
      cta.classList.remove("busy");
      cta.innerHTML = markup;
      const restored = this._el("start-sel");
      if (restored) restored.value = startVal;
      this._lastStartHour = null;
      this._bookingSignature = "";
      this._update();
    }
  }

  _acceptOffer() {
    if (!this._hass || !this._offerId) return;
    this._hass.callService(DOMAIN, "accept_powershout_offer", {
      offer_id: this._offerId,
    });
  }

  async _cancelBooking(id) {
    if (!this._hass || !id || this._cancelling) return;
    const attributes = this._st("entity_highest_savings")?.attributes || {};
    this._cancelling = id;
    this._renderBookings(true);
    try {
      await this._hass.callService(DOMAIN, "cancel_powershout_booking", {
        booking_id: id,
        ...(attributes.site_key ? { site_key: attributes.site_key } : {}),
        ...(attributes.config_entry_id
          ? { config_entry_id: attributes.config_entry_id }
          : {}),
      });
    } finally {
      this._cancelling = null;
      this._bookingSignature = "";
      this._renderBookings();
    }
  }

  _balanceHours() {
    const value = parseFloat(this._st("entity_balance")?.state);
    return isNaN(value) ? 0 : Math.floor(value);
  }

  _selectionLimit() {
    const reported = Number(
      this._st("entity_highest_savings")?.attributes?.available_hours || 0
    );
    const available = reported > 0 ? reported : this._balanceHours();
    return Math.max(0, Math.min(available, this._rankedHours.length));
  }

  _reviewPast(selection) {
    const { starts, duration } = selection;
    if (!starts.length || this._redeeming) return;
    const state = this._st("entity_highest_savings");
    const property = state?.attributes?.property || "Electricity property";
    const hoursUsed = starts.length > 1 ? starts.length : duration;
    const byStart = new Map(
      this._rankedHours.map((item) => [item.start_datetime, item])
    );
    const credit = starts.reduce(
      (total, start) => total + Number(byStart.get(start)?.cost || 0),
      0
    );

    this._pendingRedemption = selection;
    this._el("confirm-property").textContent = property;
    this._el("confirm-hours").innerHTML = [
      ...starts.map((start) => {
        const known = byStart.get(start);
        const suffix =
          starts.length === 1 && duration > 1 ? ` for ${duration} hours` : "";
        const back = known
          ? ` — <strong>$${Number(known.cost).toFixed(2)}</strong> back`
          : "";
        return `<li>${escapeHtml(fmtPastHour(start))}${escapeHtml(suffix)}${back}</li>`;
      }),
      `<li><strong>${hoursUsed} Power Shout hour${
        hoursUsed === 1 ? "" : "s"
      }</strong> will be used.</li>`,
      credit > 0
        ? `<li>Around <strong>$${credit.toFixed(2)}</strong> should come off your next bill.</li>`
        : "",
    ]
      .filter(Boolean)
      .join("");
    this._el("confirm-modal").removeAttribute("hidden");
  }

  _openManual() {
    const attributes = this._st("entity_highest_savings")?.attributes || {};
    const from = fmtWindow(attributes.earliest_date);
    const to = fmtWindow(attributes.latest_date);
    this._el("manual-window").textContent =
      from && to ? `Any hour from ${from} to ${to}` : "";
    this._manualError("");
    this._el("manual-modal").removeAttribute("hidden");
  }

  _manualError(message) {
    const element = this._el("manual-error");
    element.textContent = message;
    element.toggleAttribute("hidden", !message);
  }

  _reviewManualPast() {
    this._manualError("");
    const date = this._el("manual-date").value;
    const hour = this._el("manual-hour").value;
    const duration = parseInt(this._el("manual-duration").value, 10);
    if (!date || hour === "" || !duration) return;
    const dateInput = this._el("manual-date");
    if (
      (dateInput.min && date < dateInput.min) ||
      (dateInput.max && date > dateInput.max)
    ) {
      this._manualError(`Choose a date from ${dateInput.min} to ${dateInput.max}.`);
      return;
    }
    const reported = Number(
      this._st("entity_highest_savings")?.attributes?.available_hours || 0
    );
    const availableHours = reported > 0 ? reported : this._balanceHours();
    if (duration > availableHours) {
      this._manualError(`You only have ${availableHours} Power Shout hour${
          availableHours === 1 ? "" : "s"
        } available.`);
      return;
    }
    if (parseInt(hour, 10) + duration > 24) {
      this._manualError("That duration would run past midnight. Choose an earlier start or fewer hours.");
      return;
    }
    const manualStart = `${date}T${hour}:00:00`;
    this._el("manual-modal").setAttribute("hidden", "");
    this._reviewPast({ starts: [manualStart], duration });
  }

  _closeConfirmation() {
    if (this._redeeming) return;
    this._pendingRedemption = null;
    this._el("confirm-modal").setAttribute("hidden", "");
  }

  async _redeemPast() {
    const pending = this._pendingRedemption;
    const entityId = this._entities?.entity_highest_savings;
    if (!pending || !entityId || this._redeeming) return;

    this._redeeming = true;
    this._setRedeemBusy(true);
    try {
      // Every eligible hour is redeemable by time, so one path covers both the
      // ranked list and the manual picker.
      const response = await this._hass.callWS({
        type: "call_service",
        domain: DOMAIN,
        service: "redeem_powershout",
        target: { entity_id: entityId },
        service_data: {
          start_datetime: pending.starts,
          duration_hours: pending.duration,
        },
        return_response: true,
      });
      const result = response?.response?.[entityId];
      if (!result) throw new Error("Home Assistant returned no redemption result.");
      this._renderPastResult(result);
    } catch (error) {
      this._retrySelection = pending;
      this._showPastMessage(
        error?.message || "Genesis could not apply that Power Shout.",
        true,
        true
      );
    } finally {
      this._redeeming = false;
      this._pendingRedemption = null;
      this._setRedeemBusy(false);
      this._el("confirm-modal").setAttribute("hidden", "");
    }
  }

  _setRedeemBusy(busy) {
    // Genesis re-checks eligibility, fetches vouchers per date, then books each
    // hour, so this round-trip runs for several seconds.
    const submit = this._el("confirm-submit");
    submit.disabled = busy;
    submit.innerHTML = busy
      ? '<span class="spin"></span>Applying…'
      : "Use Power Shout";
    this._el("confirm-cancel").disabled = busy;
    this._el("redeem-selected").disabled = busy || this._selectedHours.size === 0;
    this._el("manual-review").disabled = busy;
  }

  _renderPastResult(result) {
    const succeeded = Array.isArray(result.succeeded) ? result.succeeded : [];
    const failed = Array.isArray(result.failed) ? result.failed : [];
    const succeededHours = succeeded.reduce(
      (total, item) => total + Number(item.duration_hours || 1),
      0
    );
    this._retrySelection = failed.length
      ? {
          starts: failed.map((item) => item.start_datetime),
          duration: failed[0].duration_hours || 1,
        }
      : null;
    for (const item of succeeded) {
      this._selectedHours.delete(item.start_datetime);
    }
    if (succeeded.length) {
      this._rankedSignature = "";
      this._renderRankedList();
    }

    const lines = [
      ...succeeded.map(
        (item) =>
          `<li>${escapeHtml(fmtPastHour(item.start_datetime))}: ${escapeHtml(
            `${item.duration_hours || 1} hour${
              Number(item.duration_hours || 1) === 1 ? "" : "s"
            } applied`
          )}</li>`
      ),
      ...failed.map(
        (item) =>
          `<li>${escapeHtml(fmtPastHour(item.start_datetime))}: ${escapeHtml(
            item.message || "not applied"
          )}</li>`
      ),
    ];
    const heading = failed.length
      ? `${succeededHours} hour${
          succeededHours === 1 ? "" : "s"
        } applied, ${failed.length} booking${failed.length === 1 ? "" : "s"} not applied.`
      : `${succeededHours} Power Shout hour${
          succeededHours === 1 ? "" : "s"
        } applied.`;
    const historyNote = succeeded.length
      ? " It may take up to two hours to appear in history."
      : "";
    const retry = failed.length
      ? '<div class="panel-actions"><button id="retry-past">Retry failed</button></div>'
      : "";
    const element = this._el("past-result");
    element.className = `result ${failed.length ? "bad" : "ok"}`;
    element.innerHTML = `<strong>${escapeHtml(heading)}</strong>${escapeHtml(
      historyNote
    )}<ul>${lines.join("")}</ul>${retry}`;
    element.removeAttribute("hidden");
    this._syncSelection();
  }

  _showPastMessage(message, isError = false, retry = false) {
    const element = this._el("past-result");
    element.className = `result ${isError ? "bad" : "ok"}`;
    element.innerHTML = `${escapeHtml(message)}${
      retry
        ? '<div class="panel-actions"><button id="retry-past">Retry</button></div>'
        : ""
    }`;
    element.removeAttribute("hidden");
  }

  _retryPastFailures() {
    if (!this._retrySelection || this._redeeming) return;
    this._pendingRedemption = this._retrySelection;
    this._redeemPast();
  }

  // ─── data update ─────────────────────────────────────────────────────────

  _update() {
    if (!this._built || !this._hass) return;
    this._entities = this._resolveEntities();
    if (!this._entities) return; // integration not yet loaded
    this._refreshStartOptions();
    this._updateBalance();
    this._updateLiveBar();
    this._updatePastHours();
    this._updateOffer();
    this._updateExpiring();
    this._renderBookings();
    this._updateForecast();
    this._updateEstBill();
    this._updateBreakdown();
    this._updateEcoEV();
  }

  _st(key) {
    const id = this._entities?.[key];
    return id ? this._hass.states[id] : null;
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

  _updateBalance() {
    const st = this._st("entity_balance");
    const num = st ? parseFloat(st.state) : null;
    this._el("bal-num").textContent = num != null && !isNaN(num) ? num : "—";

    const bal = fmtNum(this._st("entity_bill_balance")?.state, 2);
    this._el("bill-balance-cap").innerHTML =
      bal != null ? `Bill balance · <b>$${bal}</b>` : "Bill balance";

    this._updateDuePill(bal);
  }

  _updateDuePill(billBalance) {
    const pill = this._el("bill-due-pill");
    const owing = billBalance == null ? null : parseFloat(billBalance);
    const dueStr = this._st("entity_bill_due_date")?.state;
    const dueDate = dueStr ? new Date(dueStr) : null;
    const valid = dueDate && !isNaN(dueDate);

    let label = null;
    let tone = "";

    if (owing != null && owing < 0) {
      label = `$${Math.abs(owing).toFixed(2)} in credit`;
      tone = "ok";
    } else if (owing != null && owing === 0) {
      // Nothing owed, so a past due date is history — never show it.
      label = "Up to date";
      tone = "ok";
    } else if (owing != null && owing > 0) {
      if (!valid) {
        label = `$${owing.toFixed(2)} owing`;
      } else {
        const midnight = new Date();
        midnight.setHours(0, 0, 0, 0);
        dueDate.setHours(0, 0, 0, 0);
        const days = Math.round((dueDate - midnight) / 86400000);
        if (days < 0) {
          label = "Overdue";
          tone = "bad";
        } else if (days === 0) {
          label = "Due today";
          tone = "bad";
        } else {
          label = `Due ${fmtDate(dueStr)}`;
        }
      }
    } else if (valid) {
      label = `Due ${fmtDate(dueStr)}`;
    }

    pill.classList.remove("ok", "bad");
    if (!label) {
      pill.style.display = "none";
      return;
    }
    if (tone) pill.classList.add(tone);
    pill.textContent = label;
    pill.style.display = "";
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

  _updateExpiring() {
    const note = this._el("expiring-note");
    const message = this._st("entity_balance")?.attributes?.expiring_hours_message;
    if (!message) {
      note.setAttribute("hidden", "");
      return;
    }
    note.textContent = message;
    note.removeAttribute("hidden");
  }

  // ── booked shouts ──

  _upcomingBookings() {
    const bookings = this._st("entity_balance")?.attributes?.bookings;
    if (!Array.isArray(bookings)) return [];
    const now = Date.now();
    return bookings
      .filter((booking) => {
        if (!booking?.startDateTime) return false;
        const start = new Date(booking.startDateTime);
        if (isNaN(start)) return false;
        const end = start.getTime() + (Number(booking.duration) || 1) * 3600000;
        return end > now;
      })
      .sort((a, b) => String(a.startDateTime).localeCompare(String(b.startDateTime)));
  }

  _renderBookings(force = false) {
    const bookings = this._upcomingBookings();
    const signature = JSON.stringify([
      bookings.map((b) => [bookingId(b), b.startDateTime, b.duration]),
      this._cancelling,
    ]);
    if (!force && signature === this._bookingSignature) return;
    this._bookingSignature = signature;

    const list = this._el("booking-list");
    this._el("booked-lbl").toggleAttribute("hidden", false);

    if (!bookings.length) {
      list.innerHTML = '<div class="empty">Nothing booked yet.</div>';
      return;
    }

    list.innerHTML = bookings
      .map((booking) => {
        const id = bookingId(booking);
        const hours = Math.max(1, Number(booking.duration) || 1);
        const start = fmtPastHour(booking.startDateTime);
        const end = endHourLabel(booking.startDateTime, hours);
        const busy = this._cancelling === id;
        const locked = this._cancelling && !busy;
        return `
          <div class="bk${busy ? " busy" : ""}">
            <span class="w">${escapeHtml(start)}${
              end ? ` – ${escapeHtml(end)}` : ""
            }<small>${hours} hr</small></span>
            ${
              id
                ? `<button data-booking="${escapeHtml(id)}"${
                    busy || locked ? " disabled" : ""
                  }>${
                    busy ? '<span class="spin"></span>Cancelling…' : "Cancel"
                  }</button>`
                : ""
            }
          </div>`;
      })
      .join("");
  }

  // ── past hours ──

  _updatePastHours() {
    const state = this._st("entity_highest_savings");
    const attributes = state?.attributes || {};
    const availableHours = Number(attributes.available_hours || 0);
    const pastDays = Number(attributes.past_days || 0);
    const enabled = attributes.feature_enabled === true;
    const ranked = Array.isArray(attributes.ranked_hours)
      ? attributes.ranked_hours
      : [];

    // Keep the tab whenever the feature applies, so a Genesis outage shows a
    // reason instead of silently removing past hours from the card.
    const offline = !state || state.state === "unavailable";
    const applies = !offline && enabled && pastDays >= 1;

    this._el("tab-past").toggleAttribute("hidden", !applies);
    if (!applies) {
      if (this._tab === TAB_PAST) this._selectTab(TAB_SHOUT);
      this._rankedHours = [];
      return;
    }

    // Ranking comes from local statistics, so a Genesis outage costs only the
    // "Genesis pick" badges — the list and redemption still work.
    const spendable = availableHours > 0 ? availableHours : this._balanceHours();
    const reason = attributes.error
      ? PAST_ERRORS[attributes.error] || "Genesis could not load past hours."
      : null;
    const notice = reason
      ? attributes.error_detail
        ? `${reason} (${attributes.error_detail})`
        : reason
      : spendable < 1
        ? "You have no Power Shout hours left to spend."
        : null;
    const dead = Boolean(notice) && !ranked.length;

    this._el("past-notice").textContent = notice || "";
    this._el("past-notice").toggleAttribute("hidden", !notice);
    this._el("past-body").toggleAttribute("hidden", dead);
    if (dead) {
      this._el("past-count").setAttribute("hidden", "");
      this._rankedHours = [];
      return;
    }

    this._renderSiteSelector();

    const count = this._el("past-count");
    count.textContent = String(ranked.length);
    count.toggleAttribute("hidden", ranked.length === 0);

    this._rankedHours = ranked;
    this._selectedHours = new Set(
      [...this._selectedHours].filter((start) =>
        ranked.some((item) => item.start_datetime === start)
      )
    );

    const dateInput = this._el("manual-date");
    dateInput.min = attributes.earliest_date || "";
    dateInput.max = attributes.latest_date || "";

    const signature = JSON.stringify(ranked);
    if (signature !== this._rankedSignature) {
      this._rankedSignature = signature;
      this._renderRankedList();
    }
    this._syncSelection();
  }

  _renderSiteSelector() {
    const select = this._el("site-sel");
    if (this._siteKeys.length < 2) {
      select.setAttribute("hidden", "");
      return;
    }
    const options = this._siteKeys
      .map((id) => {
        const label =
          this._hass.states[id]?.attributes?.property ||
          this._hass.states[id]?.attributes?.friendly_name ||
          id;
        return `<option value="${escapeHtml(id)}">${escapeHtml(label)}</option>`;
      })
      .join("");
    if (select.innerHTML !== options) select.innerHTML = options;
    select.value = this._entities.entity_highest_savings;
    select.removeAttribute("hidden");
  }

  _renderRankedList() {
    const list = this._el("ranked-list");
    if (!this._rankedHours.length) {
      list.innerHTML =
        '<div class="empty">No ranked hours yet — pick any eligible hour below.</div>';
      return;
    }
    list.innerHTML = this._rankedHours
      .map((item, index) => {
        const start = item.start_datetime;
        const checked = this._selectedHours.has(start) ? " checked" : "";
        const cost = Number(item.cost || 0).toFixed(2);
        const kwh = Number(item.kwh || 0).toFixed(2);
        const badge =
          index === 0
            ? '<span class="rank best">Best</span>'
            : item.genesis_rank
              ? '<span class="rank genesis">Genesis pick</span>'
              : "";
        return `
          <div class="row">
            <input type="checkbox" id="hour-${index}" data-start="${escapeHtml(
              start
            )}"${checked}>
            <label for="hour-${index}">
              <span class="when">${escapeHtml(item.day)} · ${escapeHtml(
                item.time
              )}</span>
              <small>${kwh} kWh · <b>$${cost}</b> back</small>
            </label>
            ${badge}
          </div>`;
      })
      .join("");
  }

  _syncSelection() {
    const limit = this._selectionLimit();
    const count = this._selectedHours.size;
    const credit = this._rankedHours
      .filter((item) => this._selectedHours.has(item.start_datetime))
      .reduce((total, item) => total + Number(item.cost || 0), 0);

    const button = this._el("redeem-selected");
    button.disabled = this._redeeming || count === 0;
    button.textContent = count
      ? `Redeem ${count} hour${count === 1 ? "" : "s"} · $${credit.toFixed(2)} back`
      : "Redeem selected";

    this._el("selection-help").textContent = this._rankedHours.length
      ? `Choose up to ${limit} hour${limit === 1 ? "" : "s"}.`
      : "";

    this.shadowRoot.querySelectorAll("#ranked-list input").forEach((checkbox) => {
      checkbox.disabled = count >= limit && !checkbox.checked;
    });
  }

  // ── remaining panels ──

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
      { key: "appliances",  cfg: "entity_breakdown_appliances" },
      { key: "electronics", cfg: "entity_breakdown_electronics" },
      { key: "lighting",    cfg: "entity_breakdown_lighting" },
      { key: "heating",     cfg: "entity_breakdown_heating" },
      { key: "hot_water",   cfg: "entity_breakdown_hot_water" },
      { key: "other",       cfg: "entity_breakdown_other" },
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
    "Power Shout balance, cost-ranked past-hour redemption, bookings, offers, forecast, and usage breakdown.",
  preview: false,
});

console.info(
  `%c GENESISENERGY-POWERSHOUT-CARD %c v${CARD_VERSION} `,
  "color:#fff;background:#F15B29;font-weight:700;padding:2px 4px;",
  "color:#F15B29;background:#fff;font-weight:700;padding:2px 4px;"
);
