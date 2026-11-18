// Present tab on the brief page (#/brief/<id>/present): turn the brief into a
// slide outline with speaker notes, likely questions and things to watch out
// for, for a chosen audience and talk length. Generating is one LLM call;
// opening, editing (saved automatically) or deleting a saved deck costs nothing.
//
// Loaded before app.js. It uses app.js helpers (state, esc, api, toast, copyText,
// formatDate, icon, renderBrief, selectTab) only when the page draws. app.js
// calls presentPanel() and bindPresent(). The form lives in `prs`, so it
// survives redraws.

const prs = {
  briefId: "",
  options: null,        // audiences, lengths
  loading: false,
  audience: "",
  minutes: 10,
  include: { adaptation: "", pilot_plan: "", market_scan: "" },  // chosen saved material ids
  materials: { adaptations: [], pilot_plans: [], market_scans: [] },
  decks: [],            // saved decks for this brief (short rows), newest first
  current: null,        // the full deck on screen
  busy: false,
  error: "",
  saving: "",           // "", "saving", "saved", "error"
  saveTimer: null,
  confirmDelete: false,
};

const PRESENT_SAVE_DELAY = 800;

// ---------- loading ----------

async function presentLoad(record) {
  presentFlush();  // an edit still waiting to save belongs to the deck being left
  const briefId = record.id;
  prs.briefId = briefId;
  prs.loading = true;
  prs.current = null;
  prs.decks = [];
  prs.error = "";
  prs.confirmDelete = false;
  prs.audience = record.audience || "executive";
  prs.include = { adaptation: "", pilot_plan: "", market_scan: "" };
  try {
    const [options, saved] = await Promise.all([
      prs.options ? Promise.resolve(prs.options) : api("/api/present/options"),
      api(`/api/briefs/${briefId}/presentations`),
    ]);
    if (prs.briefId !== briefId) return;
    if (!prs.options) prs.minutes = options.default_length;
    prs.options = options;
    prs.decks = saved.presentations;
    prs.materials = saved.materials;
    if (prs.decks.length) prs.current = await api(`/api/presentations/${prs.decks[0].id}`);
  } catch (error) {
    prs.error = error.message;
  }
  prs.loading = false;
  presentRedraw(briefId);
}

function presentRedraw(briefId) {
  if (state.record && state.record.id === briefId && state.tab === "present") renderBrief();
}

function presentAudienceLabel(id) {
  const found = prs.options && prs.options.audiences.find((a) => a.id === id);
  return found ? found.label : id;
}

// ---------- the form ----------

function presentMaterialPicker(kind, label, items) {
  if (!items.length) return "";
  return `<div class="form-field">
    <label for="prs-${kind}">${esc(label)}</label>
    <select id="prs-${kind}" class="select select--light" data-prs-include="${kind}">
      <option value="">Don’t include</option>
      ${items.map((i) => `<option value="${esc(i.id)}"${prs.include[kind] === i.id ? " selected" : ""}>${esc(i.label || "Untitled")}</option>`).join("")}
    </select>
  </div>`;
}

