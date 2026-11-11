// Market tab on the brief page (#/brief/<id>/market): search SEC filings for what
// companies say about the technology in this brief's research, and get a market
// scan with growth opportunities. Running a scan is one LLM call plus SEC EDGAR
// requests; opening, reviewing or deleting a saved scan costs nothing.
//
// Loaded before app.js. It uses app.js helpers (state, esc, api, toast, copyText,
// formatDate, renderDoc, statusPill, icon, renderBrief, STATUS) only when the
// page draws. app.js calls marketPanel(), bindMarket(), projectMarketSection()
// and loadProjectMarket(). The form lives in `mkt`, so it survives redraws.

const mkt = {
  briefId: "",
  options: null,        // industries, lenses, windows, whether EDGAR is set up
  loading: false,
  phrases: [],
  industry: "Cross-industry",
  lens: "both",
  window: 90,
  scans: [],            // saved scans for this brief (short rows), newest first
  current: null,        // the full scan on screen
  busy: false,
  error: "",
  noteOpen: false,
  confirmDelete: false,
};

const MARKET_LENS_LABELS = { client: "Client industry", firm: "Our firm", both: "Both" };

const SOURCE_GROUP = /\[((?:[FD]\d+)(?:\s*[,;]\s*[FD]\d+)*)\]/g;
const ARXIV_ID = /^\d{4}\.\d{4,5}(?:v\d+)?$/;

// ---------- loading ----------

async function marketLoad(briefId) {
  mkt.briefId = briefId;
  mkt.loading = true;
  mkt.current = null;
  mkt.scans = [];
  mkt.error = "";
  mkt.noteOpen = false;
  mkt.confirmDelete = false;
  try {
    const [options, phrases, scans] = await Promise.all([
      mkt.options ? Promise.resolve(mkt.options) : api("/api/market/options"),
      api(`/api/briefs/${briefId}/market-phrases`),
      api(`/api/briefs/${briefId}/market-scans`),
    ]);
    if (mkt.briefId !== briefId) return;
    if (!mkt.options) {
      mkt.industry = options.default_industry;
      mkt.lens = options.default_lens;
      mkt.window = options.default_window;
    }
    mkt.options = options;
    mkt.phrases = phrases.phrases;
    mkt.scans = scans;
    if (scans.length) mkt.current = await api(`/api/market-scans/${scans[0].id}`);
  } catch (error) {
    mkt.error = error.message;
  }
  mkt.loading = false;
  marketRedraw(briefId);
}

function marketRedraw(briefId) {
  if (state.record && state.record.id === briefId && state.tab === "market") renderBrief();
}

// ---------- rendering the scan ----------

// "[F1, 2609.38107v1]" -> "[2609.38107v1][F1]", so each kind of citation renders
function splitMixedCitations(text) {
  return String(text || "").replace(/\[([^\[\]]+)\]/g, (whole, inner) => {
    const parts = inner.split(/\s*[,;]\s*/);
    const papers = parts.filter((p) => ARXIV_ID.test(p));
    const sources = parts.filter((p) => /^[FD]\d+$/.test(p));
    if (papers.length + sources.length !== parts.length || !papers.length || !sources.length) return whole;
    return `[${papers.join(", ")}][${sources.join(", ")}]`;
  });
}

function marketDoc(scan, record) {
  const html = renderDoc(splitMixedCitations(scan.scan), record.sources);
  const known = new Set([
    ...scan.sources.filings.map((f) => f.id),
    ...scan.sources.signals.map((s) => s.id),
  ]);
  return html.replace(SOURCE_GROUP, (_, group) => `<sup class="cites">${group.split(/\s*[,;]\s*/).map((id) =>
    known.has(id)
      ? `<a class="cite cite--market" href="#mkt-${id}" data-mkt-src="${id}" title="${esc(marketSourceTitle(scan, id))}">${id}</a>`
      : `<span class="cite-missing" title="Not one of this scan's sources">${esc(id)}?</span>`,
  ).join('<span aria-hidden="true">,</span>')}</sup>`);
}

