// POC Starter, on the brief page (#/brief/<id>): pick an industry and a use case,
// answer a few questions, and get a pilot checklist you can edit.
//
// Generating the checklist is one model call (POST /api/briefs/<id>/pilot-checklist).
// Saving a plan, ticking steps and editing them use the pilot plan routes and
// cost no model calls (see "Saved industry adaptations, pilot plans and comments"
// in README.md).
//
// Loaded before app.js. It uses app.js helpers (state, esc, api, toast, copyText,
// formatDate) only when the page draws, and app.js only calls pocStarterSection()
// and bindPocStarter(). The form lives in `poc` below, so it survives the brief
// page redrawing after a follow-up question or a review decision.

// The same industries as "Suggested industry applications" (server.py,
// IndustryApplicationRequest). Keep the two lists in step.
const POC_INDUSTRIES = [
  "Healthcare", "Finance", "Construction & Real Estate", "Government & Public Services",
];

// The questions are saved with the plan under their label, so the label is the key.
// A question with `options` is a dropdown; the rest are text boxes.
const POC_QUESTIONS = [
  { label: "Who would run the pilot?", placeholder: "e.g., two analysts, one risk lead" },
  { label: "How long should the pilot run?", options: ["2 weeks", "4 weeks", "8 weeks", "12 weeks"], fallback: "8 weeks" },
  { label: "Which records or tools could it use?", placeholder: "e.g., shared inbox, case tracker" },
  { label: "How will you know it worked?", placeholder: "e.g., review time, error rate" },
  { label: "What worries you most?", placeholder: "e.g., sensitive data leaving the team" },
];

const POC_USE_CASE_LIMIT = 300;   // same limit as src/app/poc_starter.py
const POC_MAX_SUGGESTIONS = 6;

function pocStoredName() {
  try { return localStorage.getItem("pocName") || ""; } catch { return ""; }
}

const poc = {
  briefId: "",
  loaded: false,        // saved adaptations and plans fetched for this brief
  industry: POC_INDUSTRIES[0],
  useCase: "",
  answers: {},          // question label -> what has been typed so far
  name: pocStoredName(),
  adaptations: [],      // saved for this brief; their use cases become suggestions
  plans: [],            // saved pilot plans for this brief, newest first
  plan: null,           // the plan open on screen (one of `plans`)
  busy: false,
  error: "",
  saveNote: "",
  confirmDelete: "",    // plan id waiting for a second click on Delete
  queue: Promise.resolve(),   // saves run one at a time, in order
};

// ---------- small helpers ----------

// A saved use case is text, or a small object depending on the industry prompt
function pocUseCaseLabel(item) {
  if (typeof item === "string") return item.trim();
  if (item && typeof item === "object") {
    const text = item.title || item.name || item.use_case || item.text || item.description
      || Object.values(item).find((value) => typeof value === "string");
    return String(text || "").trim();
  }
  return "";
}

function pocSavedUseCases() {
  const wanted = poc.industry.toLowerCase();
  const labels = poc.adaptations
    .filter((a) => (a.industry || "").toLowerCase() === wanted)
    .flatMap((a) => a.use_cases || [])
    .map(pocUseCaseLabel)
    .filter(Boolean);
  return [...new Set(labels)];
}

function pocAnswer(question) {
  return poc.answers[question.label] ?? question.fallback ?? "";
}

function pocAnswers() {
  return Object.fromEntries(POC_QUESTIONS.map((q) => [q.label, pocAnswer(q).trim()]));
}

function pocProgressText(items) {
  const done = items.filter((item) => item.done).length;
  return `${done} of ${items.length} done`;
}

// ---------- markup ----------