function presentForm() {
  const o = prs.options;
  const m = prs.materials;
  const pickers = [
    presentMaterialPicker("adaptation", "Industry adaptation", m.adaptations),
    presentMaterialPicker("pilot_plan", "Pilot plan", m.pilot_plans),
    presentMaterialPicker("market_scan", "Market scan", m.market_scans),
  ].join("");
  return `<section class="card present-form no-print" aria-labelledby="prs-form-h">
    <div class="poc-head">
      <h2 id="prs-form-h">${prs.current ? "Generate new notes/slides" : "Generate notes/slides"}</h2>
      <span class="status status--info">1 LLM call</span>
    </div>
    <p class="intro">Builds a slide outline with speaker notes and likely questions from this brief, its research summary and its sources. Nothing new is added: numbers and papers are checked against the research afterwards.</p>
    <form id="prs-form" class="stack" novalidate>
      <div class="present-options">
        <div class="form-field">
          <label for="prs-audience">Presenting to</label>
          <select id="prs-audience" class="select select--light">
            ${(o ? o.audiences : []).map((a) => `<option value="${esc(a.id)}"${a.id === prs.audience ? " selected" : ""}>${esc(a.label)}</option>`).join("")}
          </select>
        </div>
        <div class="form-field">
          <span class="poc-label" id="prs-length-label">Time to present</span>
          <div class="chip-row" role="group" aria-labelledby="prs-length-label">
            ${(o ? o.lengths : []).map((l) => `<button type="button" class="btn" data-prs-minutes="${l.minutes}"
              aria-pressed="${l.minutes === prs.minutes}" title="About ${l.slides} slides">${l.minutes} min</button>`).join("")}
          </div>
        </div>
      </div>
      ${pickers ? `<fieldset class="present-materials">
        <legend class="poc-label">Include saved work <span class="poc-optional">Optional. Adds an industry or pilot plan slide.</span></legend>
        <div class="present-options">${pickers}</div>
      </fieldset>` : ""}
      <div class="poc-submit">
        <span>${prs.busy ? "Writing the slides and speaker notes…" : "Takes less time than a brief."}</span>
        <button type="submit" class="btn btn--primary" id="prs-run"${prs.busy ? " disabled" : ""}>${prs.busy ? "Generating…" : "Generate"}</button>
      </div>
      ${prs.error ? `<p class="error" role="alert">${esc(prs.error)}</p>` : ""}
    </form>
  </section>`;
}

// ---------- the deck ----------

function presentApprovalWarning(record) {
  if (record.status === "approved") return "";
  return `<p class="present-warning" role="note">This brief hasn’t been approved yet. Treat these slides as a draft and don’t share them with a client until the brief is approved.</p>`;
}

function presentChecks(deck) {
  const c = deck.checks;
  const s = c.structure;
  const cards = [];
  const badCites = [...c.citations.not_retrieved, ...c.citations.not_in_summary];
  cards.push(c.citations.ok
    ? ["ok", "Citations verified", "Every paper cited is one the research summary cites."]
    : ["bad", "Citation problem", `Cites papers the research summary doesn’t: ${badCites.join(", ")}.`]);
  cards.push(c.numbers.ok
    ? ["ok", "Numbers traced", "Every number appears in the brief, the summary or the saved work included."]
    : ["warn", "Numbers to check", `Not found in the research: ${c.numbers.ungrounded.join(", ")}. Check or remove before presenting.`]);
  const problems = [];
  if (s.missing_notes.length) problems.push(`no speaker notes on slide ${s.missing_notes.join(", ")}`);
  if (s.empty_slides.length) problems.push(`no bullets on slide ${s.empty_slides.join(", ")}`);
  if (s.untitled_slides.length) problems.push(`no title on slide ${s.untitled_slides.join(", ")}`);
  if (!s.has_sources_slide) problems.push("no Sources slide");
  if (!s.minutes_ok) problems.push(`slides add up to ${s.total_minutes} of ${deck.minutes} minutes`);
  cards.push(problems.length
    ? ["warn", "Outline incomplete", problems.join("; ") + "."]
    : ["ok", `${s.slide_count} slides, ${s.total_minutes} minutes`, "Every slide has a title, bullets and speaker notes."]);
  if (deck.truncated) cards.push(["bad", "Output cut off", "The model hit its token limit. Generate again before using it."]);
  cards.push(["warn", "Draft for review", "Checks catch made-up papers and numbers, not every wrong claim. Read it through before presenting."]);
  return cards.map(([kind, title, sub]) => `<div class="check">${icon(kind)}<div>
    <strong>${esc(title)}</strong><span>${esc(sub)}</span></div></div>`).join("");
}