function marketSourceTitle(scan, id) {
  const filing = scan.sources.filings.find((f) => f.id === id);
  if (filing) return `${filing.company}, ${filing.form} filed ${filing.filed}`;
  const signal = scan.sources.signals.find((s) => s.id === id);
  return signal ? `Filings mentioning “${signal.phrase}”` : id;
}

function marketChecks(scan) {
  const c = scan.checks;
  const cards = [];
  const badCites = [...c.citations.unknown_sources, ...c.citations.papers_not_retrieved, ...c.citations.papers_not_in_summary];
  cards.push(c.citations.ok
    ? ["ok", "Citations verified", "Every filing, count and paper cited is one of this scan’s sources."]
    : ["bad", "Citation problem", `Cites sources it doesn’t have: ${badCites.join(", ")}.`]);
  cards.push(c.numbers.ok
    ? ["ok", "Numbers traced", "Every number appears in a filing, a count or the research summary."]
    : ["warn", "Numbers to check", `Not found in any source: ${c.numbers.ungrounded.join(", ")}. Check or remove before using.`]);
  if (c.targets && !c.targets.ok) {
    cards.push(["warn", "Companies named as targets", `An opportunity is “for” ${c.targets.named.join(", ").replace(/\.$/, "")}. Companies in filings are evidence, not sales targets; edit before sharing.`]);
  }
  const s = c.sources;
  const range = s.first_filed ? `filed ${formatDate(s.first_filed, false)} – ${formatDate(s.last_filed)}` : "";
  cards.push(s.thin
    ? ["warn", "Thin evidence", `Only ${s.filings} filing${s.filings === 1 ? "" : "s"} matched. Try broader phrases or a longer window.`]
    : ["ok", `${s.filings} filings from ${s.companies} companies`, range]);
  if (!c.template.ok) cards.push(["warn", "Template check failed", `Missing: ${c.template.missing.join(", ")}.`]);
  if (scan.truncated) cards.push(["bad", "Output cut off", "The model hit its token limit. Run the scan again before using it."]);
  return cards.map(([kind, title, sub]) => `<div class="check">${icon(kind)}<div>
    <strong>${esc(title)}</strong><span>${esc(sub)}</span></div></div>`).join("");
}

function marketSourcesAside(scan) {
  const signals = scan.sources.signals;
  const filings = scan.sources.filings;
  return `<aside class="sources-aside market-aside" aria-labelledby="mkt-sources-h">
    <h2 id="mkt-sources-h">Sources</h2>
    <div class="src market-signals">
      <span class="id">Filings that mention each phrase, last ${scan.window_days} days vs. a year earlier</span>
      <table>
        <thead><tr><th scope="col"></th><th scope="col">Phrase</th><th scope="col">Now</th><th scope="col">Year ago</th></tr></thead>
        <tbody>${signals.map((s) => `<tr id="mkt-${esc(s.id)}">
          <td><span class="num">${esc(s.id)}</span></td>
          <td>${esc(s.phrase)}</td>
          <td>${s.recent.toLocaleString("en-US")}</td>
          <td>${s.year_earlier.toLocaleString("en-US")}${s.change === null ? "" : ` <span class="change ${s.change >= 0 ? "up" : "down"}">${s.change >= 0 ? "+" : ""}${s.change}%</span>`}</td>
        </tr>`).join("")}</tbody>
      </table>
    </div>
    ${filings.map((f) => `<div class="src" id="mkt-${esc(f.id)}">
      <span class="id"><span class="num">${esc(f.id)}</span>${esc(f.form)}${f.document_type && f.document_type !== f.form ? ` · ${esc(f.document_type)}` : ""} · filed ${esc(formatDate(f.filed))}</span>
      <span class="name">${esc(f.company)}${f.ticker ? ` <span class="ticker">${esc(f.ticker)}</span>` : ""}</span>
      <details><summary>Excerpt${f.excerpts.length > 1 ? "s" : ""} for “${esc(f.phrase)}”</summary>
        ${f.excerpts.map((q) => `<blockquote>${esc(q)}</blockquote>`).join("")}
      </details>
      <a href="${esc(f.url)}" target="_blank" rel="noopener">Open on SEC.gov</a>
    </div>`).join("")}
  </aside>`;
}