function pocQuestionField(question, index) {
  const id = `poc-q${index}`;
  const value = pocAnswer(question);
  const control = question.options
    ? `<select id="${id}" class="select select--light" data-poc-answer="${index}">
        ${[...new Set([...question.options, value])].map((option) =>
          `<option${option === value ? " selected" : ""}>${esc(option)}</option>`).join("")}
      </select>`
    : `<input id="${id}" class="text-input" type="text" maxlength="300" data-poc-answer="${index}"
        value="${esc(value)}" placeholder="${esc(question.placeholder)}">`;

  return `<div class="form-field"><label for="${id}">${esc(question.label)}</label>${control}</div>`;
}

function pocItemHtml(item) {
  return `<li class="poc-item${item.done ? " poc-item--done" : ""}">
    <input type="checkbox" class="poc-check" aria-label="Step done"${item.done ? " checked" : ""}>
    <textarea class="field poc-text" rows="2" maxlength="300" aria-label="Step">${esc(item.text)}</textarea>
    <button type="button" class="tag-x" data-poc-remove aria-label="Remove step">×</button>
  </li>`;
}

function pocPlanHtml() {
  const plan = poc.plan;
  const items = plan.checklist || [];

  return `<div class="poc-plan" id="poc-plan">
    <p class="poc-label">3 · Your pilot checklist</p>
    <div class="poc-plan-head">
      <h3 tabindex="-1">${esc(plan.title)}</h3>
      <span class="tag">${esc(plan.industry)}</span>
    </div>
    <p class="intro">A proposal built from the research summary, not a result the research showed. Edit the wording, tick steps off, and add or remove steps. Changes save as you go.</p>
    <ul class="poc-list" id="poc-list" aria-label="Pilot checklist">
      ${items.map(pocItemHtml).join("")}
    </ul>
    <div class="actions poc-actions">
      <button type="button" class="btn" id="poc-add">Add a step</button>
      <button type="button" class="btn" id="poc-copy">Copy checklist</button>
      <button type="button" class="btn" id="poc-close">Close</button>
      <span class="poc-progress" id="poc-progress" role="status">${esc(pocProgressText(items))}</span>
      <span class="poc-note" id="poc-note" role="status">${esc(poc.saveNote)}</span>
    </div>
  </div>`;
}

function pocSavedPlansHtml() {
  return `<div class="poc-saved-plans">
    <p class="poc-label">Saved pilot plans for this brief</p>
    <ul class="poc-plans">
      ${poc.plans.map((plan) => {
        const open = poc.plan && poc.plan.id === plan.id;
        const details = [
          plan.industry,
          pocProgressText(plan.checklist || []),
          plan.created_by,
          formatDate(plan.created_at, false),
        ].filter(Boolean).join(" · ");

        return `<li class="poc-plan-row${open ? " poc-plan-row--open" : ""}">
          <div class="poc-plan-info">
            <strong>${esc(plan.title || "Pilot plan")}</strong>
            <span>${esc(details)}</span>
          </div>
          <div class="poc-row-actions">
            <button type="button" class="btn" data-poc-open="${esc(plan.id)}"${open ? " disabled" : ""}>${open ? "Viewing" : "Open"}</button>
            <button type="button" class="btn" data-poc-delete="${esc(plan.id)}">${poc.confirmDelete === plan.id ? "Click again to delete" : "Delete"}</button>
          </div>
        </li>`;
      }).join("")}
    </ul>
  </div>`;
}

