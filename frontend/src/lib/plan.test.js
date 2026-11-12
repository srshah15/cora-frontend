import { describe, expect, it } from "vitest";

import { SAMPLE_PLAN } from "../data/samplePlan.js";
import {
  applyReviews, flaggedKeys, fteTotal, isFlagged, itemsFor, nextOpen, openFlags, slug, totalFlags, withItemValues,
} from "./plan.js";

describe("review flag at the 0.7 threshold", () => {
  it("flags confidence below 0.7", () => {
    expect(isFlagged({ confidence: 0.69 })).toBe(true);
    expect(isFlagged({ confidence: 0 })).toBe(true);
  });

  it("does not flag exactly 0.7 or above", () => {
    expect(isFlagged({ confidence: 0.7 })).toBe(false);
    expect(isFlagged({ confidence: 0.95 })).toBe(false);
  });

  it("does not flag a missing or non-numeric confidence", () => {
    expect(isFlagged({})).toBe(false);
    expect(isFlagged({ confidence: null })).toBe(false);
    expect(isFlagged({ confidence: "0.2" })).toBe(false);
  });
});

describe("plan helpers", () => {
  const plan = {
    protocol: { short_title: "XR-214 Asthma, Phase II!" },
    visits: [{ id: "V1", confidence: 0.3 }],
    procedures: [{ name: "ECG", confidence: 0.5 }, { name: "Vitals", confidence: 0.9 }],
    staffing: [{ role: "PI", fte: 0.1 }, { role: "CRC", fte: null }, { role: "RN", fte: 0.25 }],
    safety: [{ event: "SAE", confidence: 0.6 }],
    pharmacy: { involved: true, items: [{ item: "Store cold", confidence: 0.4 }] },
  };

  it("reads pharmacy items from the nested object and tolerates missing sections", () => {
    expect(itemsFor(plan, "pharmacy")).toHaveLength(1);
    expect(itemsFor(plan, "billing")).toEqual([]);
    expect(itemsFor({ pharmacy: null }, "pharmacy")).toEqual([]);
  });

  it("queues flagged items in plan order and leaves visits out", () => {
    // The visit is low-confidence but visits are not reviewed one by one.
    expect(flaggedKeys(plan)).toEqual(["procedures:0", "safety:0", "pharmacy:0"]);
    expect(openFlags(plan, "visits", {})).toBe(0);
  });

  it("counts only undecided flags as open", () => {
    expect(totalFlags(plan, {})).toBe(3);
    expect(totalFlags(plan, { "safety:0": { status: "accepted" } })).toBe(2);
  });

  it("finds the next open item, wrapping around", () => {
    const queue = ["a", "b", "c"];
    expect(nextOpen(queue, {}, 0)).toBe(0);
    expect(nextOpen(queue, { b: {}, c: {} }, 1)).toBe(0);
    expect(nextOpen(queue, { a: {}, b: {}, c: {} }, 0)).toBe(-1);
  });

  it("adds up stated FTE only", () => {
    expect(fteTotal(plan)).toBeCloseTo(0.35);
  });

  it("builds a file-name slug", () => {
    expect(slug(plan)).toBe("xr-214-asthma-phase-ii");
    expect(slug({ protocol: {} })).toBe("protocol");
  });

  it("applies an edit without changing the original plan object", () => {
    const edited = withItemValues(plan, "safety:0", { event: "Serious adverse event" });
    expect(edited.safety[0].event).toBe("Serious adverse event");
    expect(plan.safety[0].event).toBe("SAE"); // untouched
    expect(edited.procedures).toBe(plan.procedures); // unchanged parts are shared, not copied
    expect(withItemValues(plan, "pharmacy:0", { item: "x" }).pharmacy.items[0].item).toBe("x");
  });

  it("re-applies a reviewer's saved edits to a plan loaded from the server", () => {
    const reviews = {
      "safety:0": { status: "edited", values: { event: "Edited event" } },
      "procedures:0": { status: "accepted" },
      "billing:7": { status: "edited", values: { item: "ignored: no such item" } },
    };
    const out = applyReviews(plan, reviews);
    expect(out.safety[0].event).toBe("Edited event");
    expect(out.procedures[0].name).toBe("ECG");
  });

  it("the bundled sample plan has flagged items to review", () => {
    expect(flaggedKeys(SAMPLE_PLAN).length).toBeGreaterThan(0);
  });
});
