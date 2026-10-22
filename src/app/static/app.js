// Research Insight Agent UI: one page, two views (#/ ask, #/brief/<id>).
// All LLM output is HTML-escaped before it is formatted.

const AUDIENCES = {
  executive: {
    label: "Executive",
    hint: "Business leaders with no technical background: decisions, risk, cost, trust and reputation.",
  },
  risk: {
    label: "Risk & compliance",
    hint: "Risk, compliance and audit teams: controls, governance, testing, monitoring and what could go wrong.",
  },
  technical: {
    label: "Technical lead",
    hint: "Technical leads deciding whether to adopt: what to build or test, and how mature the methods are.",
  },
};

const STATUS = {
  draft: { pill: "Awaiting review", title: "Awaiting advisor review", sub: "Not for client use until a KPMG reviewer approves it." },
  approved: { pill: "Approved", title: "Approved", sub: "Reviewed and cleared for internal and client conversations." },
  changes: { pill: "Changes requested", title: "Changes requested", sub: "Sent back with reviewer notes. Regenerate the brief or ask a sharper question." },
};

const SUMMARY_LABELS = ["Research Objective", "Methodology", "Key Findings", "Limitations"];

const state = {
  info: null,
  audience: "executive",
  topK: 5,
  question: "",
  busy: false,
  error: "",
  record: null,      // brief currently open
  view: null,        // audience of the brief being shown
  tab: "brief",
  noteOpen: false,
};

const app = document.getElementById("app");

// ---------- helpers ----------

function esc(text) {
  return String(text ?? "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function baseId(id) {
  return String(id).trim().replace(/v\d+$/, "");
}

async function api(path, body) {
  const options = body === undefined
    ? {}
    : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const response = await fetch(path, options);
  let data = null;
  try { data = await response.json(); } catch { /* no body */ }
  if (!response.ok) {
    const detail = data && data.detail;
    throw new Error(typeof detail === "string" ? detail : `Request failed (${response.status})`);
  }
  return data;
}

function toast(message) {
  const el = document.getElementById("toast");
  el.textContent = message;
  el.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => el.classList.remove("show"), 2200);
}

function formatDate(iso, withYear = true) {
  if (!iso) return "";
  const date = new Date(iso.length === 10 ? iso + "T00:00:00Z" : iso);
  return date.toLocaleDateString("en-US", {
    month: "short", day: "numeric", ...(withYear ? { year: "numeric" } : {}), timeZone: "UTC",
  });
}

function icon(kind) {
  if (kind === "ok") {
    return '<svg width="22" height="22" viewBox="0 0 22 22" fill="none" stroke="#0B6B3A" stroke-width="2" aria-hidden="true"><circle cx="11" cy="11" r="9"></circle><path d="M7 11.5l3 3 5-6"></path></svg>';
  }
  const color = kind === "bad" ? "#A1251B" : "#8A4B08";
  return `<svg width="22" height="22" viewBox="0 0 22 22" fill="none" stroke="${color}" stroke-width="2" aria-hidden="true"><circle cx="11" cy="11" r="9"></circle><path d="M11 6v6M11 15.5v.5"></path></svg>`;
}

const ARROW = '<svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M3 9h12M10 4l5 5-5 5"></path></svg>';
const BACK = '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M13 8H3M7 4L3 8l4 4"></path></svg>';

// ---------- formatting LLM output ----------

// "[2609.38107v1]" or "[2609.38107v1, 2609.38108v1]" -> numbered links to the source cards
const CITE = /\[(\d{4}\.\d{4,5}(?:v\d+)?(?:\s*[,;]\s*\d{4}\.\d{4,5}(?:v\d+)?)*)\]/g;
const BARE_ID = /\b(\d{4}\.\d{4,5})(?:v\d+)?\b/g;

function citeLink(id, sources) {
  const index = sources.findIndex((s) => baseId(s.paper_id) === baseId(id));
  if (index === -1) {
    return `<span class="cite" style="color: var(--red)" title="Not in the retrieved papers">[${esc(id)}?]</span>`;
  }
  const title = esc(sources[index].title);
  return `<a class="cite" href="#src-${index + 1}" data-src="${index + 1}" title="${title} (${esc(baseId(id))})">[${index + 1}]</a>`;
}

