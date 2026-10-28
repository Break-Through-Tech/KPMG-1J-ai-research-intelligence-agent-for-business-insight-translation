// Research Insight Agent UI: one page, hash routes
//   #/            Home (ask a question)
//   #/brief/<id>  a saved brief (Brief / Research summary / Sources / Review tabs);
//                 #/brief/<id>/review opens a tab directly
//   #/research    the most recent brief
//   #/library     every saved brief
//   #/review      briefs waiting for review or with changes requested
// All LLM output is HTML-escaped before it is formatted.

const AUDIENCES = {
  executive: {
    label: "Executive",
    hint: "Executive: decisions, business risk, cost, trust and reputation, with no technical background assumed.",
  },
  risk: {
    label: "Risk & compliance",
    hint: "Risk & compliance: controls, governance, testing, monitoring and what could go wrong.",
  },
  technical: {
    label: "Technical lead",
    hint: "Technical lead: what to build or test, and how mature the methods are.",
  },
};

const STATUS = {
  draft: { pill: "Awaiting review", cls: "status--review", sub: "Not for client use until a KPMG reviewer approves it." },
  approved: { pill: "Approved", cls: "status--ok", sub: "Reviewed and cleared for internal and client conversations." },
  changes: { pill: "Changes requested", cls: "status--changes", sub: "Sent back with reviewer notes. Regenerate the brief or ask a sharper question." },
};

// arXiv primary categories shown as topic filters, in plain words
const TOPIC_LABELS = {
  "cs.AI": "AI",
  "cs.CL": "Language",
  "cs.LG": "Machine learning",
  "cs.CV": "Vision",
  "cs.CR": "Security",
  "cs.RO": "Robotics",
  "cs.SE": "Software engineering",
  "cs.HC": "Human–computer",
  "cs.IR": "Search & retrieval",
  "cs.MA": "Multi-agent",
  "cs.CY": "Society",
  "stat.ML": "Statistics ML",
  "cs.SD": "Sound",
};
const MAX_TOPICS = 8;

const PUBLISHED = [
  ["any", "Any time"],
  ["7", "Last 7 days"],
  ["14", "Last 14 days"],
  ["custom", "Since a date…"],
];

const SUMMARY_LABELS = ["Research Objective", "Methodology", "Key Findings", "Limitations"];

const TABS = [
  ["brief", "Brief"],
  ["summary", "Research summary"],
  ["sources", "Sources"],
  ["review", "Review"],
];

const state = {
  info: null,
  audience: "executive",
  topK: 5,
  question: "",
  filters: { published: "any", since: "", categories: [] },
  busy: false,
  error: "",
  autoAsk: false,     // ask as soon as Home renders (search from the brief page)
  briefs: [],         // saved brief list, for the review count and Research link
  record: null,       // brief currently open
  view: null,         // audience of the brief being shown
  tab: "brief",
  followup: "",
  followupBusy: false,
};

const app = document.getElementById("app");
const topbar = document.getElementById("topbar");

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

async function copyText(text, done) {
  try {
    await navigator.clipboard.writeText(text);
    toast(done);
  } catch {
    toast("Couldn’t reach the clipboard. Try again from a focused tab.");
  }
}

function formatDate(iso, withYear = true) {
  if (!iso) return "";
  const date = new Date(iso.length === 10 ? iso + "T00:00:00Z" : iso);
  return date.toLocaleDateString("en-US", {
    month: "short", day: "numeric", ...(withYear ? { year: "numeric" } : {}), timeZone: "UTC",
  });
}

function corpus() {
  return (state.info && state.info.corpus) || {};
}

function indexedText(long = true) {
  const c = corpus();
  if (!c.papers) return state.info ? "Corpus not loaded" : "Loading…";
  const count = `${c.papers.toLocaleString("en-US")} papers indexed${long ? " from arXiv" : ""}`;
  return long ? `${count} · ${formatDate(c.first_date, false)} – ${formatDate(c.last_date)}` : count;
}

function topicLabel(id) {
  return TOPIC_LABELS[id] || id;
}

function icon(kind) {
  if (kind === "ok") {
    return '<svg viewBox="0 0 22 22" fill="none" stroke="#0B6B3A" stroke-width="2" aria-hidden="true"><circle cx="11" cy="11" r="9"></circle><path d="M7 11.5l3 3 5-6"></path></svg>';
  }
  const color = kind === "bad" ? "#A1251B" : "#8A4B08";
  return `<svg viewBox="0 0 22 22" fill="none" stroke="${color}" stroke-width="2" aria-hidden="true"><circle cx="11" cy="11" r="9"></circle><path d="M11 6v6M11 15.5v.5"></path></svg>`;
}

const ARROW = '<svg viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M3 9h12M10 4l5 5-5 5"></path></svg>';
const SEARCH = (cls) => `<svg class="search-icon ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/></svg>`;

// ---------- filters ----------

