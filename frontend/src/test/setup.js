// Runs before every test file.
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";

import { timing } from "../config.js";

// No waiting in tests: the processing animation and toasts run instantly.
Object.assign(timing, { step: 5, finishStep: 0, sampleStep: 0, finishPause: 0, toast: 50 });

// jsdom doesn't implement these browser features.
if (!URL.createObjectURL) URL.createObjectURL = () => "blob:mock";
if (!URL.revokeObjectURL) URL.revokeObjectURL = () => {};
window.scrollTo = () => {};
Element.prototype.scrollIntoView = () => {};

beforeEach(() => {
  localStorage.clear();
  // Any test that forgets to mock fetch fails loudly instead of using the network.
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.reject(new Error("fetch was called without a mock")))
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