function inline(text, sources) {
  // text is already escaped
  return text
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(CITE, (_, ids) => ids.split(/\s*[,;]\s*/).map((id) => citeLink(id, sources)).join(""));
}

// Split our fixed output format into [{heading, lines}] sections
function splitSections(text, labels) {
  const sections = [];
  let current = { heading: "", lines: [] };

  for (const raw of String(text || "").split("\n")) {
    const line = raw.trimEnd();
    const hashHeading = line.match(/^#{1,3}\s+(.+)$/);
    // Summaries write labels as "Key Findings:" or "**Key Findings:**"
    const plain = line.trim().replace(/\*\*/g, "");
    const label = labels && labels.find((l) => plain.toLowerCase().startsWith(l.toLowerCase() + ":"));

    if (hashHeading || label) {
      if (current.heading || current.lines.some((l) => l.trim())) sections.push(current);
      if (hashHeading) {
        current = { heading: hashHeading[1].replace(/\*\*/g, "").replace(/:$/, "").trim(), lines: [] };
      } else {
        const rest = plain.slice(label.length + 1).trim();
        current = { heading: label, lines: rest ? [rest] : [] };
      }
    } else {
      current.lines.push(line);
    }
  }
  if (current.heading || current.lines.some((l) => l.trim())) sections.push(current);
  return sections;
}

// Paragraphs and "- " bullet lists; wrapped lines join the item above
function renderBody(lines, sources) {
  const blocks = [];
  let block = null;

  const close = () => { if (block) blocks.push(block); block = null; };

  for (const raw of lines) {
    const line = raw.trim();
    if (!line) { close(); continue; }
    const bullet = line.match(/^[-*•]\s+(.*)$/) || line.match(/^\d+[.)]\s+(.*)$/);
    if (bullet) {
      if (!block || block.type !== "ul") { close(); block = { type: "ul", items: [] }; }
      block.items.push(bullet[1]);
    } else if (block && block.type === "ul") {
      block.items[block.items.length - 1] += " " + line;
    } else {
      if (!block) block = { type: "p", text: "" };
      block.text += (block.text ? " " : "") + line;
    }
  }
  close();

  return blocks.map((b) => b.type === "ul"
    ? "<ul>" + b.items.map((item) => `<li>${inline(esc(item), sources)}</li>`).join("") + "</ul>"
    : `<p>${inline(esc(b.text), sources)}</p>`).join("");
}

function renderSourcesSection(lines, sources) {
  const ids = [...new Set(lines.join(" ").match(BARE_ID) || [])];
  if (!ids.length) return renderBody(lines, sources);
  return "<p>" + ids.map((id) => `${citeLink(id, sources)} <span class="source-id">${esc(id)}</span>`).join(" &nbsp; ") + "</p>";
}

function renderDoc(text, sources, labels) {
  return splitSections(text, labels).map((section) => {
    const name = section.heading.toLowerCase();
    const cls = name === "bottom line" ? ' class="bottom-line"' : "";
    let body = name === "sources" ? renderSourcesSection(section.lines, sources) : renderBody(section.lines, sources);
    if (name === "evidence strength") {
      body = body.replace(/^<p>(High|Medium|Low)([.:]?)/, "<p><strong>$1$2</strong>");
    }
    const heading = section.heading ? `<h2>${esc(section.heading)}</h2>` : "";
    return `<section${cls}>${heading}${body}</section>`;
  }).join("");
}

// ---------- ask view ----------

function exampleCards() {
  const examples = (state.info && state.info.examples) || [];
  if (!examples.length) return "";
  return `
    <section class="stack" aria-labelledby="examples-h">
      <h2 id="examples-h" class="eyebrow">Try a question from our benchmark</h2>
      <div class="grid">
        ${examples.map((q, i) => `<button type="button" class="example" data-example="${i}">${esc(q)}</button>`).join("")}
      </div>
    </section>`;
}

const HOW = [
  ["01 · Retrieve", "Find the best papers", "Hybrid keyword and meaning search over every chunk, ranked into the top papers."],
  ["02 · Summarize", "Stick to the sources", "Objective, method, findings and limitations, using only the retrieved papers."],
  ["03 · Translate", "Turn findings into a brief", "Bottom line, why it matters, what to do, evidence strength, caveat and sources."],
  ["04 · Check", "Verify, then review", "Every citation is checked against what was retrieved, then an advisor approves it."],
];