// {since, categories} for /api/ask; "Last 7 days" counts back from the newest paper, not today
function filterPayload() {
  const f = state.filters;
  let since = null;

  if (f.published === "custom") {
    since = f.since || null;
  } else if (f.published !== "any" && corpus().last_date) {
    const date = new Date(corpus().last_date + "T00:00:00Z");
    date.setUTCDate(date.getUTCDate() - (Number(f.published) - 1));
    since = date.toISOString().slice(0, 10);
  }

  return { since, categories: [...f.categories] };
}

function filtersText(filters) {
  if (!filters) return "";
  const parts = [];
  if (filters.since) parts.push(`Since ${formatDate(filters.since, false)}`);
  if (filters.until) parts.push(`Until ${formatDate(filters.until, false)}`);
  if (filters.categories && filters.categories.length) parts.push(filters.categories.map(topicLabel).join(", "));
  return parts.join(" · ");
}

// ---------- formatting LLM output ----------

// "[2609.38107v1]" or "[2609.38107v1, 2609.38108v1]" -> numbered links to the source cards
const CITE = /\[(\d{4}\.\d{4,5}(?:v\d+)?(?:\s*[,;]\s*\d{4}\.\d{4,5}(?:v\d+)?)*)\]/g;
const BARE_ID = /\b(\d{4}\.\d{4,5})(?:v\d+)?\b/g;

function sourceNumber(id, sources) {
  return sources.findIndex((s) => baseId(s.paper_id) === baseId(id)) + 1;
}

function citeLink(id, sources) {
  const n = sourceNumber(id, sources);
  if (!n) {
    return `<span class="cite cite--missing" title="Not in the retrieved papers">[${esc(id)}?]</span>`;
  }
  const title = esc(sources[n - 1].title);
  return `<a class="cite" href="#src-${n}" data-src="${n}" title="${title} (${esc(baseId(id))})">[${n}]</a>`;
}

// The ids inside one [...] group, without repeats
function citeIds(group) {
  const seen = new Set();
  return group.split(/\s*[,;]\s*/).filter((id) => !seen.has(baseId(id)) && seen.add(baseId(id)));
}

