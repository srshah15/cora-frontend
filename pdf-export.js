// Builds the operational plan PDF in the browser with jsPDF + autotable.
// Returns a jsPDF doc; the caller decides whether to .save() it.
window.buildPlanPdf = function buildPlanPdf(plan, { reviewed, isFlagged, sections, itemsFor }) {
  const { jsPDF } = window.jspdf;
  const doc = new jsPDF({ unit: "pt", format: "letter" });

  const M = 40; // page margin
  const W = doc.internal.pageSize.getWidth();
  const H = doc.internal.pageSize.getHeight();
  const C = {
    text: [22, 32, 44],
    muted: [90, 102, 117],
    border: [227, 230, 235],
    accent: [47, 111, 176],
    headFill: [241, 243, 246],
    warn: [162, 97, 11],
    warnFill: [253, 243, 226],
    ok: [44, 122, 75],
  };

  // Standard PDF fonts only cover basic Latin, so swap out characters they can't draw.
  const clean = (s) =>
    String(s ?? "")
      .replace(/[–—]/g, "-")
      .replace(/[‘’]/g, "'")
      .replace(/[“”]/g, '"')
      .replace(/[^\x00-\xFF]/g, "");

  const p = plan.protocol || {};
  let y = M;

  // ---------- header ----------
  doc.setFont("helvetica", "bold").setFontSize(9).setTextColor(...C.accent);
  doc.text("OPERATIONAL PLAN  ·  DRAFT FOR REVIEW", M, y);
  if (plan.is_sample) {
    doc.setTextColor(...C.muted).text("SAMPLE DATA (FICTIONAL PROTOCOL)", W - M, y, { align: "right" });
  }
  y += 20;

  doc.setFont("helvetica", "bold").setFontSize(16).setTextColor(...C.text);
  const titleLines = doc.splitTextToSize(clean(p.title || "Untitled protocol"), W - 2 * M);
  doc.text(titleLines, M, y);
  y += titleLines.length * 19;

  doc.setFont("helvetica", "normal").setFontSize(9).setTextColor(...C.muted);
  const sub = [p.registry_id, p.pages && `${p.pages} pages`, `Generated ${new Date().toLocaleDateString()}`]
    .filter(Boolean)
    .join("  ·  ");
  doc.text(clean(sub), M, y);
  y += 16;

  // ---------- review banner ----------
  let open = 0, done = 0;
  for (const s of sections) {
    itemsFor(s.key).forEach((it, i) => {
      if (!isFlagged(it)) return;
      reviewed.has(`${s.key}:${i}`) ? done++ : open++;
    });
  }
  const bannerText = open
    ? `${open} item${open === 1 ? "" : "s"} still need${open === 1 ? "s" : ""} human review (highlighted below).` +
      (done ? ` ${done} already reviewed.` : "")
    : done
      ? `All ${done} flagged items have been reviewed.`
      : "No low-confidence items were flagged.";
  doc.setFillColor(...(open ? C.warnFill : [229, 243, 234]));
  doc.roundedRect(M, y, W - 2 * M, 26, 4, 4, "F");
  doc.setFont("helvetica", "bold").setFontSize(9.5).setTextColor(...(open ? C.warn : C.ok));
  doc.text(clean(bannerText), M + 10, y + 16.5);
  y += 38;

  // ---------- study facts ----------
  const facts = [
    ["Phase", p.phase], ["Sponsor", p.sponsor],
    ["Therapeutic area", p.therapeutic_area], ["Enrollment", p.enrollment],
    ["Design", p.design], ["Duration", p.duration],
  ].filter(([, v]) => v != null && v !== "");
  const factRows = [];
  for (let i = 0; i < facts.length; i += 2) {
    factRows.push([facts[i][0], clean(facts[i][1]), facts[i + 1]?.[0] ?? "", clean(facts[i + 1]?.[1] ?? "")]);
  }
  doc.autoTable({
    startY: y,
    margin: { left: M, right: M },
    body: factRows,
    theme: "plain",
    styles: { fontSize: 9, cellPadding: { top: 3, bottom: 3, left: 0, right: 8 }, textColor: C.text },
    columnStyles: {
      0: { textColor: C.muted, cellWidth: 80 },
      2: { textColor: C.muted, cellWidth: 80 },
    },
  });
  y = doc.lastAutoTable.finalY + 8;

  // ---------- sections ----------
  const status = (key, i, it) =>
    !isFlagged(it) ? "" : reviewed.has(`${key}:${i}`) ? "Reviewed" : "REVIEW";
  const conf = (it) => (typeof it.confidence === "number" ? `${Math.round(it.confidence * 100)}%` : "");
  const withNotes = (main, it) => {
    let s = clean(main);
    if (it.notes) s += `\nNote: ${clean(it.notes)}`;
    if (it.source_page) s += `\n(p. ${it.source_page})`;
    return s;
  };

  function heading(label, sub) {
    if (y > H - 110) { doc.addPage(); y = M; }
    y += 14;
    doc.setFont("helvetica", "bold").setFontSize(12).setTextColor(...C.text);
    doc.text(label, M, y);
    if (sub) {
      doc.setFont("helvetica", "normal").setFontSize(8.5).setTextColor(...C.muted);
      doc.text(clean(sub), M, y + 12);
      y += 12;
    }
    y += 6;
  }

  const baseTable = {
    margin: { left: M, right: M, bottom: 50 },
    theme: "grid",
    styles: { fontSize: 8.5, cellPadding: 5, textColor: C.text, lineColor: C.border, lineWidth: 0.5, valign: "top" },
    headStyles: { fillColor: C.headFill, textColor: C.muted, fontStyle: "bold", fontSize: 8 },
  };

  // Generic table: first column carries notes/page ref; confidence + status at the end.
  function listTable(key, cols) {
    const items = itemsFor(key);
    if (!items.length) return emptyNote("Nothing found in the protocol for this category.");
    const flags = items.map((it, i) => status(key, i, it));
    doc.autoTable({
      ...baseTable,
      startY: y,
      head: [[...cols.map((c) => c.label), "Conf.", "Status"]],
      body: items.map((it, i) => [
        ...cols.map((c, ci) => {
          const v = c.value ? c.value(it) : it[c.field];
          return ci === 0 ? withNotes(v, it) : clean(v);
        }),
        conf(it),
        flags[i],
      ]),
      columnStyles: {
        0: { fontStyle: "bold" },
        [cols.length]: { halign: "right", cellWidth: 38 },
        [cols.length + 1]: { cellWidth: 52 },
      },
      didParseCell: (d) => styleFlagRow(d, flags, cols.length + 1),
    });
    y = doc.lastAutoTable.finalY + 6;
  }

  function styleFlagRow(d, flags, statusCol) {
    if (d.section !== "body") return;
    const f = flags[d.row.index];
    if (f === "REVIEW") d.cell.styles.fillColor = C.warnFill;
    if (d.column.index === statusCol) {
      d.cell.styles.fontStyle = "bold";
      d.cell.styles.textColor = f === "REVIEW" ? C.warn : C.ok;
    }
  }

  function emptyNote(msg) {
    doc.setFont("helvetica", "italic").setFontSize(9).setTextColor(...C.muted);
    doc.text(msg, M, y + 10);
    y += 18;
  }

  const visits = plan.visits || [];

  const RENDER = {
    visits() {
      if (!visits.length) return emptyNote("No visits extracted.");
      doc.autoTable({
        ...baseTable,
        startY: y,
        head: [["ID", "Visit", "Day", "Window", "Type"]],
        body: visits.map((v) => [v.id, clean(v.name), clean(v.day), clean(v.window || "-"), clean(v.type || "")]),
        columnStyles: { 0: { cellWidth: 36, textColor: C.accent, fontStyle: "bold" }, 1: { fontStyle: "bold" } },
      });
      y = doc.lastAutoTable.finalY + 6;
    },

    procedures() {
      const procs = plan.procedures || [];
      if (!procs.length) return emptyNote("No procedures extracted.");
      const flags = procs.map((it, i) => status("procedures", i, it));
      const statusCol = visits.length + 2;
      doc.autoTable({
        ...baseTable,
        startY: y,
        head: [["Procedure", ...visits.map((v) => v.id), "Conf.", "Status"]],
        body: procs.map((pr, i) => [
          withNotes(pr.name, pr),
          ...visits.map((v) => ({ content: "", mark: pr.visits?.includes(v.id) })),
          conf(pr),
          flags[i],
        ]),
        columnStyles: {
          0: { fontStyle: "bold" },
          ...Object.fromEntries(visits.map((_, i) => [i + 1, { halign: "center", cellWidth: 26 }])),
          [statusCol - 1]: { halign: "right", cellWidth: 38 },
          [statusCol]: { cellWidth: 52 },
        },
        didParseCell: (d) => {
          if (d.section === "head" && d.column.index > 0 && d.column.index <= visits.length) d.cell.styles.halign = "center";
          styleFlagRow(d, flags, statusCol);
        },
        didDrawCell: (d) => {
          if (d.section === "body" && d.cell.raw?.mark) {
            doc.setFillColor(...C.accent);
            doc.circle(d.cell.x + d.cell.width / 2, d.cell.y + 9, 2.6, "F");
          }
        },
      });
      y = doc.lastAutoTable.finalY + 4;
      doc.setFont("helvetica", "normal").setFontSize(7.5).setTextColor(...C.muted);
      const legend = visits.map((v) => `${v.id} = ${v.name}`).join("   ");
      const lines = doc.splitTextToSize(clean(legend), W - 2 * M);
      doc.text(lines, M, y + 8);
      y += lines.length * 9 + 8;
    },

    staffing() {
      listTable("staffing", [
        { label: "Role", field: "role" },
        { label: "Est. FTE", field: "fte" },
        { label: "Responsibilities", field: "responsibilities" },
      ]);
      const fte = (plan.staffing || []).reduce((n, s) => n + (Number(s.fte) || 0), 0);
      if (fte) {
        doc.setFont("helvetica", "bold").setFontSize(8.5).setTextColor(...C.text);
        doc.text(`Total estimated FTE: ${fte.toFixed(2)}`, M, y + 8);
        y += 14;
      }
    },

    safety() {
      listTable("safety", [
        { label: "Event", field: "event" },
        { label: "Timeline", field: "timeline" },
        { label: "Report to", field: "recipient" },
        { label: "Method", field: "method" },
      ]);
    },

    billing() {
      listTable("billing", [
        { label: "Item", field: "item" },
        { label: "Paid by", field: "designation" },
        { label: "Visits", value: (b) => (b.visits || []).join(", ") },
      ]);
    },

    equipment() {
      listTable("equipment", [
        { label: "Item", field: "item" },
        { label: "Purpose", field: "purpose" },
      ]);
    },

    pharmacy() {
      if (!plan.pharmacy) return emptyNote("No pharmacy info extracted.");
      listTable("pharmacy", [{ label: "Requirement", field: "item" }]);
    },

    technology() {
      listTable("technology", [
        { label: "System", field: "system" },
        { label: "Purpose", field: "purpose" },
      ]);
    },
  };

  const SUBS = {
    procedures: "Schedule of assessments. A dot means the procedure happens at that visit.",
    billing: "Sponsor = billed to the study. Standard of care = billed as routine care. Confirm with a coverage analysis.",
    pharmacy: plan.pharmacy ? `Investigational pharmacy ${plan.pharmacy.involved ? "is" : "is not"} involved.` : "",
  };

  for (const s of sections) {
    heading(s.label, SUBS[s.key]);
    RENDER[s.key]();
  }

  // ---------- sign-off ----------
  if (y > H - 130) { doc.addPage(); y = M; }
  y += 24;
  doc.setFont("helvetica", "bold").setFontSize(12).setTextColor(...C.text);
  doc.text("Reviewer sign-off", M, y);
  y += 8;
  doc.setFont("helvetica", "normal").setFontSize(8.5).setTextColor(...C.muted);
  const disclaimer = doc.splitTextToSize(
    "This plan was drafted automatically from the protocol text and may contain errors. It must be checked against the protocol by qualified study staff before use.",
    W - 2 * M
  );
  doc.text(disclaimer, M, y + 10);
  y += disclaimer.length * 10 + 30;
  doc.setDrawColor(...C.muted).setLineWidth(0.5);
  const col = (W - 2 * M - 30) / 3;
  ["Reviewed by", "Signature", "Date"].forEach((label, i) => {
    const x = M + i * (col + 15);
    doc.line(x, y, x + col, y);
    doc.text(label, x, y + 11);
  });

  // ---------- footer on every page ----------
  const pages = doc.getNumberOfPages();
  for (let i = 1; i <= pages; i++) {
    doc.setPage(i);
    doc.setFont("helvetica", "normal").setFontSize(7.5).setTextColor(...C.muted);
    doc.text(clean(`CORA  ·  ${p.short_title || p.registry_id || ""}  ·  Draft, not for clinical use without review`), M, H - 24);
    doc.text(`Page ${i} of ${pages}`, W - M, H - 24, { align: "right" });
  }

  return doc;
};