function progressList() {
  return `<ol class="progress" id="progress" aria-label="Progress">
    ${HOW.map(([num, title], i) => `<li data-step="${i}"><span class="dot"></span>${esc(num.split(" · ")[1])}: ${esc(title)}</li>`).join("")}
  </ol>`;
}

function renderAsk(scrollTo) {
  const audience = AUDIENCES[state.audience];

  app.className = "page";
  app.innerHTML = `
    <section class="hero">
      <h1>What does recent AI research mean for your business?</h1>
      <p>Ask in plain English. The agent finds the most relevant new arXiv papers, summarizes them with citations, and turns the findings into a business brief that a KPMG advisor reviews before it’s used.</p>
    </section>

    <form class="card ask-card" id="ask-form" aria-label="Ask a question">
      <div class="field">
        <label for="question" class="field-label">Your question</label>
        <textarea id="question" rows="3" placeholder="e.g., How can companies check AI models for bias before deploying them?">${esc(state.question)}</textarea>
      </div>

      <div class="field">
        <span id="aud-label" class="field-label">Write the brief for</span>
        <div role="group" aria-labelledby="aud-label" class="pills">
          ${Object.entries(AUDIENCES).map(([id, a]) =>
            `<button type="button" class="pill" data-audience="${id}" aria-pressed="${id === state.audience}">${esc(a.label)}</button>`).join("")}
        </div>
        <p class="hint">${esc(audience.hint)}</p>
      </div>

      <div class="ask-footer">
        <div class="field" style="gap: 6px">
          <label for="topk" class="small-label">Papers per answer</label>
          <select id="topk">
            ${[3, 5].map((k) => `<option value="${k}"${k === state.topK ? " selected" : ""}>${k}</option>`).join("")}
          </select>
        </div>
        <button type="submit" class="primary" id="generate"${state.busy ? " disabled" : ""}>
          ${state.busy ? "Generating…" : "Generate brief"} ${ARROW}
        </button>
      </div>

      ${state.busy ? progressList() : ""}
      ${state.error ? `<p class="error" role="alert">${esc(state.error)}</p>` : ""}
    </form>

    ${exampleCards()}

    <section id="how" class="stack" aria-labelledby="how-h">
      <h2 id="how-h" class="eyebrow">How every answer is built</h2>
      <ol class="steps">
        ${HOW.map(([num, title, text]) => `<li>
          <span class="step-num">${esc(num)}</span>
          <span class="step-title">${esc(title)}</span>
          <span class="step-text">${esc(text)}</span>
        </li>`).join("")}
      </ol>
    </section>

    <section id="recent" class="stack" aria-labelledby="recent-h">
      <h2 id="recent-h" class="eyebrow">Recent briefs</h2>
      <div class="recent" id="recent-list"><p class="empty">Loading…</p></div>
    </section>`;

  const form = document.getElementById("ask-form");
  const textarea = document.getElementById("question");

  textarea.addEventListener("input", () => { state.question = textarea.value; });
  textarea.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) form.requestSubmit();
  });
  document.getElementById("topk").addEventListener("change", (e) => { state.topK = Number(e.target.value); });
  form.querySelectorAll("[data-audience]").forEach((button) =>
    button.addEventListener("click", () => {
      state.audience = button.dataset.audience;
      form.querySelectorAll("[data-audience]").forEach((b) => b.setAttribute("aria-pressed", String(b === button)));
      form.querySelector(".hint").textContent = AUDIENCES[state.audience].hint;
    }));
  form.addEventListener("submit", (e) => { e.preventDefault(); ask(); });
  app.querySelectorAll("[data-example]").forEach((button) =>
    button.addEventListener("click", () => {
      state.question = state.info.examples[Number(button.dataset.example)];
      textarea.value = state.question;
      ask();
    }));

  loadRecent();

  if (scrollTo) document.getElementById(scrollTo)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function loadRecent() {
  const list = document.getElementById("recent-list");
  if (!list) return;
  try {
    const briefs = await api("/api/briefs");
    if (!briefs.length) {
      list.innerHTML = '<p class="empty">No briefs yet. Ask a question to create the first one.</p>';
      return;
    }
    list.innerHTML = briefs.map((b) => {
      const status = STATUS[b.status] || STATUS.draft;
      return `<a href="#/brief/${esc(b.id)}">
        <span class="recent-q">${esc(b.query)}</span>
        <span class="recent-meta">
          <span>${esc(formatDate(b.created_at))}</span>
          <span class="status-pill status-${esc(b.status)}">${esc(status.pill)}</span>
        </span>
      </a>`;
    }).join("");
  } catch (error) {
    list.innerHTML = `<p class="empty">Couldn’t load saved briefs: ${esc(error.message)}</p>`;
  }
}