function inline(text, sources) {
  // text is already escaped
  return text
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(CITE, (_, ids) => citeIds(ids).map((id) => citeLink(id, sources)).join(""));
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
function blocksOf(lines) {
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
  return blocks;
}

function renderBody(lines, sources) {
  return blocksOf(lines).map((b) => b.type === "ul"
    ? "<ul>" + b.items.map((item) => `<li>${inline(esc(item), sources)}</li>`).join("") + "</ul>"
    : `<p>${inline(esc(b.text), sources)}</p>`).join("");
}

function renderSourcesSection(lines, sources) {
  const ids = [...new Set(lines.join(" ").match(BARE_ID) || [])];
  if (!ids.length) return renderBody(lines, sources);
  return `<p class="source-id-list">${ids.map((id) => `${citeLink(id, sources)} ${esc(id)}`).join(" &nbsp; ")}</p>`;
}

function meter(level) {
  const index = ["Low", "Medium", "High"].indexOf(level);
  if (index === -1) return "";
  return `<div class="meter" role="img" aria-label="Evidence strength: ${esc(level)}, on a scale of Low, Medium, High">
    <div class="meter-bars">${[0, 1, 2].map((i) => `<span${i <= index ? ' class="on"' : ""}></span>`).join("")}</div>
    <div class="meter-labels">${["Low", "Medium", "High"].map((l, i) => `<span${i === index ? ' class="on"' : ""}>${l}</span>`).join("")}</div>
  </div>`;
}

function renderDoc(text, sources, labels, evidenceLevel) {
  return splitSections(text, labels).map((section) => {
    const name = section.heading.toLowerCase();
    const cls = name === "bottom line" ? ' class="bottom-line"' : "";
    let body = name === "sources" ? renderSourcesSection(section.lines, sources) : renderBody(section.lines, sources);
    if (name === "evidence strength") {
      body = meter(evidenceLevel) + body.replace(/^<p>(High|Medium|Low)([.:]?)/, "<p><strong>$1$2</strong>");
    }
    const heading = section.heading ? `<h2>${esc(section.heading)}</h2>` : "";
    return `<section${cls}>${heading}${body}</section>`;
  }).join("");
}

// Bottom Line as plain text, for the page lede
function bottomLine(brief) {
  const section = splitSections(brief).find((s) => s.heading.toLowerCase() === "bottom line");
  if (!section) return "";
  return section.lines.join(" ").replace(CITE, "").replace(/\*\*/g, "").replace(/\s+/g, " ").trim();
}

// ---------- copy for email / Slack ----------

function briefAsText(record, entry, format) {
  const slack = format === "slack";
  const sources = record.sources;

  const clean = (text) => text
    .replace(CITE, (_, ids) => citeIds(ids).map((id) => {
      const n = sourceNumber(id, sources);
      return n ? `[${n}]` : `[${id}]`;
    }).join(""))
    .replace(/\*\*(.+?)\*\*/g, slack ? "*$1*" : "$1");

  const heading = (text) => (slack ? `*${text}*` : text.toUpperCase());
  const out = [];

  out.push(slack ? `*${record.query}*` : record.query);
  if (record.status !== "approved") out.push("Draft, awaiting KPMG review. Not for client use.");
  out.push(`Written for: ${(AUDIENCES[state.view] || { label: state.view }).label}`);

  for (const section of splitSections(entry.brief)) {
    if (section.heading.toLowerCase() === "sources") continue;
    out.push("");
    if (section.heading) out.push(heading(section.heading));
    for (const block of blocksOf(section.lines)) {
      if (block.type === "ul") block.items.forEach((item) => out.push(`${slack ? "•" : "-"} ${clean(item)}`));
      else out.push(clean(block.text));
    }
  }

  const cited = new Set(entry.citation_check.cited.map(baseId));
  const list = sources.map((s, i) => [s, i + 1]).filter(([s]) => cited.has(baseId(s.paper_id)));
  if (list.length) {
    out.push("", heading("Sources"));
    list.forEach(([s, n]) => out.push(slack ? `[${n}] <${s.arxiv_url}|${s.title}>` : `[${n}] ${s.title}, ${s.arxiv_url}`));
  }

  return out.join("\n");
}

// ---------- shell ----------

function setNav(page) {
  document.querySelectorAll("[data-nav]").forEach((a) => {
    if (a.dataset.nav === page) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
}

function topbarTitle(title) {
  topbar.className = "topbar";
  topbar.innerHTML = `<p class="topbar-title">${esc(title)}</p>
    <p class="indexed"><span class="dot" aria-hidden="true"></span>${esc(indexedText(false))}</p>`;
}

function topbarSearch() {
  topbar.className = "topbar topbar--white";
  topbar.innerHTML = `
    <form class="search search--compact" id="quick-form" role="search">
      ${SEARCH("")}
      <label for="quick-q" class="sr-only">New research question</label>
      <input id="quick-q" type="text" placeholder="Search Research Topic" autocomplete="off">
      <button class="btn-research" type="submit">Research ${ARROW}</button>
    </form>
    <p class="indexed"><span class="dot" aria-hidden="true"></span>${esc(indexedText(false))}</p>`;

  document.getElementById("quick-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const question = document.getElementById("quick-q").value.trim();
    if (!question) return;
    state.question = question;
    state.autoAsk = true;
    location.hash = "#/";
  });
}

async function refreshBriefs() {
  try {
    state.briefs = await api("/api/briefs?limit=500");
  } catch {
    return;
  }
  const waiting = state.briefs.filter((b) => b.status !== "approved").length;
  const badge = document.getElementById("review-count");
  badge.hidden = !waiting;
  badge.textContent = waiting;
  badge.setAttribute("aria-label", `${waiting} waiting`);
}

function statusPill(status) {
  const s = STATUS[status] || STATUS.draft;
  return `<span class="status ${s.cls}">${esc(s.pill)}</span>`;
}

function listRows(briefs) {
  return briefs.map((b) => {
    const meta = [
      (AUDIENCES[b.audience] || { label: b.audience || "" }).label,
      b.evidence ? `Evidence: ${b.evidence}` : "",
      b.papers !== undefined ? `${b.papers} papers` : "",
      formatDate(b.created_at),
    ].filter(Boolean).join(" · ");
    return `<a class="list-row" href="#/brief/${esc(b.id)}">
      <span><span class="title">${esc(b.query)}</span><span class="meta">${esc(meta)}</span></span>
      ${statusPill(b.status)}
    </a>`;
  }).join("");
}

// ---------- Home ----------

const HOW = [
  ["RETRIEVE", "Find the best papers", "Hybrid keyword and meaning search over every chunk, ranked into the top papers."],
  ["SUMMARIZE", "Stick to the sources", "Objective, method, findings and limitations, using only the retrieved papers."],
  ["TRANSLATE", "Turn findings into a brief", "Bottom line, why it matters, what to do, evidence strength, caveat and sources."],
  ["CHECK", "Verify, then review", "Every citation is checked against what was retrieved, then a KPMG advisor approves it."],
];

function progressList() {
  return `<ol class="progress" id="progress" aria-label="Progress">
    ${HOW.map(([kicker, title], i) => `<li data-step="${i}"><span class="dot"></span>${esc(kicker[0] + kicker.slice(1).toLowerCase())}: ${esc(title)}</li>`).join("")}
  </ol>`;
}

function topicChips() {
  const categories = (corpus().categories || []).slice(0, MAX_TOPICS);
  if (!categories.length) return "";
  const selected = new Set(state.filters.categories);
  return `<div class="topics">
    <div class="chip-row" role="group" aria-labelledby="topic-label">
      <span class="control-label" id="topic-label">Topics</span>
      <button type="button" class="chip chip--small" data-topic="" aria-pressed="${!selected.size}">All topics</button>
      ${categories.map((c) => `<button type="button" class="chip chip--small" data-topic="${esc(c.id)}"
        aria-pressed="${selected.has(c.id)}" title="${esc(c.id)} · ${c.papers.toLocaleString("en-US")} papers">${esc(topicLabel(c.id))}</button>`).join("")}
    </div>
  </div>`;
}

function renderHome(scrollTo) {
  const c = corpus();
  const f = state.filters;
  setNav("home");
  topbarTitle("RESEARCH WORKSPACE");

  const examples = (state.info && state.info.examples) || [];
  const recent = state.briefs.slice(0, 5);

  app.className = "";
  app.innerHTML = `
    <section class="hero" aria-labelledby="hero-h">
      <div class="hero-inner">
        <div class="hero-head">
          <h1 id="hero-h">What Do You Want to Understand?</h1>
          <p class="hero-sub">Ask a research question, search through recent papers, and receive a concise summary and business brief with sources.</p>
        </div>

        <form class="search search--hero" id="ask-form" role="search">
          ${SEARCH("")}
          <label for="question" class="sr-only">Research question</label>
          <textarea id="question" rows="1" placeholder="Search Research Topic">${esc(state.question)}</textarea>
          <button class="btn-research" type="submit" id="generate"${state.busy ? " disabled" : ""}>
            ${state.busy ? "Researching…" : "Research"} ${ARROW}
          </button>
        </form>

        <p class="indexed"><span class="dot" aria-hidden="true"></span>${esc(indexedText())}</p>
        ${state.busy ? progressList() : ""}
        ${state.error ? `<p class="error" role="alert">${esc(state.error)}</p>` : ""}

        <div class="hero-controls">
          <div class="chip-row" role="group" aria-labelledby="aud-label">
            <span class="control-label" id="aud-label">Write the brief for</span>
            ${Object.entries(AUDIENCES).map(([id, a]) =>
              `<button type="button" class="chip" data-audience="${id}" aria-pressed="${id === state.audience}">${esc(a.label)}</button>`).join("")}
          </div>
          <div class="filters">
            <label for="published" class="sr-only">Published</label>
            <select id="published" class="select">
              ${PUBLISHED.map(([v, l]) => `<option value="${v}"${v === f.published ? " selected" : ""}>${l}</option>`).join("")}
            </select>
            ${f.published === "custom" ? `<label for="since" class="sr-only">Published since</label>
              <input id="since" type="date" class="date-input" value="${esc(f.since)}"
                ${c.first_date ? `min="${esc(c.first_date)}"` : ""} ${c.last_date ? `max="${esc(c.last_date)}"` : ""}>` : ""}
            <label for="topk" class="sr-only">Papers per answer</label>
            <select id="topk" class="select">
              ${[5, 3].map((k) => `<option value="${k}"${k === state.topK ? " selected" : ""}>${k} papers</option>`).join("")}
            </select>
          </div>
        </div>
        <p class="hint-on-blue" id="aud-hint" aria-live="polite">${esc(AUDIENCES[state.audience].hint)}</p>
        ${topicChips()}
      </div>
    </section>

    <div class="content">
      ${examples.length ? `<section class="section" aria-labelledby="examples-h">
        <h2 class="eyebrow" id="examples-h">Try a question from our benchmark</h2>
        <div class="grid-cards">
          ${examples.map((q, i) => `<button type="button" class="q-card" data-example="${i}">
            <span class="q">${esc(q)}</span>
            <span class="go">Generate the brief ${ARROW}</span>
          </button>`).join("")}
        </div>
      </section>` : ""}

      <section class="section" id="how" aria-labelledby="how-h">
        <h2 class="eyebrow" id="how-h">How every answer is built</h2>
        <ol class="steps">
          ${HOW.map(([kicker, title, text], i) => `<li class="step">
            <span class="step-head"><span class="step-num">${i + 1}</span><span class="step-kicker">${kicker}</span></span>
            <strong>${esc(title)}</strong>
            <p>${esc(text)}</p>
          </li>`).join("")}
        </ol>
      </section>

      <section class="section" id="recent" aria-labelledby="recent-h">
        <div class="section-head">
          <h2 class="eyebrow" id="recent-h">Recent briefs</h2>
          ${state.briefs.length > recent.length ? '<a href="#/library">See all in the Library</a>' : ""}
        </div>
        <div class="list-panel">
          ${recent.length ? listRows(recent) : '<p class="empty">No briefs yet. Ask a question to create the first one.</p>'}
        </div>
      </section>
    </div>`;

  bindHome();

  if (scrollTo) document.getElementById(scrollTo)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function bindHome() {
  const form = document.getElementById("ask-form");
  const textarea = document.getElementById("question");

  const grow = () => { textarea.style.height = "auto"; textarea.style.height = textarea.scrollHeight + "px"; };
  grow();
  textarea.addEventListener("input", () => { state.question = textarea.value; grow(); });
  textarea.addEventListener("keydown", (e) => {
    // Enter asks; Shift+Enter adds a new line
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); }
  });
  form.addEventListener("submit", (e) => { e.preventDefault(); ask(); });

  app.querySelectorAll("[data-audience]").forEach((button) =>
    button.addEventListener("click", () => {
      state.audience = button.dataset.audience;
      app.querySelectorAll("[data-audience]").forEach((b) => b.setAttribute("aria-pressed", String(b === button)));
      document.getElementById("aud-hint").textContent = AUDIENCES[state.audience].hint;
    }));

  document.getElementById("topk").addEventListener("change", (e) => { state.topK = Number(e.target.value); });
  document.getElementById("published").addEventListener("change", (e) => {
    state.filters.published = e.target.value;
    renderHome();
    if (e.target.value === "custom") document.getElementById("since")?.focus();
  });
  document.getElementById("since")?.addEventListener("change", (e) => { state.filters.since = e.target.value; });

  app.querySelectorAll("[data-topic]").forEach((button) =>
    button.addEventListener("click", () => {
      const id = button.dataset.topic;
      const chosen = new Set(state.filters.categories);
      if (!id) chosen.clear();
      else if (chosen.has(id)) chosen.delete(id);
      else chosen.add(id);
      state.filters.categories = [...chosen];
      app.querySelectorAll("[data-topic]").forEach((b) => b.setAttribute("aria-pressed",
        String(b.dataset.topic ? chosen.has(b.dataset.topic) : !chosen.size)));
    }));

  app.querySelectorAll("[data-example]").forEach((button) =>
    button.addEventListener("click", () => {
      state.question = state.info.examples[Number(button.dataset.example)];
      ask();
    }));
}

// Steps light up on a rough timer; the server answers in one go
function animateProgress() {
  const times = [0, 2000, 30000];
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
    renderHome();
    document.getElementById("question").focus();
    return;
  }
  if (state.busy) return;

  if (state.filters.published === "custom" && !state.filters.since) {
    state.error = "Pick a start date, or choose a different Published option.";
    renderHome();
    return;
  }

  state.busy = true;
  state.error = "";
  renderHome();
  const stop = animateProgress();

  try {
    const record = await api("/api/ask", {
      question, audience: state.audience, top_k: state.topK, ...filterPayload(),
    });
    stop();
    state.busy = false;
    state.question = "";
    refreshBriefs();
    location.hash = `#/brief/${record.id}`;
  } catch (error) {
    stop();
    state.busy = false;
    state.error = error.message;
    if (!location.hash.startsWith("#/brief/")) renderHome();
  }
}

