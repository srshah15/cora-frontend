(() => {
  const { apiBase, reviewThreshold } = window.APP_CONFIG;
  const $ = (id) => document.getElementById(id);

  const state = {
    plan: null,
    // Reviewer decisions, keyed like "safety:2":
    // { status: "accepted" | "edited" | "rejected", comment, reviewer, at, original }
    reviews: new Map(),
    flaggedOnly: false,
    pdfUrl: null, // object URL of the uploaded PDF, for the source pane
    queue: [], // flagged item keys, in plan order
    qi: 0, // index into queue; -1 means everything is reviewed
  };

  const SECTIONS = [
    { key: "visits", label: "Visit schedule" },
    { key: "procedures", label: "Procedures" },
    { key: "staffing", label: "Staffing" },
    { key: "safety", label: "Safety reporting" },
    { key: "billing", label: "Billing" },
    { key: "equipment", label: "Equipment" },
    { key: "pharmacy", label: "Pharmacy" },
    { key: "technology", label: "Technology" },
  ];

  // ---------- helpers ----------
  const esc = (s) =>
    String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const isFlagged = (item) => typeof item.confidence === "number" && item.confidence < reviewThreshold;

  function itemsFor(key) {
    const p = state.plan;
    if (key === "pharmacy") return p.pharmacy?.items || [];
    return p[key] || [];
  }

  // Flagged and no decision yet.
  const isOpen = (it, k) => isFlagged(it) && !state.reviews.has(k);

  function openFlags(key) {
    return itemsFor(key).filter((it, i) => isOpen(it, `${key}:${i}`)).length;
  }

  const STATUS_LABEL = { accepted: "Accepted", edited: "Edited", rejected: "Rejected" };

  function showView(name) {
    for (const v of ["uploadView", "processingView", "resultsView", "reviewView"]) $(v).hidden = v !== name;
    $("newBtn").hidden = name === "uploadView";
    window.scrollTo(0, 0);
  }

  let toastTimer;
  function toast(msg) {
    const t = $("toast");
    t.textContent = msg;
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (t.hidden = true), 3500);
  }

  function setMode(isSample) {
    const pill = $("modePill");
    pill.hidden = false;
    pill.textContent = isSample ? "Sample data" : "Draft, needs review";
    pill.className = "pill " + (isSample ? "pill-muted" : "pill-warn");
  }

  // ---------- upload ----------
  const dz = $("dropzone");
  const fileInput = $("fileInput");

  dz.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInput.click(); }
  });
  ["dragenter", "dragover"].forEach((ev) =>
    dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("drag"); })
  );
  ["dragleave", "drop"].forEach((ev) =>
    dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("drag"); })
  );
  dz.addEventListener("drop", (e) => {
    const f = e.dataTransfer.files?.[0];
    if (f) handleFile(f);
  });
  fileInput.addEventListener("change", () => {
    const f = fileInput.files?.[0];
    if (f) handleFile(f);
    fileInput.value = "";
  });

  $("sampleBtn").addEventListener("click", () => runSample());
  $("newBtn").addEventListener("click", () => {
    state.plan = null;
    state.reviews.clear();
    setPdf(null);
    $("modePill").hidden = true;
    $("uploadError").hidden = true;
    showView("uploadView");
  });

  function showUploadError(html) {
    const el = $("uploadError");
    el.innerHTML = html;
    el.hidden = false;
    showView("uploadView");
  }

  async function handleFile(file) {
    $("uploadError").hidden = true;
    if (!/\.pdf$/i.test(file.name) && file.type !== "application/pdf") {
      return showUploadError("That doesn't look like a PDF. Protocols need to be uploaded as <code>.pdf</code> files.");
    }
    if (file.size > 50 * 1024 * 1024) {
      return showUploadError("That file is over 50 MB. Try a smaller protocol or split the appendices out.");
    }

    const stepper = startProcessing(file.name);
    try {
      const body = new FormData();
      body.append("file", file);
      const res = await fetch(`${apiBase}/api/protocols`, { method: "POST", body });
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        let detail = text;
        try { detail = JSON.parse(text).detail || text; } catch {}
        throw new Error(detail ? String(detail).slice(0, 200) : `Server returned ${res.status}`);
      }
      const plan = await res.json();
      await stepper.finish();
      setPdf(file);
      loadPlan(plan);
    } catch (err) {
      stepper.stop();
      const unreachable = err instanceof TypeError; // fetch network failure
      showUploadError(
        (unreachable
          ? `Couldn't reach the backend at <code>${esc(apiBase)}</code>. Is the FastAPI server running?`
          : `Processing failed. ${esc(err.message)}`) +
          ` <button class="link-btn" id="fallbackSample">View sample output instead</button>`
      );
      $("fallbackSample").addEventListener("click", runSample);
    }
  }

  async function runSample() {
    const stepper = startProcessing("sample-protocol-xr214.pdf");
    await stepper.finish(900);
    setPdf(null);
    loadPlan(structuredClone(window.SAMPLE_PLAN));
  }

  // Keeps the uploaded PDF around so reviewers can check items against it.
  function setPdf(file) {
    if (state.pdfUrl) URL.revokeObjectURL(state.pdfUrl);
    state.pdfUrl = file ? URL.createObjectURL(file) : null;
  }

  // Walks through the pipeline steps on a timer. The backend is a single request
  // for now, so this is cosmetic until we add progress events.
  function startProcessing(filename) {
    showView("processingView");
    $("processingFile").textContent = filename;
    const steps = [...document.querySelectorAll("#steps li")];
    steps.forEach((s) => (s.className = ""));
    let i = 0;
    steps[0].className = "active";
    const timer = setInterval(() => {
      if (i < steps.length - 1) {
        steps[i].className = "done";
        steps[++i].className = "active";
      }
    }, 1400);

    return {
      stop: () => clearInterval(timer),
      finish: (perStep = 250) =>
        new Promise((resolve) => {
          clearInterval(timer);
          const tick = () => {
            steps[i].className = "done";
            if (i < steps.length - 1) {
              steps[++i].className = "active";
              setTimeout(tick, perStep);
            } else setTimeout(resolve, 300);
          };
          setTimeout(tick, perStep);
        }),
    };
  }

  // ---------- results ----------
  function loadPlan(plan) {
    state.plan = plan;
    state.reviews.clear();
    setMode(!!plan.is_sample);
    showView("resultsView");
    render();
  }

  $("flaggedOnly").addEventListener("change", (e) => {
    state.flaggedOnly = e.target.checked;
    renderSections();
  });

  function render() {
    renderSummary();
    renderNav();
    renderSections();
  }

  function totalFlags() {
    return SECTIONS.reduce((n, s) => n + openFlags(s.key), 0);
  }

  function renderSummary() {
    const p = state.plan.protocol;
    const flags = totalFlags();
    $("summary").innerHTML = `
      <div class="summary card">
        <div class="summary-head">
          <div>
            <div class="eyebrow">${esc(p.registry_id || "")}${p.pages ? ` · ${p.pages} pages` : ""}</div>
            <h1 class="summary-title">${esc(p.title)}</h1>
          </div>
          <div class="summary-actions">
            ${flags ? `<button class="btn btn-primary" id="startReview">Review ${flags} flagged</button>` : ""}
            <button class="btn ${flags ? "btn-secondary" : "btn-primary"}" id="exportPdf">Download PDF</button>
          </div>
        </div>
        <dl class="facts">
          ${fact("Phase", p.phase)}
          ${fact("Sponsor", p.sponsor)}
          ${fact("Therapeutic area", p.therapeutic_area)}
          ${fact("Enrollment", p.enrollment)}
          ${fact("Design", p.design)}
          ${fact("Duration", p.duration)}
        </dl>
        ${state.plan.extraction === "keyword" ? `<p class="extraction-note">Early draft: CORA found these items by searching the protocol text for keywords, and each one links to the page it came from. The visit schedule, staffing and billing aren't extracted yet.</p>` : ""}
        <div class="summary-stats">
          ${stat(state.plan.visits?.length ?? 0, "visits")}
          ${stat(state.plan.procedures?.length ?? 0, "procedures")}
          ${stat(fteTotal().toFixed(2), "est. FTE")}
          <div class="stat ${flags ? "stat-warn" : "stat-ok"}"><strong>${flags}</strong><span>${flags === 1 ? "item needs" : "items need"} review</span></div>
        </div>
      </div>`;
    $("exportPdf").addEventListener("click", exportPdf);
    $("startReview")?.addEventListener("click", () => openReview());
  }

  const fact = (k, v) => (v == null || v === "" ? "" : `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`);
  const stat = (n, label) => `<div class="stat"><strong>${esc(n)}</strong><span>${esc(label)}</span></div>`;
  const fteTotal = () => (state.plan.staffing || []).reduce((n, s) => n + (Number(s.fte) || 0), 0);

  function renderNav() {
    $("sectionNav").innerHTML = SECTIONS.map((s) => {
      const n = openFlags(s.key);
      return `<a href="#sec-${s.key}">${esc(s.label)}${n ? `<span class="badge-count">${n}</span>` : ""}</a>`;
    }).join("");
  }

  function renderSections() {
    const html = SECTIONS.map((s) => {
      const body = RENDERERS[s.key]();
      return `<section class="card section" id="sec-${s.key}">
        <header class="section-head"><h2>${esc(s.label)}</h2>${sectionMeta(s.key)}</header>
        ${body}
      </section>`;
    }).join("");
    $("sections").innerHTML = html;
    bindReviewButtons();
  }

  function sectionMeta(key) {
    const n = openFlags(key);
    return n ? `<span class="pill pill-warn">${n} to review</span>` : `<span class="pill pill-ok">Looks good</span>`;
  }

  // Rows for list-style sections, with review badges and filtering.
  function rows(key, cols) {
    const items = itemsFor(key);
    const visible = items
      .map((it, i) => ({ it, i }))
      .filter(({ it, i }) => !state.flaggedOnly || isOpen(it, `${key}:${i}`));
    if (!items.length) return `<p class="empty">Nothing found in the protocol for this category.</p>`;
    if (!visible.length) return `<p class="empty">No open flags here.</p>`;

    return `<div class="table-wrap"><table class="data">
      <thead><tr>${cols.map((c) => `<th>${esc(c.label)}</th>`).join("")}<th class="col-conf">Confidence</th></tr></thead>
      <tbody>${visible
        .map(({ it, i }) => {
          const k = `${key}:${i}`;
          const flagged = isOpen(it, k);
          return `<tr class="${rowClass(it, k)}">
            ${cols.map((c, ci) => `<td${ci === 0 ? ' class="cell-main"' : ""}>${c.render ? c.render(it) : esc(it[c.field])}${ci === 0 ? noteFor(it, k, flagged) : ""}</td>`).join("")}
            <td class="col-conf">${confCell(it, k)}</td>
          </tr>`;
        })
        .join("")}</tbody>
    </table></div>`;
  }

  function rowClass(it, k) {
    if (isOpen(it, k)) return "row-flag";
    return state.reviews.get(k)?.status === "rejected" ? "row-rejected" : "";
  }

  function noteFor(it, k, flagged) {
    const bits = [];
    if (it.notes) bits.push(`<div class="note ${flagged ? "note-warn" : ""}">${esc(it.notes)}</div>`);
    const r = state.reviews.get(k);
    if (r?.comment) bits.push(`<div class="note note-review">${esc(r.reviewer || "Reviewer")}: ${esc(r.comment)}</div>`);
    if (it.source_page) bits.push(`<div class="src">p. ${esc(it.source_page)}</div>`);
    return bits.join("");
  }

  function confCell(it, k) {
    if (typeof it.confidence !== "number") return "";
    const pct = Math.round(it.confidence * 100);
    const flagged = isFlagged(it);
    let html = `<div class="conf"><div class="conf-bar"><span style="width:${pct}%" class="${flagged ? "low" : ""}"></span></div><span class="mono">${pct}%</span></div>`;
    if (flagged) {
      const r = state.reviews.get(k);
      html += r
        ? `<button class="review-btn ${r.status}" data-key="${k}">${STATUS_LABEL[r.status]}</button>`
        : `<button class="review-btn" data-key="${k}">Review</button>`;
    }
    return html;
  }

  function bindReviewButtons() {
    document.querySelectorAll(".review-btn").forEach((b) =>
      b.addEventListener("click", () => openReview(b.dataset.key))
    );
  }

  const visitNames = (ids) => (ids || []).map((id) => `<span class="chip">${esc(id)}</span>`).join(" ");

  const RENDERERS = {
    visits() {
      const visits = state.plan.visits || [];
      if (!visits.length) return `<p class="empty">No visits extracted.</p>`;
      return `<ol class="timeline">${visits
        .map(
          (v) => `<li class="${v.type === "Phone" ? "remote" : ""}">
            <span class="tl-dot"></span>
            <div class="tl-id mono">${esc(v.id)}</div>
            <div class="tl-name">${esc(v.name)}</div>
            <div class="tl-day">${esc(v.day)}${v.window ? ` <span class="muted">${esc(v.window)}</span>` : ""}</div>
            <div class="tl-type">${esc(v.type || "")}</div>
          </li>`
        )
        .join("")}</ol>`;
    },

    procedures() {
      const visits = state.plan.visits || [];
      const procs = (state.plan.procedures || [])
        .map((p, i) => ({ p, i }))
        .filter(({ p, i }) => !state.flaggedOnly || isOpen(p, `procedures:${i}`));
      if (!state.plan.procedures?.length) return `<p class="empty">No procedures extracted.</p>`;
      if (!procs.length) return `<p class="empty">No open flags here.</p>`;

      return `<p class="section-sub">${visits.length
        ? "Schedule of assessments. Each mark is a procedure required at that visit."
        : "Procedures mentioned in the protocol. Which visit each one happens at isn't extracted yet."}</p>
      <div class="table-wrap"><table class="soa">
        <thead><tr><th class="sticky">Procedure</th>${visits
          .map((v) => `<th title="${esc(v.name)} · ${esc(v.day)}"><span class="mono">${esc(v.id)}</span></th>`)
          .join("")}<th class="col-conf">Confidence</th></tr></thead>
        <tbody>${procs
          .map(({ p, i }) => {
            const k = `procedures:${i}`;
            const flagged = isOpen(p, k);
            return `<tr class="${rowClass(p, k)}">
              <td class="sticky cell-main">${esc(p.name)} <span class="cat">${esc(p.category || "")}</span>${noteFor(p, k, flagged)}</td>
              ${visits.map((v) => `<td class="mark">${p.visits?.includes(v.id) ? "●" : ""}</td>`).join("")}
              <td class="col-conf">${confCell(p, k)}</td>
            </tr>`;
          })
          .join("")}</tbody>
      </table></div>`;
    },

    staffing() {
      return rows("staffing", [
        { label: "Role", field: "role" },
        { label: "Est. FTE", render: (s) => `<span class="mono">${esc(s.fte)}</span>` },
        { label: "Responsibilities", field: "responsibilities" },
      ]);
    },

    safety() {
      return rows("safety", [
        { label: "Event", field: "event" },
        { label: "Timeline", field: "timeline" },
        { label: "Report to", field: "recipient" },
        { label: "Method", field: "method" },
      ]);
    },

    billing() {
      return rows("billing", [
        { label: "Item", field: "item" },
        {
          label: "Designation",
          render: (b) => {
            const cls = /sponsor/i.test(b.designation) ? "tag-sponsor" : /standard|soc/i.test(b.designation) ? "tag-soc" : "tag-other";
            return `<span class="tag ${cls}">${esc(b.designation)}</span>`;
          },
        },
        { label: "Visits", render: (b) => visitNames(b.visits) },
      ]);
    },

    equipment() {
      return rows("equipment", [
        { label: "Item", field: "item" },
        { label: "Purpose", field: "purpose" },
      ]);
    },

    pharmacy() {
      const ph = state.plan.pharmacy;
      if (!ph) return `<p class="empty">No pharmacy info extracted.</p>`;
      const head = `<p class="section-sub">Investigational pharmacy ${ph.involved ? "<strong>is</strong>" : "is <strong>not</strong>"} involved.</p>`;
      return head + rows("pharmacy", [{ label: "Requirement", field: "item" }]);
    },

    technology() {
      return rows("technology", [
        { label: "System", field: "system" },
        { label: "Purpose", field: "purpose" },
      ]);
    },
  };

  // ---------- review ----------
  // Editable fields per section. The first field is the item's title.
  const FIELDS = {
    procedures: [
      { f: "name", label: "Procedure" },
      { f: "category", label: "Category" },
      { f: "visits", label: "Visits", type: "visits" },
    ],
    staffing: [
      { f: "role", label: "Role" },
      { f: "fte", label: "Est. FTE", type: "number" },
      { f: "responsibilities", label: "Responsibilities", type: "textarea" },
    ],
    safety: [
      { f: "event", label: "Event" },
      { f: "timeline", label: "Timeline" },
      { f: "recipient", label: "Report to" },
      { f: "method", label: "Method" },
    ],
    billing: [
      { f: "item", label: "Item" },
      { f: "designation", label: "Designation", type: "designation" },
      { f: "visits", label: "Visits", type: "visits" },
    ],
    equipment: [
      { f: "item", label: "Item" },
      { f: "purpose", label: "Purpose", type: "textarea" },
    ],
    pharmacy: [{ f: "item", label: "Requirement", type: "textarea" }],
    technology: [
      { f: "system", label: "System" },
      { f: "purpose", label: "Purpose", type: "textarea" },
    ],
  };

  const reviewerInput = $("reviewerName");
  try { reviewerInput.value = localStorage.getItem("cora.reviewer") || ""; } catch {}
  reviewerInput.addEventListener("input", () => {
    try { localStorage.setItem("cora.reviewer", reviewerInput.value.trim()); } catch {}
  });
  const reviewerName = () => reviewerInput.value.trim();

  function keyParts(k) {
    const [sec, i] = k.split(":");
    return { sec, item: itemsFor(sec)[Number(i)] };
  }

  const flaggedKeys = () =>
    SECTIONS.flatMap((s) => itemsFor(s.key).flatMap((it, i) => (isFlagged(it) ? [`${s.key}:${i}`] : [])));

  // First undecided item at or after `from`, wrapping around; -1 if none left.
  function nextOpen(from) {
    const q = state.queue;
    for (let n = 0; n < q.length; n++) {
      const j = (from + n) % q.length;
      if (!state.reviews.has(q[j])) return j;
    }
    return -1;
  }

  function openReview(k) {
    state.queue = flaggedKeys();
    if (!state.queue.length) return toast("Nothing is flagged for review.");
    state.qi = k ? state.queue.indexOf(k) : nextOpen(0);
    showView("reviewView");
    renderReview();
  }

  $("backToPlan").addEventListener("click", () => {
    const k = state.queue[state.qi];
    showView("resultsView");
    render();
    if (k) $(`sec-${k.split(":")[0]}`)?.scrollIntoView();
  });

  const fmtValue = (v) => (Array.isArray(v) ? v.join(", ") : v ?? "") || "(empty)";
  const same = (a, b) => JSON.stringify(a ?? "") === JSON.stringify(b ?? "");

  function fieldInput(fd, item, locked, original) {
    const v = item[fd.f];
    const id = `rv-${fd.f}`;
    const dis = locked ? "disabled" : "";
    let input;
    if (fd.type === "visits") {
      const visits = state.plan.visits || [];
      input = `<div class="visit-picks" id="${id}">${visits.length ? "" : `<span class="muted">No visits extracted yet</span>`}${visits
        .map(
          (vis) => `<label class="visit-pick" title="${esc(vis.name)} · ${esc(vis.day)}">
            <input type="checkbox" value="${esc(vis.id)}" ${v?.includes(vis.id) ? "checked" : ""} ${dis}>
            <span class="mono">${esc(vis.id)}</span></label>`
        )
        .join("")}</div>`;
    } else if (fd.type === "textarea") {
      input = `<textarea id="${id}" rows="3" ${dis}>${esc(v)}</textarea>`;
    } else {
      const extra = fd.type === "number" ? 'type="number" step="0.05" min="0"' : fd.type === "designation" ? 'type="text" list="designations"' : 'type="text"';
      input = `<input id="${id}" ${extra} value="${esc(v)}" ${dis}>`;
    }
    const was = original && !same(original[fd.f], v) ? `<div class="rv-was">Was: ${esc(fmtValue(original[fd.f]))}</div>` : "";
    return `<div class="rv-field"><label for="${id}">${esc(fd.label)}</label>${input}${was}</div>`;
  }

  function readForm(sec) {
    const vals = {};
    for (const fd of FIELDS[sec]) {
      const el = $(`rv-${fd.f}`);
      if (fd.type === "visits") vals[fd.f] = [...el.querySelectorAll("input:checked")].map((c) => c.value);
      else if (fd.type === "number") vals[fd.f] = el.value === "" ? "" : Number(el.value);
      else vals[fd.f] = el.value.trim();
    }
    return vals;
  }

  function renderReview() {
    const q = state.queue;
    const decided = q.filter((k) => state.reviews.has(k)).length;
    $("reviewCount").textContent = `${decided} of ${q.length} reviewed`;
    $("reviewProgress").style.width = `${(decided / q.length) * 100}%`;

    if (state.qi < 0) {
      renderSource(null);
      $("reviewPane").innerHTML = doneHtml() + queueHtml();
      bindQueue();
      $("rvDoneBack").addEventListener("click", () => $("backToPlan").click());
      $("rvDoneExport").addEventListener("click", exportPdf);
      return;
    }

    const k = q[state.qi];
    const { sec, item } = keyParts(k);
    const r = state.reviews.get(k);
    const fields = FIELDS[sec];
    const pct = Math.round(item.confidence * 100);
    const label = SECTIONS.find((s) => s.key === sec).label;

    $("reviewPane").innerHTML = `
      <div class="rv-head">
        <span class="eyebrow">${esc(label)} · ${state.qi + 1} of ${q.length}</span>
        ${r ? `<span class="pill pill-${r.status}">${STATUS_LABEL[r.status]}${r.reviewer ? ` by ${esc(r.reviewer)}` : ""}</span>` : ""}
      </div>
      <h2 class="rv-title">${esc(item[fields[0].f])}</h2>
      <div class="rv-why">
        <div class="conf"><div class="conf-bar"><span style="width:${pct}%" class="low"></span></div><span class="mono">${pct}%</span></div>
        <p>${item.notes ? esc(item.notes) : `Confidence is below the ${Math.round(reviewThreshold * 100)}% review threshold.`}</p>
      </div>
      <form id="rvForm" class="rv-form" autocomplete="off">
        ${fields.map((fd) => fieldInput(fd, item, !!r, r?.original)).join("")}
        <div class="rv-field">
          <label for="rvComment">Comment</label>
          <textarea id="rvComment" rows="2" placeholder="Optional: why you changed or rejected this" ${r ? "disabled" : ""}>${esc(r?.comment)}</textarea>
        </div>
      </form>
      <div class="rv-actions">
        <button id="rvPrev" class="btn btn-ghost" ${state.qi === 0 ? "disabled" : ""}>&larr; Prev</button>
        <span class="spacer"></span>
        ${r
          ? `<button id="rvUndo" class="btn btn-secondary">Undo decision</button>`
          : `<button id="rvReject" class="btn btn-danger">Reject</button>
             <button id="rvAccept" class="btn btn-primary">Accept</button>`}
        <button id="rvNext" class="btn btn-ghost" ${state.qi === q.length - 1 ? "disabled" : ""}>Next &rarr;</button>
      </div>
      <p class="kbd-hint">Shortcuts: <kbd>A</kbd> accept · <kbd>R</kbd> reject · <kbd>&larr;</kbd> <kbd>&rarr;</kbd> move</p>
      ${queueHtml()}`;

    renderSource(item.source_page);
    bindQueue();
    $("rvPrev").addEventListener("click", () => move(-1));
    $("rvNext").addEventListener("click", () => move(1));
    $("rvForm").addEventListener("submit", (e) => e.preventDefault());
    if (r) {
      $("rvUndo").addEventListener("click", undoDecision);
    } else {
      $("rvAccept").addEventListener("click", () => decide("accepted"));
      $("rvReject").addEventListener("click", () => decide("rejected"));
      // Relabel Accept once the reviewer changes something.
      $("rvForm").addEventListener("input", () => {
        const vals = readForm(sec);
        const edited = fields.some((fd) => !same(vals[fd.f], item[fd.f]));
        $("rvAccept").textContent = edited ? "Accept with edits" : "Accept";
      });
    }
  }

  function queueHtml() {
    return `<div class="rv-queue"><h3>Flagged items</h3><ol>${state.queue
      .map((k, j) => {
        const { sec, item } = keyParts(k);
        const r = state.reviews.get(k);
        return `<li><button data-j="${j}" class="${j === state.qi ? "current" : ""}">
          <span class="rv-q-title">${esc(item[FIELDS[sec][0].f])}</span>
          <span class="pill pill-${r ? r.status : "open"}">${r ? STATUS_LABEL[r.status] : "Open"}</span>
        </button></li>`;
      })
      .join("")}</ol></div>`;
  }

  function bindQueue() {
    document.querySelectorAll(".rv-queue button").forEach((b) =>
      b.addEventListener("click", () => {
        state.qi = Number(b.dataset.j);
        renderReview();
      })
    );
  }

  function doneHtml() {
    const counts = { accepted: 0, edited: 0, rejected: 0 };
    for (const r of state.reviews.values()) counts[r.status]++;
    return `<div class="rv-done">
      <h2>All flagged items reviewed</h2>
      <p class="muted">${counts.accepted} accepted · ${counts.edited} edited · ${counts.rejected} rejected</p>
      <div class="rv-actions">
        <button id="rvDoneBack" class="btn btn-secondary">Back to plan</button>
        <button id="rvDoneExport" class="btn btn-primary">Download PDF</button>
      </div>
    </div>`;
  }

  // Shows the uploaded PDF at the item's source page. Sample data has no PDF.
  let shownSrc = null;
  function renderSource(page) {
    const pane = $("sourcePane");
    const src = state.pdfUrl ? `${state.pdfUrl}#page=${page || 1}&navpanes=0&view=FitH` : null;
    if (src && src === shownSrc) return;
    shownSrc = src;
    if (!state.pdfUrl) {
      pane.innerHTML = `<div class="src-empty">
        <strong>Source protocol</strong>
        <p>${state.plan?.is_sample ? "The sample uses a fictional protocol, so there's no PDF to show." : "The source PDF isn't available."}
        ${page ? `In a real upload, page ${esc(page)} opens here so you can check the item against the protocol.` : ""}</p>
      </div>`;
      return;
    }
    // A fresh iframe each time: the built-in PDF viewer ignores hash changes on an open document.
    pane.innerHTML = `<div class="src-head">
        <strong>Source protocol</strong>
        <span class="muted">${page ? `p. ${esc(page)}` : "No page reference"}</span>
        <a href="${src}" target="_blank" rel="noopener">Open in new tab</a>
      </div>
      <iframe class="src-frame" src="${src}" title="Source protocol PDF"></iframe>`;
  }

  function move(d) {
    const j = state.qi + d;
    if (j < 0 || j >= state.queue.length) return;
    state.qi = j;
    renderReview();
  }

  function decide(status) {
    if (!reviewerName()) {
      reviewerInput.focus();
      return toast("Add your name first so the plan records who reviewed it.");
    }
    const k = state.queue[state.qi];
    const { sec, item } = keyParts(k);
    const fields = FIELDS[sec];
    const vals = readForm(sec);
    const original = Object.fromEntries(fields.map((fd) => [fd.f, structuredClone(item[fd.f])]));
    if (status === "accepted" && fields.some((fd) => !same(vals[fd.f], item[fd.f]))) {
      Object.assign(item, vals);
      status = "edited";
    }
    state.reviews.set(k, {
      status,
      comment: $("rvComment").value.trim(),
      reviewer: reviewerName(),
      at: new Date().toISOString(),
      original,
    });
    state.qi = nextOpen(state.qi);
    renderReview();
  }

  function undoDecision() {
    const k = state.queue[state.qi];
    const r = state.reviews.get(k);
    if (r.status === "edited") Object.assign(keyParts(k).item, r.original);
    state.reviews.delete(k);
    renderReview();
  }

  document.addEventListener("keydown", (e) => {
    if ($("reviewView").hidden || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.target.closest?.("input, textarea, select")) return;
    const act = { a: "rvAccept", r: "rvReject", ArrowLeft: "rvPrev", ArrowRight: "rvNext" }[e.key];
    const btn = act && $(act);
    if (btn && !btn.disabled) { e.preventDefault(); btn.click(); }
  });

  // ---------- export ----------
  function exportPdf() {
    if (!window.jspdf) return toast("PDF library didn't load. Check your internet connection and refresh.");
    try {
      window.buildPlanPdf(state.plan, {
        reviews: state.reviews,
        reviewer: reviewerName(),
        isFlagged,
        sections: SECTIONS,
        itemsFor,
      }).save(`${slug()}-operational-plan.pdf`);
    } catch (err) {
      console.error(err);
      toast("Couldn't generate the PDF.");
    }
  }

  const slug = () =>
    (state.plan.protocol.short_title || state.plan.protocol.registry_id || "protocol")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "");
})();