function pocInner() {
  const saved = pocSavedUseCases().slice(0, POC_MAX_SUGGESTIONS);

  return `<div class="poc-head">
      <h2 id="poc-h">POC Starter</h2>
      <span class="status status--info">Draft · you can edit everything</span>
    </div>
    <p class="intro">Pick a use case, answer a few questions, and get a pilot checklist your team can edit and save. The research summary is the only source it uses.</p>

    <form id="poc-form" class="poc-form" novalidate>
      <p class="poc-label">1 · Pick a use case</p>
      <div class="chip-row" role="group" aria-label="Industry">
        ${POC_INDUSTRIES.map((industry) =>
          `<button type="button" class="btn" data-poc-industry="${esc(industry)}" aria-pressed="${industry === poc.industry}">${esc(industry)}</button>`
        ).join("")}
      </div>
      ${saved.length ? `<div class="poc-saved">
        <span class="poc-hint">Saved use cases for ${esc(poc.industry)}. Pick one or write your own.</span>
        ${saved.map((useCase, i) =>
          `<button type="button" class="btn poc-suggest" data-poc-usecase="${i}">${esc(useCase)}</button>`).join("")}
      </div>` : ""}
      <label for="poc-usecase" class="sr-only">Use case</label>
      <textarea id="poc-usecase" class="field" rows="2" maxlength="${POC_USE_CASE_LIMIT}"
        placeholder="Describe the use case in a sentence, e.g., Route insurance paperwork to the right team before staff review">${esc(poc.useCase)}</textarea>

      <p class="poc-label">2 · A few questions <span class="poc-optional">Skip any you don’t know yet</span></p>
      <div class="poc-questions">
        ${POC_QUESTIONS.map(pocQuestionField).join("")}
        <div class="form-field">
          <label for="poc-name">Your name <span class="optional">(optional)</span></label>
          <input id="poc-name" class="text-input" type="text" maxlength="120" value="${esc(poc.name)}" placeholder="Shown on the saved plan">
        </div>
      </div>

      <div class="poc-submit">
        <span>One model call. Saving and editing the checklist are free.</span>
        <button type="submit" class="btn btn--primary"${poc.busy ? " disabled" : ""}>${poc.busy ? "Writing the checklist…" : "Generate checklist"}</button>
      </div>
    </form>

    ${poc.error ? `<p class="error" role="alert">${esc(poc.error)}</p>` : ""}
    ${poc.plan ? pocPlanHtml() : ""}
    ${poc.plans.length ? pocSavedPlansHtml() : ""}`;
}

// app.js calls this where the section belongs on the brief page
function pocStarterSection() {
  pocSwitchBrief(state.record.id);
  return `<section class="card poc no-print" id="poc-starter" aria-labelledby="poc-h">${pocInner()}</section>`;
}

// ---------- drawing ----------

function pocSwitchBrief(briefId) {
  if (poc.briefId === briefId) return;
  Object.assign(poc, {
    briefId, loaded: false, useCase: "", answers: {}, adaptations: [], plans: [], plan: null,
    busy: false, error: "", saveNote: "", confirmDelete: "",
  });
}

// Redraws the section from `poc`. `focus` is a selector to put the cursor back on.
function pocDraw(focus) {
  const section = document.getElementById("poc-starter");
  if (!section) return;

  // Keep edits that haven't finished saving, so the redraw can't undo them
  if (poc.plan && document.getElementById("poc-list")) poc.plan.checklist = pocReadChecklist();

  section.innerHTML = pocInner();
  if (focus) section.querySelector(focus)?.focus();
}

// ---------- the checklist on screen ----------

function pocReadChecklist() {
  return [...document.querySelectorAll("#poc-list .poc-item")]
    .map((row) => ({
      text: row.querySelector(".poc-text").value.replace(/\s+/g, " ").trim(),
      done: row.querySelector(".poc-check").checked,
    }))
    .filter((item) => item.text);
}

function pocSetNote(text) {
  poc.saveNote = text;
  const note = document.getElementById("poc-note");
  if (note) note.textContent = text;
}

function pocShowProgress() {
  const progress = document.getElementById("poc-progress");
  if (progress) progress.textContent = pocProgressText(pocReadChecklist());
}

// Saves whatever the checklist shows now. Saves queue up, so they finish in order.
function pocSave() {
  if (!poc.plan) return;
  const planId = poc.plan.id;
  pocShowProgress();
  poc.queue = poc.queue.then(() => pocSaveNow(planId));
}