// ---------- Library and Review Queue ----------

async function renderList(kind) {
  const review = kind === "review";
  setNav(kind);
  topbarTitle(review ? "REVIEW QUEUE" : "LIBRARY");

  app.className = "";
  app.innerHTML = `<div class="content content--list">
    <h1 class="page-title">${review ? "Review Queue" : "Library"}</h1>
    <p class="intro">${review
      ? "Briefs that are waiting for a KPMG reviewer, or were sent back with changes. Briefs can’t be used with clients until they’re approved."
      : "Every saved brief, newest first. Opening one never calls the model again."}</p>
    <div class="list-panel" id="list"><p class="empty">Loading…</p></div>
  </div>`;

  await refreshBriefs();
  const list = document.getElementById("list");
  if (!list) return;

  const briefs = review ? state.briefs.filter((b) => b.status !== "approved") : state.briefs;
  list.innerHTML = briefs.length
    ? listRows(briefs)
    : `<p class="empty">${review ? "Nothing waiting for review." : "No briefs yet. Ask a question on Home to create the first one."}</p>`;
}

// ---------- Brief page ----------

function currentBrief() {
  return state.record.briefs[state.view] || null;
}

function checkCards(entry) {
  if (!entry) {
    return `<div class="check">${icon("warn")}<div>
      <strong>No brief</strong><span>No relevant papers were found, so there was nothing to translate.</span></div></div>`;
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
    ? [icon(e.level === "High" ? "ok" : "warn"), `Evidence: ${e.level}`, e.reason || "See Evidence Strength in the brief."]
    : [icon("warn"), "Evidence: not rated", "The brief didn’t give an evidence rating."]);

  if (c.summary_truncated || c.brief_truncated) {
    cards.push([icon("bad"), "Output cut off", "The model hit its token limit. Regenerate before using this."]);
  }

  return cards.map(([svg, title, sub]) => `<div class="check">${svg}<div>
    <strong>${esc(title)}</strong><span>${esc(sub)}</span></div></div>`).join("");
}

