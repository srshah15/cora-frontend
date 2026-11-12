// Role picker (issue #29): a role changes the ORDER of sections and which
// numbers the summary shows. It never changes the plan data.

import { SECTIONS } from "./plan.js";

export const ROLES = [
  { key: "all", label: "All sections", sections: [] },
  { key: "coordinator", label: "Research coordinator", sections: ["visits", "procedures"] },
  { key: "manager", label: "Project manager", sections: ["staffing", "safety"] },
  { key: "operations", label: "Research operations leader", sections: ["technology", "pharmacy", "equipment"] },
];

const STORAGE_KEY = "cora.role";

export const getRole = (key) => ROLES.find((r) => r.key === key) || ROLES[0];

// The role's sections first, then every other section in the standard order.
export function orderedSections(roleKey) {
  const first = getRole(roleKey).sections;
  const byKey = Object.fromEntries(SECTIONS.map((s) => [s.key, s]));
  return [...first.map((k) => byKey[k]), ...SECTIONS.filter((s) => !first.includes(s.key))];
}

export const isPrioritized = (roleKey, sectionKey) => {
  const first = getRole(roleKey).sections;
  return first.length === 0 || first.includes(sectionKey); // "All sections": everything open
};

// localStorage can throw (private mode, blocked storage), so every access is guarded.
export function loadRole() {
  try {
    return getRole(localStorage.getItem(STORAGE_KEY)).key;
  } catch {
    return "all";
  }
}

export function saveRole(key) {
  try {
    localStorage.setItem(STORAGE_KEY, key);
  } catch {
    /* the choice just won't be remembered */
  }
}