// Steps light up on a rough timer; the server answers in one go
function animateProgress() {
  const times = [0, 2000, 14000];
  const timers = times.map((t, i) => setTimeout(() => {
    document.querySelectorAll("#progress li").forEach((li) => {
      const step = Number(li.dataset.step);
      li.classList.toggle("done", step < i);
      li.classList.toggle("active", step === i);
    });
  }, t));
  return () => timers.forEach(clearTimeout);
}

async function ask() {
  const question = state.question.trim();
  if (!question) {
    state.error = "Please type a question.";
    renderAsk();
    document.getElementById("question").focus();
    return;
  }
  if (state.busy) return;

  state.busy = true;
  state.error = "";
  renderAsk();
  document.getElementById("ask-form").scrollIntoView({ behavior: "smooth", block: "start" });
  const stop = animateProgress();

  try {
    const record = await api("/api/ask", { question, audience: state.audience, top_k: state.topK });
    state.busy = false;
    state.question = "";
    stop();
    location.hash = `#/brief/${record.id}`;
  } catch (error) {
    stop();
    state.busy = false;
    state.error = error.message;
    renderAsk();
  }
}

// ---------- brief view ----------

function currentBrief() {
  const record = state.record;
  return record.briefs[state.view] || null;
}

function checkCards(entry) {
  if (!entry) {
    return `<div class="check">${icon("warn")}<div class="check-text">
      <span class="check-title">No brief</span>
      <span class="check-sub">No relevant papers were found, so there was nothing to translate.</span></div></div>`;
  }
  const c = entry.checks;
  const cards = [];

  const bad = [...c.citations.cited_not_retrieved, ...c.citations.cited_not_in_summary];
  cards.push(c.citations.ok
    ? [icon("ok"), "Citations verified", "Every cited paper was actually retrieved."]
    : [icon("bad"), "Citation problem", `Cites papers it shouldn’t: ${bad.join(", ")}.`]);

  const t = c.template;
  cards.push(t.ok
    ? [icon("ok"), "Template check passed", `All ${t.sections} sections, ${t.words} words (limit ${t.max_words}).`]
    : [icon("warn"), "Template check failed",
       t.headings_ok ? `${t.words} words, over the ${t.max_words} limit.` : `Sections don’t match the ${t.sections}-section template.`]);

  const e = c.evidence;
  cards.push(e.level
    ? [icon(e.level === "High" ? "ok" : "warn"), `Evidence: ${e.level}`, e.reason || "See Evidence Strength below."]
    : [icon("warn"), "Evidence: not rated", "The brief didn’t give an evidence rating."]);

  if (c.summary_truncated || c.brief_truncated) {
    cards.push([icon("bad"), "Output cut off", "The model hit its token limit. Regenerate before using this."]);
  }

  return cards.map(([svg, title, sub]) => `<div class="check">${svg}<div class="check-text">
    <span class="check-title">${esc(title)}</span><span class="check-sub">${esc(sub)}</span></div></div>`).join("");
}

function sourceCards(record, cited) {
  if (!record.sources.length) return '<p class="hint">No papers were retrieved.</p>';
  return record.sources.map((s, i) => {
    const isCited = cited.has(baseId(s.paper_id));
    return `<div class="source" id="src-${i + 1}">
      <div class="source-top">
        <span class="source-id">[${i + 1}] ${esc(baseId(s.paper_id))}</span>
        <span class="tag ${isCited ? "tag-cited" : "tag-uncited"}">${isCited ? "Cited" : "Not cited"}</span>
      </div>
      <span class="source-title">${esc(s.title)}</span>
      ${s.section ? `<span class="source-section">Matched in: ${esc(s.section)}</span>` : ""}
      <a href="${esc(s.arxiv_url)}" target="_blank" rel="noopener">Open on arXiv</a>
    </div>`;
  }).join("");
}