function presentSlide(slide, i) {
  const id = `prs-s${i}`;
  return `<article class="card present-slide" aria-labelledby="${id}-title-label">
    <div class="present-slide-head">
      <span class="present-num" id="${id}-title-label">Slide ${i + 1}${slide.section ? ` · ${esc(slide.section)}` : ""}</span>
      <label class="present-minutes">
        <input type="number" class="text-input" min="0" max="20" step="0.5" value="${esc(slide.minutes)}"
          data-prs-slide="${i}" data-prs-field="minutes" aria-label="Minutes for slide ${i + 1}"> min
      </label>
    </div>
    <label class="sr-only" for="${id}-title">Title</label>
    <input id="${id}-title" class="text-input present-title" type="text" maxlength="120" value="${esc(slide.title)}"
      data-prs-slide="${i}" data-prs-field="title">
    <label class="small-label" for="${id}-bullets">Bullets <span class="poc-optional">one per line</span></label>
    <textarea id="${id}-bullets" class="field" rows="${Math.max(2, slide.bullets.length + 1)}"
      data-prs-slide="${i}" data-prs-field="bullets">${esc(slide.bullets.join("\n"))}</textarea>
    <label class="small-label" for="${id}-notes">Speaker notes</label>
    <textarea id="${id}-notes" class="field" rows="4" data-prs-slide="${i}" data-prs-field="notes">${esc(slide.notes)}</textarea>
    ${slide.questions.length ? `<div class="present-questions">
      <span class="small-label">They might ask</span>
      ${slide.questions.map((q, j) => `<div class="present-question">
        <label class="sr-only" for="${id}-q${j}">Question ${j + 1}</label>
        <input id="${id}-q${j}" class="text-input" type="text" maxlength="300" value="${esc(q.question)}"
          data-prs-slide="${i}" data-prs-question="${j}" data-prs-field="question">
        <label class="sr-only" for="${id}-a${j}">Suggested answer ${j + 1}</label>
        <textarea id="${id}-a${j}" class="field" rows="2" data-prs-slide="${i}" data-prs-question="${j}"
          data-prs-field="answer">${esc(q.answer)}</textarea>
      </div>`).join("")}
    </div>` : ""}
  </article>`;
}

function presentSaveText() {
  return { saving: "Saving…", saved: "All changes saved", error: "Couldn’t save. Keep this tab open and try again." }[prs.saving] || "Edits save automatically";
}

function presentDeckView(deck, record) {
  const extras = Object.values(deck.extras || {}).map((e) => e.label).filter(Boolean);
  return `<section class="card present-head-card">
      <div class="badges">
        <span class="status status--info">${esc(presentAudienceLabel(deck.audience))} · ${deck.minutes} min</span>
        <span class="status status--review">Draft</span>
      </div>
      <p class="present-meta">Generated ${esc(formatDate(deck.created_at))}${extras.length ? ` · includes ${esc(extras.join(", "))}` : ""}</p>
      ${presentApprovalWarning(record)}
      <div class="actions no-print">
        <button type="button" class="btn" id="prs-copy">Copy as text</button>
        <button type="button" class="btn" id="prs-delete">${prs.confirmDelete ? "Click again to delete" : "Delete"}</button>
        <span class="present-saving" id="prs-saving" aria-live="polite">${esc(presentSaveText())}</span>
      </div>
    </section>
    <section class="stack present-checks" id="prs-checks" aria-label="Automatic checks">${presentChecks(deck)}</section>
    ${deck.slides.map(presentSlide).join("")}
    <section class="card present-watch" aria-labelledby="prs-watch-h">
      <h2 id="prs-watch-h">Watch out for</h2>
      <label class="sr-only" for="prs-watch">Things to watch out for, one per line</label>
      <textarea id="prs-watch" class="field" rows="${Math.max(3, deck.watch_outs.length + 1)}"
        data-prs-field="watch_outs">${esc(deck.watch_outs.join("\n"))}</textarea>
    </section>`;
}

function presentSavedList() {
  if (prs.decks.length < 2 && !(prs.decks.length === 1 && !prs.current)) return "";
  return `<section class="card no-print" aria-labelledby="prs-saved-h">
    <h2 id="prs-saved-h">Saved presentations for this brief</h2>
    <ul class="poc-plans">${prs.decks.map((d) => {
      const open = prs.current && prs.current.id === d.id;
      const details = [`${d.slides} slides`, formatDate(d.updated_at || d.created_at)].join(" · ");
      return `<li class="poc-plan-row${open ? " poc-plan-row--open" : ""}">
        <div class="poc-plan-info"><strong>${esc(presentAudienceLabel(d.audience))} · ${d.minutes} min</strong><span>${esc(details)}</span></div>
        <div class="poc-row-actions">
          <button type="button" class="btn" data-prs-open="${esc(d.id)}"${open ? " disabled" : ""}>${open ? "Viewing" : "Open"}</button></div>
      </li>`;
    }).join("")}</ul>
  </section>`;
}