function marketReview(scan) {
  const status = STATUS[scan.status] || STATUS.draft;
  return `<section class="card market-review no-print" aria-labelledby="mkt-review-h">
    <div class="market-review-head">
      <h2 id="mkt-review-h">Review</h2>
      ${statusPill(scan.status)}
    </div>
    <p class="intro">${esc(status.sub)}</p>
    ${scan.note ? `<p class="note"><strong>Reviewer note:</strong> ${esc(scan.note)}</p>` : ""}
    ${mkt.noteOpen ? `<form id="mkt-note-form" class="stack">
        <label for="mkt-note" class="small-label">What should change? (optional)</label>
        <textarea id="mkt-note" class="field" rows="2" placeholder="e.g., Too many risk-factor boilerplate quotes; look at 8-K announcements."></textarea>
        <div class="actions">
          <button type="submit" class="btn">Send back</button>
          <button type="button" class="btn" id="mkt-note-cancel">Cancel</button>
        </div>
      </form>` : `<div class="actions">
        ${scan.status !== "changes" ? '<button type="button" class="btn" id="mkt-request-changes">Request changes</button>' : ""}
        ${scan.status !== "approved" ? '<button type="button" class="btn btn--primary" id="mkt-approve">Approve scan</button>' : ""}
        <button type="button" class="btn" id="mkt-copy">Copy scan</button>
        <button type="button" class="btn" id="mkt-delete">${mkt.confirmDelete ? "Click again to delete" : "Delete scan"}</button>
      </div>`}
  </section>`;
}

function marketScanView(scan, record) {
  const d = scan.sources;
  return `<article class="card market-scan">
      <div class="market-scan-head">
        <div class="badges">
          ${statusPill(scan.status)}
          <span class="status status--info">${esc(scan.industry)} · ${esc(MARKET_LENS_LABELS[scan.lens] || scan.lens)}</span>
        </div>
        <p class="market-fresh">SEC filings ${esc(formatDate(d.since, false))} – ${esc(formatDate(d.until))},
          retrieved ${esc(formatDate(scan.created_at))} · phrases: ${scan.phrases.map((p) => `“${esc(p)}”`).join(", ")}</p>
      </div>
      <p class="market-caution">A starting point for discussion, built from public filings. Companies named are evidence of
        market direction, not sales targets; check independence rules before approaching any of them.</p>
      <div class="doc">${marketDoc(scan, record)}</div>
    </article>
    <section class="stack market-checks" aria-label="Automatic checks">${marketChecks(scan)}</section>
    ${marketReview(scan)}`;
}

// ---------- the form ----------