// Problems shown on the Brief tab too, so they aren't only on Review
function problemAlert(entry) {
  if (!entry) return "";
  const c = entry.checks;
  const problems = [];
  if (!c.citations.ok) problems.push("it cites papers that weren’t retrieved");
  if (c.summary_truncated || c.brief_truncated) problems.push("the model output was cut off");
  if (!problems.length) return "";
  return `<div class="alert" role="alert">${icon("bad")}
    <span>Check before using this brief: ${esc(problems.join(" and "))}.</span>
    <button type="button" class="btn" data-goto="review">See the checks</button>
  </div>`;
}

function sourceCard(s, n, isCited) {
  return `<div class="src${isCited ? " src--cited" : ""}" id="src-${n}">
    <span class="id">[${n}] ${esc(baseId(s.paper_id))}</span>
    <span class="name">${esc(s.title)}</span>
    ${s.section ? `<span class="where">Matched in: ${esc(s.section)}</span>` : ""}
    <a href="${esc(s.arxiv_url)}" target="_blank" rel="noopener">Open on arXiv</a>
  </div>`;
}

function citedAside(record, cited, label) {
  const shown = record.sources.map((s, i) => [s, i + 1]).filter(([s]) => cited.has(baseId(s.paper_id)));
  return `<aside class="sources-aside" aria-labelledby="aside-h">
    <h2 id="aside-h">${esc(label)}</h2>
    ${shown.length ? shown.map(([s, n]) => sourceCard(s, n, true)).join("") : '<p class="intro">No papers cited.</p>'}
    ${record.sources.length ? `<button class="btn btn--link" type="button" data-goto="sources">See all ${record.sources.length} retrieved papers</button>` : ""}
  </aside>`;
}