function reviewBanner(record) {
  const status = STATUS[record.status] || STATUS.draft;
  const hasBrief = !!currentBrief();
  const noteForm = state.noteOpen ? `
    <form class="note-box" id="note-form">
      <label for="note" class="small-label">What should change? (optional)</label>
      <textarea id="note" rows="2" placeholder="e.g., Focus on banking clients; the second recommendation is too generic."></textarea>
      <div class="review-actions">
        <button type="submit" class="secondary">Send back</button>
        <button type="button" class="secondary" id="note-cancel">Cancel</button>
      </div>
    </form>` : "";

  return `<section class="review status-${esc(record.status)}" aria-label="Review status">
    <div class="review-text">
      <span class="review-title">${esc(status.title)}</span>
      <span class="review-sub">${esc(status.sub)}</span>
      ${record.note ? `<p class="note"><strong>Reviewer note:</strong> ${esc(record.note)}</p>` : ""}
    </div>
    ${hasBrief && !state.noteOpen ? `<div class="review-actions">
      ${record.status === "changes" ? `<button type="button" class="secondary" data-rewrite="${esc(state.view)}">Regenerate brief</button>` : ""}
      ${record.status !== "changes" ? '<button type="button" class="secondary" id="request-changes">Request changes</button>' : ""}
      ${record.status !== "approved" ? '<button type="button" class="secondary approve" id="approve">Approve brief</button>' : ""}
    </div>` : ""}
    ${noteForm}
  </section>`;
}

function renderBrief() {
  const record = state.record;
  const entry = currentBrief();
  const audience = AUDIENCES[state.view] || { label: state.view };

  const cited = new Set([
    ...record.citation_check.cited,
    ...(entry ? entry.citation_check.cited : []),
  ].map(baseId));

  const others = Object.keys(AUDIENCES).filter((a) => a !== state.view);

  const briefTab = entry ? `
    <div class="doc">${renderDoc(entry.brief, record.sources)}</div>
    <div class="doc-actions">
      <button type="button" class="secondary" id="print">Export PDF</button>
      <button type="button" class="secondary" id="copy">Copy link</button>
      ${others.map((a) => record.briefs[a]
        ? `<button type="button" class="secondary" data-view="${a}">View ${esc(AUDIENCES[a].label)} brief</button>`
        : `<button type="button" class="secondary" data-rewrite="${a}">Rewrite for ${esc(AUDIENCES[a].label)}</button>`).join("")}
    </div>`
    : `<div class="doc"><section><p>${esc(record.summary)}</p></section></div>`;

  const summaryTab = `
    <p class="lead">The facts the brief is built from, written only from the retrieved papers. The brief is generated from this summary alone, so it can’t add anything the summary doesn’t say.</p>
    <div class="doc">${renderDoc(record.summary, record.sources, SUMMARY_LABELS)}</div>`;

  app.className = "page brief-page";
  app.innerHTML = `
    <a class="back" href="#/">${BACK} New question</a>

    <section class="brief-head">
      <h1>${esc(record.query)}</h1>
      <div class="meta">
        <span>Written for: <strong>${esc(audience.label)}</strong></span>
        <span>${record.sources.length} papers retrieved</span>
        <span>Model: ${esc(record.model)}</span>
        <span>${esc(formatDate(record.created_at))}</span>
      </div>
    </section>

    ${reviewBanner(record)}

    <section class="checks" aria-label="Automatic checks">${checkCards(entry)}</section>

    ${state.error ? `<p class="error" role="alert">${esc(state.error)}</p>` : ""}

    <div class="brief-layout">
      <article class="card brief-card">
        <div class="tabs" role="group" aria-label="View">
          <button type="button" class="tab" data-tab="brief" aria-pressed="${state.tab === "brief"}">Business brief</button>
          <button type="button" class="tab" data-tab="summary" aria-pressed="${state.tab === "summary"}">Research summary</button>
        </div>
        ${state.tab === "brief" ? briefTab : summaryTab}
      </article>
      <aside class="card sources" aria-labelledby="sources-h">
        <div class="sources-head"><h2 id="sources-h">Sources</h2><span>Ranked by relevance</span></div>
        ${sourceCards(record, cited)}
      </aside>
    </div>`;

  bindBrief();
}