function marketForm() {
  const o = mkt.options;
  const max = o ? o.max_phrases : 4;
  return `<section class="card market-form no-print" aria-labelledby="mkt-form-h">
    <div class="poc-head">
      <h2 id="mkt-form-h">${mkt.current ? "Run a new market scan" : "Market scan"}</h2>
      <span class="status status--info">1 LLM call + SEC EDGAR search</span>
    </div>
    <p class="intro">Searches public companies’ SEC filings (annual and quarterly reports, current reports and press releases) for these phrases, then writes what they show about the market and where it could grow. Only the phrases and industry are sent to SEC, never client details.</p>
    <form id="mkt-form" class="stack" novalidate>
      <fieldset class="market-phrases">
        <legend class="poc-label">Search phrases <span class="poc-optional">Filings must contain the exact phrase. Short, common wording works best.</span></legend>
        ${mkt.phrases.map((p, i) => `<div class="market-phrase">
          <label class="sr-only" for="mkt-phrase-${i}">Phrase ${i + 1}</label>
          <input id="mkt-phrase-${i}" class="text-input" type="text" maxlength="60" value="${esc(p)}" data-mkt-phrase="${i}">
          <button type="button" class="tag-x" data-mkt-remove="${i}" aria-label="Remove ${esc(p || "phrase")}">×</button>
        </div>`).join("")}
        ${mkt.phrases.length < max ? '<button type="button" class="btn btn--link" id="mkt-add">Add a phrase</button>' : ""}
      </fieldset>
      <div class="market-options">
        <div class="form-field">
          <label for="mkt-industry">Industry</label>
          <select id="mkt-industry" class="select select--light">
            ${(o ? o.industries : [mkt.industry]).map((i) => `<option${i === mkt.industry ? " selected" : ""}>${esc(i)}</option>`).join("")}
          </select>
        </div>
        <div class="form-field">
          <label for="mkt-window">Filed in the last</label>
          <select id="mkt-window" class="select select--light">
            ${(o ? o.windows : [mkt.window]).map((w) => `<option value="${w}"${w === mkt.window ? " selected" : ""}>${w} days</option>`).join("")}
          </select>
        </div>
      </div>
      ${mkt.industry === "Government & Public Services" ? '<p class="hint-text">Government agencies don’t file with the SEC, so this finds companies whose filings also mention government.</p>' : ""}
      <div class="form-field">
        <span class="poc-label" id="mkt-lens-label">Opportunities for</span>
        <div class="chip-row" role="group" aria-labelledby="mkt-lens-label">
          ${Object.entries(MARKET_LENS_LABELS).map(([id, label]) =>
            `<button type="button" class="btn" data-mkt-lens="${id}" aria-pressed="${id === mkt.lens}"
              title="${esc(o ? o.lenses[id] : "")}">${esc(label)}</button>`).join("")}
        </div>
      </div>
      <div class="poc-submit">
        <span>${mkt.busy ? "Searching SEC filings, then writing the scan. This can take a couple of minutes." : "Takes about as long as a brief."}</span>
        <button type="submit" class="btn btn--primary" id="mkt-run"${mkt.busy ? " disabled" : ""}>${mkt.busy ? "Running…" : "Run market scan"}</button>
      </div>
      ${mkt.error ? `<p class="error" role="alert">${esc(mkt.error)}</p>` : ""}
    </form>
  </section>`;
}

function marketSavedList() {
  if (mkt.scans.length < 2 && !(mkt.scans.length === 1 && !mkt.current)) return "";
  return `<section class="card no-print" aria-labelledby="mkt-saved-h">
    <h2 id="mkt-saved-h">Saved market scans for this brief</h2>
    <ul class="poc-plans">${mkt.scans.map((s) => {
      const open = mkt.current && mkt.current.id === s.id;
      const details = [s.industry, MARKET_LENS_LABELS[s.lens], `${s.window_days} days`, `${s.filings} filings`, formatDate(s.created_at)].join(" · ");
      return `<li class="poc-plan-row${open ? " poc-plan-row--open" : ""}">
        <div class="poc-plan-info"><strong>${esc(s.phrases.join(", "))}</strong><span>${esc(details)}</span></div>
        <div class="poc-row-actions">${statusPill(s.status)}
          <button type="button" class="btn" data-mkt-open="${esc(s.id)}"${open ? " disabled" : ""}>${open ? "Viewing" : "Open"}</button></div>
      </li>`;
    }).join("")}</ul>
  </section>`;
}

