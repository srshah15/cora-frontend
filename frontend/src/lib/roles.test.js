import { describe, expect, it } from "vitest";

import { SAMPLE_PLAN } from "../data/samplePlan.js";
import { SECTIONS } from "./plan.js";
import { isPrioritized, loadRole, orderedSections, ROLES, saveRole } from "./roles.js";

const keys = (role) => orderedSections(role).map((s) => s.key);

describe("role picker ordering", () => {
  it("keeps the standard order for 'All sections'", () => {
    expect(keys("all")).toEqual(SECTIONS.map((s) => s.key));
  });

  it("puts each role's sections first, matching the user stories", () => {
    expect(keys("coordinator").slice(0, 2)).toEqual(["visits", "procedures"]);
    expect(keys("manager").slice(0, 2)).toEqual(["staffing", "safety"]);
    expect(keys("operations").slice(0, 3)).toEqual(["technology", "pharmacy", "equipment"]);
  });

  it("never drops a section: every role still has all eight", () => {
    for (const role of ROLES) {
      expect([...keys(role.key)].sort()).toEqual(SECTIONS.map((s) => s.key).sort());
    }
  });

  it("changes presentation order only, not the plan data", () => {
    const before = JSON.stringify(SAMPLE_PLAN);
    orderedSections("manager");
    orderedSections("operations");
    expect(JSON.stringify(SAMPLE_PLAN)).toBe(before);
  });

  it("opens the role's sections and collapses the others", () => {
    expect(isPrioritized("manager", "staffing")).toBe(true);
    expect(isPrioritized("manager", "visits")).toBe(false);
    expect(isPrioritized("all", "visits")).toBe(true);
  });

  it("remembers the choice in localStorage and ignores unknown values", () => {
    expect(loadRole()).toBe("all");
    saveRole("operations");
    expect(localStorage.getItem("cora.role")).toBe("operations");
    expect(loadRole()).toBe("operations");
    localStorage.setItem("cora.role", "astronaut");
    expect(loadRole()).toBe("all");
  });
});