function bindBrief() {
  const on = (selector, handler) => app.querySelectorAll(selector).forEach((el) => el.addEventListener("click", handler));

  on("[data-tab]", (e) => { state.tab = e.currentTarget.dataset.tab; renderBrief(); });
  on("[data-view]", (e) => { state.view = e.currentTarget.dataset.view; state.tab = "brief"; renderBrief(); });
  on("[data-rewrite]", (e) => rewrite(e.currentTarget.dataset.rewrite, e.currentTarget));
  on("#approve", () => setStatus("approved"));
  on("#request-changes", () => { state.noteOpen = true; renderBrief(); document.getElementById("note").focus(); });
  on("#note-cancel", () => { state.noteOpen = false; renderBrief(); });
  on("#print", () => window.print());
  on("#copy", async () => {
    try { await navigator.clipboard.writeText(location.href); toast("Link copied"); }
    catch { toast("Copy this link from the address bar"); }
  });

  // Citation links scroll to the source card without changing the route
  on("[data-src]", (e) => {
    e.preventDefault();
    const card = document.getElementById("src-" + e.currentTarget.dataset.src);
    if (!card) return;
    card.scrollIntoView({ behavior: "smooth", block: "center" });
    card.classList.add("flash");
    setTimeout(() => card.classList.remove("flash"), 1500);
  });

  const noteForm = document.getElementById("note-form");
  if (noteForm) {
    noteForm.addEventListener("submit", (e) => {
      e.preventDefault();
      setStatus("changes", document.getElementById("note").value);
    });
  }
}

async function setStatus(status, note = "") {
  try {
    state.record = await api(`/api/briefs/${state.record.id}/status`, { status, note });
    state.noteOpen = false;
    state.error = "";
    toast(status === "approved" ? "Brief approved" : "Sent back for changes");
  } catch (error) {
    state.error = error.message;
  }
  renderBrief();
}

async function rewrite(audience, button) {
  button.disabled = true;
  button.textContent = "Writing…";
  try {
    state.record = await api(`/api/briefs/${state.record.id}/rewrite`, { audience });
    state.view = audience;
    state.tab = "brief";
    state.error = "";
  } catch (error) {
    state.error = error.message;
  }
  renderBrief();
}

async function openBrief(id) {
  app.className = "page brief-page";
  app.innerHTML = '<p class="hint">Loading brief…</p>';
  try {
    state.record = await api(`/api/briefs/${encodeURIComponent(id)}`);
    state.view = state.record.audience;
    state.tab = "brief";
    state.noteOpen = false;
    state.error = "";
    renderBrief();
  } catch (error) {
    app.innerHTML = `<a class="back" href="#/">${BACK} New question</a><p class="error" role="alert">${esc(error.message)}</p>`;
  }
}

// ---------- routing ----------

function route() {
  const hash = location.hash || "#/";
  const brief = hash.match(/^#\/brief\/(.+)$/);
  const page = brief ? "brief" : hash === "#/saved" ? "saved" : hash === "#/how" ? "how" : "ask";

  document.querySelectorAll("[data-nav]").forEach((a) => a.classList.toggle("active", a.dataset.nav === page));

  if (brief) {
    openBrief(brief[1]);
  } else {
    state.error = "";
    renderAsk(page === "saved" ? "recent" : page === "how" ? "how" : null);
    if (page === "ask") window.scrollTo(0, 0);
  }
}

async function init() {
  try {
    state.info = await api("/api/info");
    const c = state.info.corpus;
    if (c && c.papers) {
      document.getElementById("corpus-text").textContent =
        `${c.papers.toLocaleString("en-US")} papers indexed · ${formatDate(c.first_date, false)} – ${formatDate(c.last_date)}`;
    }
    if (state.info.default_audience) state.audience = state.info.default_audience;
  } catch {
    document.getElementById("corpus-text").textContent = "Server not reachable";
  }
  route();
}

window.addEventListener("hashchange", route);
init();