function followupSection(record, entry) {
  if (!entry) return "";
  const items = record.followups || [];

  return `<section class="card followups" aria-labelledby="fu-h">
    <h2 id="fu-h">Follow-up questions</h2>
    <p class="intro">Answered from the research summary only, with no new search. Follow-ups aren’t part of the reviewed brief.</p>
    ${items.map((f) => {
      const index = items.indexOf(f);
      const other = f.audience && f.audience !== state.view && AUDIENCES[f.audience];
      const check = f.citation_check || { cited_not_retrieved: [], cited_not_in_summary: [] };
      const bad = [...check.cited_not_retrieved, ...(check.cited_not_in_summary || [])];
      return `<div class="followup${f.covered ? "" : " followup--gap"}">
        <p class="fu-q">${esc(f.question)}</p>
        ${other ? `<p class="fu-for">Answered for ${esc(other.label)}</p>` : ""}
        <div class="fu-a">${renderBody(String(f.answer).split("\n"), record.sources)}</div>
        ${bad.length ? `<p class="warn">Cites papers that aren’t in the summary: ${esc(bad.join(", "))}.</p>` : ""}
        ${f.truncated ? '<p class="warn">The answer was cut off.</p>' : ""}
        ${f.covered ? "" : `<div><button type="button" class="btn" data-research="${index}">Search new papers for this ${ARROW}</button></div>`}
      </div>`;
    }).join("")}
    <form class="followup-form" id="followup-form">
      <label for="followup" class="sr-only">Follow-up question</label>
      <textarea id="followup" class="field" rows="2"
        placeholder="e.g., What would this mean for a mid-size bank?">${esc(state.followup)}</textarea>
      <div class="row">
        <span>One model call. Enter to ask, Shift+Enter for a new line.</span>
        <button type="submit" class="btn btn--primary"${state.followupBusy ? " disabled" : ""}>
          ${state.followupBusy ? "Answering…" : "Ask follow-up"}
        </button>
      </div>
    </form>
  </section>`;
}

function briefPanel(record, entry, cited) {
  if (!entry) {
    return `<article class="card"><div class="doc"><section><p>${esc(record.summary)}</p></section></div></article>`;
  }
  const others = Object.keys(AUDIENCES).filter((a) => a !== state.view);

  return `${problemAlert(entry)}
    <div class="brief-layout">
      <div class="brief-main">
        <article class="card">
          <div class="doc">${renderDoc(entry.brief, record.sources, null, entry.checks.evidence.level)}</div>
          <div class="actions">
            <button type="button" class="btn" id="print">Export PDF</button>
            <button type="button" class="btn" id="copy-email">Copy for email</button>
            <button type="button" class="btn" id="copy-slack">Copy for Slack</button>
            <button type="button" class="btn" id="copy-link">Copy link</button>
            ${others.map((a) => record.briefs[a]
              ? `<button type="button" class="btn" data-view="${a}">View ${esc(AUDIENCES[a].label)} brief</button>`
              : `<button type="button" class="btn" data-rewrite="${a}">Rewrite for ${esc(AUDIENCES[a].label)}</button>`).join("")}
          </div>
        </article>
        ${followupSection(record, entry)}
      </div>
      ${citedAside(record, cited, "Cited in this brief")}
    </div>`;
}

function summaryPanel(record) {
  const cited = new Set(record.citation_check.cited.map(baseId));
  return `<div class="brief-layout">
      <article class="card">
        <p class="intro">The facts the brief is built from, written only from the retrieved papers. The brief is generated from this summary alone, so it can’t add anything the summary doesn’t say.</p>
        <div class="doc">${renderDoc(record.summary, record.sources, SUMMARY_LABELS)}</div>
      </article>
      ${citedAside(record, cited, "Cited in the summary")}
    </div>`;
}