function marketPanel(record) {
  if (mkt.briefId !== record.id || mkt.loading) {
    return '<p class="loading">Loading market scans…</p>';
  }
  if (!record.sources.length) {
    return '<p class="intro">No papers were found for this question, so there is no research to scan the market for.</p>';
  }
  if (mkt.options && !mkt.options.configured) {
    return `<section class="card market-setup">
      <h2>Set up SEC EDGAR</h2>
      <p class="intro">${esc(mkt.options.setup)}</p>
    </section>`;
  }

  const scan = mkt.current;
  return `<div class="brief-layout market">
      <div class="brief-main">
        ${scan ? marketScanView(scan, record) : ""}
        ${marketForm()}
        ${marketSavedList()}
      </div>
      ${scan ? marketSourcesAside(scan) : `<aside class="sources-aside" aria-label="About market scans">
        <h2>How it works</h2>
        <div class="src"><span class="name">1 · Count</span><span class="where">How many filings mention each phrase now and a year earlier.</span></div>
        <div class="src"><span class="name">2 · Read</span><span class="where">Up to 8 filings, one per company, with the sentences around each mention.</span></div>
        <div class="src"><span class="name">3 · Write</span><span class="where">Snapshot, who’s moving, demand, research vs. market, opportunities, risks, watch list. Every claim cites a filing, count or paper.</span></div>
        <div class="src"><span class="name">4 · Check</span><span class="where">Citations and numbers are traced to the sources, then a reviewer approves it.</span></div>
      </aside>`}
    </div>`;
}

// ---------- events ----------

function scanAsText(scan) {
  const lines = [`Market scan: ${scan.query}`, `${scan.industry} · SEC filings ${scan.sources.since} to ${scan.sources.until}`, "", scan.scan, "", "Sources:"];
  scan.sources.signals.forEach((s) => lines.push(`[${s.id}] Filings mentioning "${s.phrase}": ${s.recent} (a year earlier: ${s.year_earlier})`));
  scan.sources.filings.forEach((f) => lines.push(`[${f.id}] ${f.company}, ${f.form} filed ${f.filed}: ${f.url}`));
  return lines.join("\n");
}