function presentPanel(record) {
  if (prs.briefId !== record.id || prs.loading) {
    return '<p class="loading">Loading presentations…</p>';
  }
  if (!record.sources.length) {
    return '<p class="intro">No papers were found for this question, so there is no research to present.</p>';
  }
  const deck = prs.current;
  return `<div class="brief-layout present">
      <div class="brief-main">
        ${deck ? presentDeckView(deck, record) : presentApprovalWarning(record)}
        ${presentForm()}
        ${presentSavedList()}
      </div>
      <aside class="sources-aside" aria-label="About presentations">
        <h2>Storyline</h2>
        <div class="src"><span class="name">The answer</span><span class="where">The main takeaway.</span></div>
        <div class="src"><span class="name">Why it matters</span><span class="where">Why the business should care.</span></div>
        <div class="src"><span class="name">Research findings</span><span class="where">What the papers found, one study at a time.</span></div>
        <div class="src"><span class="name">What to do next</span><span class="where">The action or decision.</span></div>
        <div class="src"><span class="name">Evidence and limitations</span><span class="where">How confident we are, and what’s untested.</span></div>
        <div class="src"><span class="name">Industry or pilot plan</span><span class="where">Only when saved work is included.</span></div>
        <div class="src"><span class="name">Sources</span><span class="where">The papers behind it.</span></div>
      </aside>
    </div>`;
}

// ---------- copying ----------

function deckAsText(deck, record) {
  const lines = [`${record.query}`, `${presentAudienceLabel(deck.audience)} · ${deck.minutes} minutes`];
  if (record.status !== "approved") lines.push("DRAFT: the research brief behind these slides hasn't been approved.");
  deck.slides.forEach((s, i) => {
    lines.push("", `Slide ${i + 1}: ${s.title} (${s.minutes} min)`);
    s.bullets.forEach((b) => lines.push(`- ${b}`));
    if (s.notes) lines.push("", `Speaker notes: ${s.notes}`);
    s.questions.forEach((q) => lines.push(`Q: ${q.question}`, `A: ${q.answer || "(no suggested answer)"}`));
  });
  if (deck.watch_outs.length) {
    lines.push("", "Watch out for:");
    deck.watch_outs.forEach((w) => lines.push(`- ${w}`));
  }
  return lines.join("\n");
}

// ---------- saving edits ----------

function presentEdit(target) {
  const deck = prs.current;
  const field = target.dataset.prsField;
  if (field === "watch_outs") {
    deck.watch_outs = target.value.split("\n");
  } else {
    const slide = deck.slides[Number(target.dataset.prsSlide)];
    if (target.dataset.prsQuestion !== undefined) {
      slide.questions[Number(target.dataset.prsQuestion)][field] = target.value;
    } else if (field === "bullets") {
      slide.bullets = target.value.split("\n");
    } else if (field === "minutes") {
      slide.minutes = Number(target.value) || 0;
    } else {
      slide[field] = target.value;
    }
  }
  presentSetSaving("saving");
  clearTimeout(prs.saveTimer);
  prs.saveTimer = setTimeout(() => presentSave(deck.id), PRESENT_SAVE_DELAY);
}

function presentSetSaving(status) {
  prs.saving = status;
  const el = document.getElementById("prs-saving");
  if (el) el.textContent = presentSaveText();
}

// The deck as the PUT route takes it: blank lines and blank questions dropped
function presentBody(deck) {
  return {
    slides: deck.slides.map((s) => ({
      ...s,
      bullets: s.bullets.map((b) => b.trim()).filter(Boolean),
      questions: s.questions.filter((q) => q.question.trim()),
    })),
    watch_outs: deck.watch_outs.map((w) => w.trim()).filter(Boolean),
  };
}