function sourcesPanel(record, cited) {
  if (!record.sources.length) return '<p class="intro">No papers were retrieved.</p>';
  return `<section class="stack" aria-label="Retrieved papers">
    <p class="intro">The ${record.sources.length} papers the search returned, ranked by relevance. The summary and brief may only cite papers on this list.</p>
    ${record.sources.map((s, i) => {
      const isCited = cited.has(baseId(s.paper_id));
      return `<div class="src src-row${isCited ? " src--cited" : ""}" id="src-${i + 1}">
        <div class="body">
          <span class="id">[${i + 1}] ${esc(baseId(s.paper_id))}${s.section ? ` · matched in ${esc(s.section)}` : ""}</span>
          <span class="name">${esc(s.title)}</span>
        </div>
        <div class="side">
          <span class="${isCited ? "pill-cited" : "pill-not"}">${isCited ? "Cited" : "Not cited"}</span>
          <a href="${esc(s.arxiv_url)}" target="_blank" rel="noopener">arXiv</a>
        </div>
      </div>`;
    }).join("")}
  </section>`;
}

function reviewPanel(record, entry) {
  const status = STATUS[record.status] || STATUS.draft;
  return `<div class="review-layout">
    <section class="stack" aria-labelledby="checks-h">
      <h2 id="checks-h" style="margin:0; font-size:17px">Automatic checks</h2>
      ${checkCards(entry)}
    </section>
    <section class="card decision" aria-labelledby="decision-h">
      <h2 id="decision-h">Reviewer decision</h2>
      <div class="badges">${statusPill(record.status)}</div>
      <p class="sub">${esc(status.sub)}</p>
      ${record.note ? `<p class="note"><strong>Reviewer note:</strong> ${esc(record.note)}</p>` : ""}
      ${entry ? `
        <label for="note">Notes for the researcher (sent with Request changes)</label>
        <textarea id="note" class="field" rows="3" placeholder="e.g., Focus on banking clients; the second recommendation is too generic."></textarea>
        <div class="actions">
          ${record.status === "changes" ? `<button type="button" class="btn" data-rewrite="${esc(state.view)}">Regenerate brief</button>` : ""}
          ${record.status !== "changes" ? '<button type="button" class="btn" data-decision="changes">Request changes</button>' : ""}
          ${record.status !== "approved" ? '<button type="button" class="btn btn--primary" data-decision="approved">Approve brief</button>' : ""}
        </div>` : ""}
    </section>
  </div>`;
}

function renderBrief() {
  const record = state.record;
  const entry = currentBrief();
  const audience = AUDIENCES[state.view] || { label: state.view };
  setNav("research");
  topbarSearch();

  const briefCited = new Set((entry ? entry.citation_check.cited : []).map(baseId));
  const allCited = new Set([...record.citation_check.cited, ...briefCited].map(baseId));
  const evidence = entry && entry.checks.evidence.level;
  const lede = entry ? bottomLine(entry.brief) : "";
  const filters = filtersText(record.filters);

  const panels = {
    brief: () => briefPanel(record, entry, briefCited),
    summary: () => summaryPanel(record),
    sources: () => sourcesPanel(record, allCited),
    review: () => reviewPanel(record, entry),
  };

  app.className = "research";
  app.innerHTML = `
    <div class="q-head">
      <div class="badges">
        ${statusPill(record.status)}
        ${evidence ? `<span class="status status--info">Evidence: ${esc(evidence)}</span>` : ""}
      </div>
      <h1>${esc(record.query)}</h1>
      ${lede ? `<p class="lede">${esc(lede)}</p>` : ""}
      <div class="meta">
        <span>Written for: <strong>${esc(audience.label)}</strong></span>
        <span>${record.sources.length} papers retrieved, ${briefCited.size} cited in the brief</span>
        ${filters ? `<span>Filters: ${esc(filters)}</span>` : ""}
        <span>Model: ${esc(record.model)}</span>
        <span>${esc(formatDate(record.created_at))}</span>
      </div>
    </div>

    ${state.error ? `<p class="error" role="alert">${esc(state.error)}</p>` : ""}

    <div class="tabs" role="tablist" aria-label="Brief views">
      ${TABS.map(([id, label]) => `<button class="tab" role="tab" id="tab-${id}" type="button"
        aria-selected="${state.tab === id}" aria-controls="panel" tabindex="${state.tab === id ? 0 : -1}"
        data-tab="${id}">${label}</button>`).join("")}
    </div>

    <div class="panel" id="panel" role="tabpanel" aria-labelledby="tab-${state.tab}">
      ${panels[state.tab]()}
    </div>`;

  bindBrief();
}

function selectTab(tab, focus) {
  state.tab = tab;
  renderBrief();
  if (focus) document.getElementById(`tab-${tab}`)?.focus();
}