async function pocSaveNow(planId) {
  // The plan may have been closed or swapped while this save waited
  if (!poc.plan || poc.plan.id !== planId || !document.getElementById("poc-list")) return;

  const plan = poc.plan;
  pocSetNote("Saving…");
  try {
    const saved = await api(`/api/pilot-plans/${planId}`, { checklist: pocReadChecklist() }, "PUT");
    plan.checklist = saved.checklist;
    plan.updated_at = saved.updated_at;
    pocSetNote("Saved");
  } catch (error) {
    pocSetNote(`Couldn’t save: ${error.message}`);
  }
}

function pocChecklistText() {
  const lines = pocReadChecklist().map((item) => `- [${item.done ? "x" : " "}] ${item.text}`);
  return [
    poc.plan.title,
    `Industry: ${poc.plan.industry}`,
    "",
    ...lines,
    "",
    "Draft pilot proposal built from the research summary. Not a result the research showed.",
  ].join("\n");
}

// ---------- generating and saving a plan ----------

// A pilot plan belongs to an adaptation (a brief applied to one industry). Reuse
// the one for this brief and industry, or create it with this use case in it.
async function pocAdaptationFor(briefId, industry, useCase) {
  const wanted = industry.toLowerCase();
  let adaptation = poc.adaptations.find((a) => (a.industry || "").toLowerCase() === wanted);

  if (!adaptation) {
    adaptation = await api(`/api/briefs/${briefId}/adaptations`, {
      industry, use_cases: [useCase], created_by: poc.name.trim(),
    });
    poc.adaptations.unshift(adaptation);
  } else if (!(adaptation.use_cases || []).some((item) => pocUseCaseLabel(item) === useCase)) {
    const updated = await api(`/api/adaptations/${adaptation.id}`,
      { use_cases: [...(adaptation.use_cases || []), useCase] }, "PUT");
    poc.adaptations = poc.adaptations.map((a) => (a.id === updated.id ? updated : a));
    adaptation = updated;
  }
  return adaptation.id;
}

async function pocGenerate() {
  const useCase = poc.useCase.replace(/\s+/g, " ").trim();
  if (poc.busy) return;
  if (!useCase) {
    poc.error = "Pick a use case or write your own first.";
    pocDraw("#poc-usecase");
    return;
  }

  const briefId = poc.briefId;
  const industry = poc.industry;
  const answers = pocAnswers();

  poc.busy = true;
  poc.error = "";
  pocDraw();

  try {
    // 1 model call. Nothing is saved until it works, so a failure leaves no half-made plan.
    const { checklist } = await api(`/api/briefs/${briefId}/pilot-checklist`,
      { industry, use_case: useCase, answers });

    const adaptationId = await pocAdaptationFor(briefId, industry, useCase);
    const plan = await api(`/api/adaptations/${adaptationId}/pilot-plans`, {
      title: `Pilot: ${useCase}`.slice(0, 120),   // titles are capped at 120 characters
      use_case: useCase,
      answers,
      checklist,
      created_by: poc.name.trim(),
    });

    if (poc.briefId !== briefId) return;   // moved to another brief while waiting
    poc.plans.unshift(plan);
    poc.plan = plan;
    poc.saveNote = "Saved";
    poc.busy = false;
    pocDraw("#poc-plan h3");
    document.getElementById("poc-plan")?.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    if (poc.briefId !== briefId) return;
    poc.busy = false;
    poc.error = error.message;
    pocDraw();
  }
}

function pocOpenPlan(planId) {
  const plan = poc.plans.find((p) => p.id === planId);
  if (!plan) return;

  poc.plan = plan;
  poc.industry = plan.industry || poc.industry;
  poc.useCase = typeof plan.use_case === "string" ? plan.use_case : pocUseCaseLabel(plan.use_case);
  poc.answers = { ...(plan.answers || {}) };
  poc.error = "";
  poc.saveNote = "";
  pocDraw("#poc-plan h3");
  document.getElementById("poc-plan")?.scrollIntoView({ behavior: "smooth", block: "start" });
}