async function marketRun(briefId) {
  const phrases = mkt.phrases.map((p) => p.trim()).filter(Boolean);
  if (!phrases.length) {
    mkt.error = "Add at least one search phrase.";
    marketRedraw(briefId);
    return;
  }
  mkt.busy = true;
  mkt.error = "";
  marketRedraw(briefId);
  try {
    const scan = await api(`/api/briefs/${briefId}/market-scans`, {
      phrases, industry: mkt.industry, lens: mkt.lens, window_days: mkt.window,
    });
    if (mkt.briefId === briefId) {
      mkt.current = scan;
      mkt.scans = await api(`/api/briefs/${briefId}/market-scans`);
      toast("Market scan ready");
    }
  } catch (error) {
    if (mkt.briefId === briefId) mkt.error = error.message;
  }
  mkt.busy = false;
  marketRedraw(briefId);
  if (mkt.current) document.querySelector(".market-scan")?.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function marketStatus(briefId, status, note = "") {
  try {
    mkt.current = await api(`/api/market-scans/${mkt.current.id}/status`, { status, note });
    mkt.scans = mkt.scans.map((s) => (s.id === mkt.current.id ? { ...s, status } : s));
    mkt.noteOpen = false;
    toast(status === "approved" ? "Market scan approved" : "Sent back for changes");
  } catch (error) {
    toast(error.message);
  }
  marketRedraw(briefId);
}

function bindMarket(record) {
  if (state.tab !== "market") return;
  const briefId = record.id;
  if (mkt.briefId !== briefId) {
    marketLoad(briefId);
    return;
  }

  const on = (selector, event, handler) =>
    app.querySelectorAll(selector).forEach((el) => el.addEventListener(event, handler));

  on("[data-mkt-phrase]", "input", (e) => { mkt.phrases[Number(e.target.dataset.mktPhrase)] = e.target.value; });
  on("[data-mkt-remove]", "click", (e) => {
    mkt.phrases.splice(Number(e.currentTarget.dataset.mktRemove), 1);
    renderBrief();
  });
  on("#mkt-add", "click", () => {
    mkt.phrases.push("");
    renderBrief();
    document.getElementById(`mkt-phrase-${mkt.phrases.length - 1}`)?.focus();
  });
  on("#mkt-industry", "change", (e) => { mkt.industry = e.target.value; renderBrief(); });
  on("#mkt-window", "change", (e) => { mkt.window = Number(e.target.value); });
  on("[data-mkt-lens]", "click", (e) => {
    mkt.lens = e.currentTarget.dataset.mktLens;
    app.querySelectorAll("[data-mkt-lens]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.mktLens === mkt.lens)));
  });
  on("#mkt-form", "submit", (e) => { e.preventDefault(); if (!mkt.busy) marketRun(briefId); });

  on("[data-mkt-open]", "click", async (e) => {
    try {
      mkt.current = await api(`/api/market-scans/${e.currentTarget.dataset.mktOpen}`);
      mkt.noteOpen = false;
      mkt.confirmDelete = false;
    } catch (error) {
      toast(error.message);
    }
    renderBrief();
  });

  on("[data-mkt-src]", "click", (e) => {
    e.preventDefault();
    const card = document.getElementById("mkt-" + e.currentTarget.dataset.mktSrc);
    if (!card) return;
    card.scrollIntoView({ behavior: "smooth", block: "center" });
    card.querySelector("details")?.setAttribute("open", "");
    card.classList.add("flash");
    setTimeout(() => card.classList.remove("flash"), 1500);
  });

  on("#mkt-approve", "click", () => marketStatus(briefId, "approved"));
  on("#mkt-request-changes", "click", () => { mkt.noteOpen = true; renderBrief(); document.getElementById("mkt-note")?.focus(); });
  on("#mkt-note-cancel", "click", () => { mkt.noteOpen = false; renderBrief(); });
  on("#mkt-note-form", "submit", (e) => {
    e.preventDefault();
    marketStatus(briefId, "changes", document.getElementById("mkt-note").value);
  });
  on("#mkt-copy", "click", () => copyText(scanAsText(mkt.current), "Market scan copied"));
  on("#mkt-delete", "click", async () => {
    if (!mkt.confirmDelete) {
      mkt.confirmDelete = true;
      renderBrief();
      return;
    }
    try {
      await api(`/api/market-scans/${mkt.current.id}`, undefined, "DELETE");
      mkt.scans = mkt.scans.filter((s) => s.id !== mkt.current.id);
      mkt.current = mkt.scans.length ? await api(`/api/market-scans/${mkt.scans[0].id}`) : null;
      toast("Market scan deleted");
    } catch (error) {
      toast(error.message);
    }
    mkt.confirmDelete = false;
    renderBrief();
  });
}

// ---------- project page ----------

function projectMarketSection() {
  return `<section class="section" aria-labelledby="pmarket-h">
    <div class="section-head">
      <h2 class="section-title" id="pmarket-h">Market scans</h2>
      <span class="count-text" id="pmarket-count"></span>
    </div>
    <div class="list-panel" id="pmarket-list"><p class="empty">Loading…</p></div>
  </section>`;
}

async function loadProjectMarket(project) {
  const list = document.getElementById("pmarket-list");
  if (!list) return;
  try {
    const scans = await api(`/api/market-scans?project_id=${encodeURIComponent(project.id)}`);
    if (!document.getElementById("pmarket-list")) return;
    document.getElementById("pmarket-count").textContent = `${scans.length} scan${scans.length === 1 ? "" : "s"}`;
    list.innerHTML = scans.length
      ? scans.map((s) => `<a class="list-row" href="#/brief/${esc(s.brief_id)}/market">
          <span><span class="title">${esc(s.query)}</span>
            <span class="meta">${[s.industry, MARKET_LENS_LABELS[s.lens], s.phrases.join(", "), formatDate(s.created_at)]
              .map((m) => `<span>${esc(m)}</span>`).join("")}</span></span>
          ${statusPill(s.status)}
        </a>`).join("")
      : '<p class="empty">No market scans yet. Open a brief in this project and use its Market tab.</p>';
  } catch (error) {
    list.innerHTML = `<p class="empty">${esc(error.message)}</p>`;
  }
}