function bindBrief() {
  const on = (selector, handler) => app.querySelectorAll(selector).forEach((el) => el.addEventListener("click", handler));

  const tabIds = TABS.map(([id]) => id);
  app.querySelectorAll("[role=tab]").forEach((tab) => {
    tab.addEventListener("click", () => selectTab(tab.dataset.tab));
    tab.addEventListener("keydown", (e) => {
      const i = tabIds.indexOf(tab.dataset.tab);
      const next = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: tabIds.length - 1 }[e.key];
      if (next === undefined) return;
      e.preventDefault();
      selectTab(tabIds[(next + tabIds.length) % tabIds.length], true);
    });
  });

  on("[data-goto]", (e) => selectTab(e.currentTarget.dataset.goto, true));
  on("[data-view]", (e) => { state.view = e.currentTarget.dataset.view; state.tab = "brief"; renderBrief(); });
  on("[data-rewrite]", (e) => rewrite(e.currentTarget.dataset.rewrite, e.currentTarget));
  on("[data-decision]", (e) => {
    const decision = e.currentTarget.dataset.decision;
    setStatus(decision, decision === "changes" ? document.getElementById("note").value : "");
  });
  on("#print", () => window.print());
  on("#copy-link", () => copyText(location.href, "Link copied"));
  on("#copy-email", () => copyText(briefAsText(state.record, currentBrief(), "email"), "Copied for email"));
  on("#copy-slack", () => copyText(briefAsText(state.record, currentBrief(), "slack"), "Copied for Slack"));
  on("[data-research]", (e) => {
    const f = state.record.followups[Number(e.currentTarget.dataset.research)];
    state.question = f.question;
    state.audience = f.audience || state.view;
    state.error = "";
    location.hash = "#/";
  });

  // Citation links scroll to the source card; papers not shown here open the Sources tab
  on("[data-src]", (e) => {
    e.preventDefault();
    const n = e.currentTarget.dataset.src;
    if (!document.getElementById("src-" + n)) selectTab("sources");
    const card = document.getElementById("src-" + n);
    if (!card) return;
    card.scrollIntoView({ behavior: "smooth", block: "center" });
    card.classList.add("flash");
    setTimeout(() => card.classList.remove("flash"), 1500);
  });

  const form = document.getElementById("followup-form");
  if (form) {
    const textarea = document.getElementById("followup");
    textarea.addEventListener("input", () => { state.followup = textarea.value; });
    textarea.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); }
    });
    form.addEventListener("submit", (e) => { e.preventDefault(); askFollowup(); });
  }
}

async function askFollowup() {
  const question = state.followup.trim();
  if (!question || state.followupBusy) return;

  const id = state.record.id;
  state.followupBusy = true;
  state.error = "";
  renderBrief();

  try {
    const record = await api(`/api/briefs/${id}/followup`, { question });
    state.followup = "";
    if (state.record && state.record.id === id) state.record = record;
  } catch (error) {
    state.error = error.message;
  }
  state.followupBusy = false;
  if (state.record && state.record.id === id) {
    renderBrief();
    document.getElementById("followup")?.focus();
  }
}

async function setStatus(status, note = "") {
  try {
    state.record = await api(`/api/briefs/${state.record.id}/status`, { status, note });
    state.error = "";
    toast(status === "approved" ? "Brief approved" : "Sent back for changes");
    refreshBriefs();
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
    refreshBriefs();
  } catch (error) {
    state.error = error.message;
  }
  renderBrief();
}

async function openBrief(id, tab) {
  setNav("research");
  topbarSearch();
  app.className = "research";
  app.innerHTML = '<p class="loading">Loading brief…</p>';
  try {
    const record = await api(`/api/briefs/${encodeURIComponent(id)}`);
    if (!state.record || state.record.id !== record.id) {
      state.followup = "";
      state.tab = "brief";
    }
    if (TABS.some(([t]) => t === tab)) state.tab = tab;
    state.record = record;
    state.view = record.audience;
    state.error = "";
    renderBrief();
  } catch (error) {
    app.innerHTML = `<p class="error" role="alert">${esc(error.message)}</p><p><a href="#/">Back to Home</a></p>`;
  }
}

// ---------- routing ----------

async function route() {
  const hash = location.hash || "#/";
  const brief = hash.match(/^#\/brief\/([^/]+)(?:\/(\w+))?$/);
  window.scrollTo(0, 0);

  if (brief) return openBrief(brief[1], brief[2]);

  state.error = state.busy ? state.error : "";

  if (hash === "#/library" || hash === "#/saved") return renderList("library");
  if (hash === "#/review") return renderList("review");

  if (hash === "#/research") {
    const latest = state.record ? state.record.id : state.briefs[0] && state.briefs[0].id;
    if (latest) { location.replace(`#/brief/${latest}`); return; }
    history.replaceState(null, "", "#/");
  }

  renderHome(hash === "#/how" ? "how" : null);

  if (state.autoAsk) {
    state.autoAsk = false;
    ask();
  }
}

async function init() {
  try {
    state.info = await api("/api/info");
    if (state.info.default_audience) state.audience = state.info.default_audience;
    const model = [state.info.provider, state.info.model].filter(Boolean).join(" · ");
    if (model) document.getElementById("model-text").textContent = model;
  } catch {
    state.info = { corpus: {} };
    document.getElementById("model-text").textContent = "Server not reachable";
  }
  await refreshBriefs();
  route();
}

window.addEventListener("hashchange", route);
init();