// The first click asks for confirmation; the second deletes
async function pocDeletePlan(planId) {
  if (poc.confirmDelete !== planId) {
    poc.confirmDelete = planId;
    pocDraw(`[data-poc-delete="${planId}"]`);
    return;
  }

  poc.confirmDelete = "";
  try {
    await api(`/api/pilot-plans/${planId}`, undefined, "DELETE");
    poc.plans = poc.plans.filter((p) => p.id !== planId);
    if (poc.plan && poc.plan.id === planId) poc.plan = null;
    toast("Pilot plan deleted");
  } catch (error) {
    poc.error = error.message;
  }
  pocDraw();
}

// ---------- events ----------

function pocClick(event) {
  const button = event.target.closest("button");
  if (!button) return;
  const data = button.dataset;

  if (data.pocIndustry) {
    poc.industry = data.pocIndustry;
    pocDraw(`[data-poc-industry="${data.pocIndustry}"]`);
  } else if (data.pocUsecase !== undefined) {
    poc.useCase = (pocSavedUseCases()[Number(data.pocUsecase)] || "").slice(0, POC_USE_CASE_LIMIT);
    pocDraw("#poc-usecase");
  } else if (data.pocOpen) {
    pocOpenPlan(data.pocOpen);
  } else if (data.pocDelete) {
    pocDeletePlan(data.pocDelete);
  } else if (data.pocRemove !== undefined) {
    button.closest(".poc-item").remove();
    pocSave();
  } else if (button.id === "poc-add") {
    const list = document.getElementById("poc-list");
    list.insertAdjacentHTML("beforeend", pocItemHtml({ text: "", done: false }));
    list.lastElementChild.querySelector(".poc-text").focus();
  } else if (button.id === "poc-copy") {
    copyText(pocChecklistText(), "Checklist copied");
  } else if (button.id === "poc-close") {
    poc.plan = null;
    poc.saveNote = "";
    pocDraw();
  }
}

// Typing in the form is kept in `poc`, so a redraw never loses it
function pocInput(event) {
  const field = event.target;

  if (field.id === "poc-usecase") {
    poc.useCase = field.value;
  } else if (field.id === "poc-name") {
    poc.name = field.value;
    try { localStorage.setItem("pocName", field.value); } catch { /* private window */ }
  } else if (field.dataset.pocAnswer !== undefined) {
    poc.answers[POC_QUESTIONS[Number(field.dataset.pocAnswer)].label] = field.value;
  }
}

// A tick or a finished edit (the change event fires when a step box loses focus)
function pocChange(event) {
  const field = event.target;

  if (field.matches(".poc-check")) {
    field.closest(".poc-item").classList.toggle("poc-item--done", field.checked);
    pocSave();
  } else if (field.matches(".poc-text")) {
    pocSave();
  }
}

// Enter finishes editing a step instead of adding a line break
function pocKeydown(event) {
  if (event.key === "Enter" && event.target.matches(".poc-text")) {
    event.preventDefault();
    event.target.blur();
  }
}

async function pocLoad(briefId) {
  poc.loaded = true;
  try {
    const [adaptations, plans] = await Promise.all([
      api(`/api/briefs/${briefId}/adaptations`),
      api(`/api/pilot-plans?brief_id=${encodeURIComponent(briefId)}`),
    ]);
    if (poc.briefId !== briefId) return;
    poc.adaptations = adaptations;
    poc.plans = plans;
    pocDraw();
  } catch {
    // The starter still works without saved items, so say nothing
  }
}

// app.js calls this after it draws the brief page
function bindPocStarter(briefId) {
  pocSwitchBrief(briefId);
  const section = document.getElementById("poc-starter");
  if (!section) return;

  section.addEventListener("click", pocClick);
  section.addEventListener("input", pocInput);
  section.addEventListener("change", pocChange);
  section.addEventListener("keydown", pocKeydown);
  section.addEventListener("submit", (event) => {
    event.preventDefault();
    pocGenerate();
  });

  if (!poc.loaded) pocLoad(briefId);
}
