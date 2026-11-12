import { describe, expect, it } from "vitest";

import { SAMPLE_PLAN } from "../data/samplePlan.js";
import { buildPlanPdf } from "./pdfExport.js";
import { orderedSections } from "./roles.js";

// jsPDF writes text into the file uncompressed by default, so the section
// headings can be found in the output in the order they were drawn.
const positions = (pdf, labels) => labels.map((l) => pdf.indexOf(`(${l})`));

describe("PDF export", () => {
  it("builds a PDF with every section, review highlights and the sign-off block", () => {
    const pdf = buildPlanPdf(SAMPLE_PLAN, { reviews: {}, reviewer: "Ana Reviewer" }).output();
    expect(pdf.startsWith("%PDF")).toBe(true);
    for (const label of ["Visit schedule", "Procedures", "Staffing", "Safety reporting", "Billing", "Equipment", "Pharmacy", "Technology"]) {
      expect(pdf).toContain(`(${label})`);
    }
    expect(pdf).toContain("still need");       // the review banner
    expect(pdf).toContain("Reviewer sign-off");
    expect(pdf).toContain("Ana Reviewer");
  });

  it("puts the role's sections first", () => {
    const pdf = buildPlanPdf(SAMPLE_PLAN, { sections: orderedSections("manager") }).output();
    const [staffing, safety, visits] = positions(pdf, ["Staffing", "Safety reporting", "Visit schedule"]);
    expect(staffing).toBeGreaterThan(-1);
    expect(staffing).toBeLessThan(safety);
    expect(safety).toBeLessThan(visits);
  });

  it("copes with an almost empty plan", () => {
    const pdf = buildPlanPdf({ protocol: {}, visits: [], procedures: [] }).output();
    expect(pdf).toContain("No visits extracted.");
    expect(pdf).toContain("No pharmacy info extracted.");
    expect(pdf).toContain("No low-confidence items were flagged.");
  });
});