async function presentSave(deckId) {
  const deck = prs.current;
  if (!deck || deck.id !== deckId) return;
  try {
    const saved = await api(`/api/presentations/${deckId}`, presentBody(deck), "PUT");
    if (prs.current && prs.current.id === deckId) {
      // keep what's being typed; take the server's checks
      prs.current.checks = saved.checks;
      prs.current.updated_at = saved.updated_at;
      const checks = document.getElementById("prs-checks");
      if (checks) checks.innerHTML = presentChecks(prs.current);
    }
    presentSetSaving("saved");
  } catch (error) {
    presentSetSaving("error");
    toast(error.message);
  }
}

async function presentFlush() {
  if (!prs.saveTimer || prs.saving !== "saving" || !prs.current) return;
  clearTimeout(prs.saveTimer);
  prs.saveTimer = null;
  await presentSave(prs.current.id);
}

// ---------- events ----------

async function presentRun(briefId) {
  await presentFlush();
  prs.busy = true;
  prs.error = "";
  presentRedraw(briefId);
  const body = { audience: prs.audience, minutes: prs.minutes };
  if (prs.include.adaptation) body.adaptation_id = prs.include.adaptation;
  if (prs.include.pilot_plan) body.pilot_plan_id = prs.include.pilot_plan;
  if (prs.include.market_scan) body.market_scan_id = prs.include.market_scan;
  try {
    const deck = await api(`/api/briefs/${briefId}/presentations`, body);
    if (prs.briefId === briefId) {
      prs.current = deck;
      prs.saving = "";
      prs.decks = (await api(`/api/briefs/${briefId}/presentations`)).presentations;
      toast("Slides ready");
    }
  } catch (error) {
    if (prs.briefId === briefId) prs.error = error.message;
  }
  prs.busy = false;
  presentRedraw(briefId);
  if (prs.current) document.querySelector(".present-head-card")?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function bindPresent(record) {
  if (state.tab !== "present") return;
  const briefId = record.id;
  if (prs.briefId !== briefId) {
    presentLoad(record);
    return;
  }

  const on = (selector, event, handler) =>
    app.querySelectorAll(selector).forEach((el) => el.addEventListener(event, handler));

  on("#prs-audience", "change", (e) => { prs.audience = e.target.value; });
  on("[data-prs-minutes]", "click", (e) => {
    prs.minutes = Number(e.currentTarget.dataset.prsMinutes);
    app.querySelectorAll("[data-prs-minutes]").forEach((b) =>
      b.setAttribute("aria-pressed", String(Number(b.dataset.prsMinutes) === prs.minutes)));
  });
  on("[data-prs-include]", "change", (e) => { prs.include[e.target.dataset.prsInclude] = e.target.value; });
  on("#prs-form", "submit", (e) => { e.preventDefault(); if (!prs.busy) presentRun(briefId); });

  on("[data-prs-field]", "input", (e) => presentEdit(e.target));

  on("[data-prs-open]", "click", async (e) => {
    await presentFlush();
    try {
      prs.current = await api(`/api/presentations/${e.currentTarget.dataset.prsOpen}`);
      prs.saving = "";
      prs.confirmDelete = false;
    } catch (error) {
      toast(error.message);
    }
    renderBrief();
  });

  on("#prs-copy", "click", async () => {
    await presentFlush();
    copyText(deckAsText(prs.current, state.record), "Slides copied");
  });
  on("#prs-delete", "click", async () => {
    if (!prs.confirmDelete) {
      prs.confirmDelete = true;
      renderBrief();
      return;
    }
    clearTimeout(prs.saveTimer);
    prs.saveTimer = null;
    try {
      await api(`/api/presentations/${prs.current.id}`, undefined, "DELETE");
      prs.decks = prs.decks.filter((d) => d.id !== prs.current.id);
      prs.current = prs.decks.length ? await api(`/api/presentations/${prs.decks[0].id}`) : null;
      prs.saving = "";
      toast("Presentation deleted");
    } catch (error) {
      toast(error.message);
    }
    prs.confirmDelete = false;
    renderBrief();
  });
}

// An edit still waiting to save when the page closes is sent anyway
window.addEventListener("pagehide", () => {
  if (prs.saving !== "saving" || !prs.current) return;
  clearTimeout(prs.saveTimer);
  const deck = prs.current;
  fetch(`/api/presentations/${deck.id}`, {
    method: "PUT",
    keepalive: true,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(presentBody(deck)),
  });
});
