// Whole-app tests: render <App />, act like a user, check what is on screen.
// The backend is never contacted; fetch is a mock (see src/test/setup.js).

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import App from "./App.jsx";
import { validateFile } from "./components/UploadView.jsx";
import { SAMPLE_PLAN } from "./data/samplePlan.js";

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const pdfFile = (name = "protocol.pdf") => new File(["%PDF-1.7"], name, { type: "application/pdf" });

// A small backend-shaped plan with one flagged and one confident item.
const PLAN = {
  id: "NCT01234567",
  is_sample: false,
  extraction: "llm",
  protocol: { title: "A Study of Drug Y", short_title: "Drug Y", registry_id: "NCT01234567", phase: "Phase 2", pages: 42 },
  visits: [
    { id: "V1", name: "Screening", day: "Day -14", window: null, type: "Clinic", confidence: 0.95, source_page: 12 },
    { id: "V2", name: "Baseline", day: "Day 1", window: "±1 day", type: "Clinic", confidence: 0.5, notes: "Window unclear." },
  ],
  procedures: [{ name: "Vital signs", category: "Clinical", visits: ["V1", "V2"], confidence: 0.9, source_page: 14 }],
  staffing: [{ role: "Principal Investigator", fte: null, responsibilities: "Oversight", qualifications: "MD", confidence: 0.9 }],
  safety: [
    { event: "Serious adverse event", timeline: "Within 24 hours", recipient: "Sponsor", method: "EDC", confidence: 0.6, notes: "Timeline stated twice.", source_page: 30 },
    { event: "Pregnancy", timeline: "Within 24 hours", recipient: "Sponsor", method: null, confidence: 0.7 },
  ],
  billing: [],
  equipment: [],
  pharmacy: null,
  technology: [],
};

async function uploadPlan(plan = PLAN, user = userEvent.setup()) {
  fetch.mockImplementation(() => Promise.resolve(json(plan)));
  render(<App />);
  await user.upload(screen.getByLabelText("Protocol PDF"), pdfFile());
  await screen.findByRole("heading", { name: plan.protocol.title });
  return user;
}

const section = (name) => screen.getByRole("heading", { level: 2, name }).closest("section");

describe("PDF validation", () => {
  it("accepts a .pdf by extension or by type", () => {
    expect(validateFile(new File(["x"], "protocol.PDF", { type: "" }))).toBeNull();
    expect(validateFile(new File(["x"], "no-extension", { type: "application/pdf" }))).toBeNull();
  });

  it("rejects other file types with a clear message", () => {
    expect(validateFile(new File(["x"], "notes.docx", { type: "application/msword" }))).toMatch(/doesn't look like a PDF/);
  });

  it("rejects files over 50 MB", () => {
    const big = new File(["x"], "big.pdf", { type: "application/pdf" });
    Object.defineProperty(big, "size", { value: 50 * 1024 * 1024 + 1 });
    expect(validateFile(big)).toMatch(/over 50 MB/);
    const ok = new File(["x"], "ok.pdf", { type: "application/pdf" });
    Object.defineProperty(ok, "size", { value: 50 * 1024 * 1024 });
    expect(validateFile(ok)).toBeNull();
  });

  it("shows the message and sends nothing when a non-PDF is dropped", async () => {
    render(<App />);
    const input = screen.getByLabelText("Protocol PDF");
    // applyAccept: false lets the test hand over a file the picker would hide.
    await userEvent.setup({ applyAccept: false }).upload(input, new File(["x"], "notes.txt", { type: "text/plain" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/doesn't look like a PDF/);
    expect(fetch).not.toHaveBeenCalled();
  });
});

describe("upload screen", () => {
  it("shows the 'Public protocols only' notice", () => {
    render(<App />);
    expect(screen.getByText("Public protocols only.")).toBeInTheDocument();
    expect(screen.getByText(/never keeps the PDF or its text/)).toBeInTheDocument();
  });

  it("hides 'New protocol' until there is something to leave", () => {
    render(<App />);
    expect(screen.queryByRole("button", { name: "New protocol" })).not.toBeInTheDocument();
  });
});

describe("view transitions", () => {
  it("goes upload -> processing -> results, and back with 'New protocol'", async () => {
    let answer;
    fetch.mockImplementation(() => new Promise((resolve) => { answer = resolve; }));
    const user = userEvent.setup();
    render(<App />);

    await user.upload(screen.getByLabelText("Protocol PDF"), pdfFile("my-protocol.pdf"));
    expect(screen.getByRole("heading", { name: "Processing protocol" })).toBeInTheDocument();
    expect(screen.getByText("my-protocol.pdf")).toBeInTheDocument();
    expect(screen.getByText("Ingestion")).toBeInTheDocument();
    expect(screen.getByText("Review check")).toBeInTheDocument();

    answer(json(PLAN));
    expect(await screen.findByRole("heading", { name: "A Study of Drug Y" })).toBeInTheDocument();
    expect(screen.getByText("Draft, needs review")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "New protocol" }));
    expect(screen.getByRole("heading", { name: /Turn a protocol into an operational plan/ })).toBeInTheDocument();
    expect(screen.queryByText("Draft, needs review")).not.toBeInTheDocument();
  });

  it("sample mode loads the fictional plan without calling the backend", async () => {
    render(<App />);
    await userEvent.setup().click(screen.getByRole("button", { name: "Try a sample protocol" }));
    expect(await screen.findByRole("heading", { name: SAMPLE_PLAN.protocol.title })).toBeInTheDocument();
    expect(screen.getByText("Sample data")).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("ignores a late answer after the user started over", async () => {
    let answer;
    fetch.mockImplementation(() => new Promise((resolve) => { answer = resolve; }));
    const user = userEvent.setup();
    render(<App />);
    await user.upload(screen.getByLabelText("Protocol PDF"), pdfFile());
    await user.click(screen.getByRole("button", { name: "New protocol" }));
    answer(json(PLAN));
    await new Promise((r) => setTimeout(r, 30));
    expect(screen.getByRole("heading", { name: /Turn a protocol/ })).toBeInTheDocument();
  });
});

describe("error states", () => {
  async function failWith(mock) {
    fetch.mockImplementation(mock);
    render(<App />);
    await userEvent.setup().upload(screen.getByLabelText("Protocol PDF"), pdfFile());
    return screen.findByRole("alert");
  }

  it("backend unavailable: says so, names the URL, and leaves the processing screen", async () => {
    const alert = await failWith(() => Promise.reject(new TypeError("Failed to fetch")));
    expect(alert).toHaveTextContent("Couldn't reach the backend at http://localhost:8000");
    expect(alert).toHaveTextContent("Is the FastAPI server running?");
    expect(screen.queryByRole("heading", { name: "Processing protocol" })).not.toBeInTheDocument();
    expect(within(alert).getByRole("button", { name: "View sample output instead" })).toBeInTheDocument();
  });

  it("shows the backend's own message for a rejected upload", async () => {
    const alert = await failWith(() =>
      Promise.resolve(json({ detail: "This protocol has 200 pages. CORA handles up to 150." }, 413))
    );
    expect(alert).toHaveTextContent("Processing failed. This protocol has 200 pages. CORA handles up to 150.");
  });

  it("offers the sample from an error, and the error clears", async () => {
    const alert = await failWith(() => Promise.reject(new TypeError("Failed to fetch")));
    await userEvent.setup().click(within(alert).getByRole("button", { name: "View sample output instead" }));
    expect(await screen.findByText("Sample data")).toBeInTheDocument();
  });

  it("a request that never answers ends with a timeout message, not an endless spinner", async () => {
    vi.stubEnv("VITE_UPLOAD_TIMEOUT_MS", "30");
    const alert = await failWith(
      (_url, { signal }) =>
        new Promise((_resolve, reject) =>
          signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")))
        )
    );
    expect(alert).toHaveTextContent("CORA stopped waiting for the server");
    expect(screen.queryByRole("heading", { name: "Processing protocol" })).not.toBeInTheDocument();
    vi.unstubAllEnvs();
  });
});

describe("results", () => {
  it("renders the summary and each section's content", async () => {
    await uploadPlan();
    expect(screen.getByText("NCT01234567 · 42 pages")).toBeInTheDocument();
    expect(screen.getByText("Phase 2")).toBeInTheDocument();

    expect(within(section("Visit schedule")).getByText("Screening")).toBeInTheDocument();
    expect(within(section("Visit schedule")).getByText("Needs checking: Window unclear.")).toBeInTheDocument();
    const procedures = within(section("Procedures"));
    expect(procedures.getByText("Vital signs")).toBeInTheDocument();
    expect(procedures.getAllByText("●")).toHaveLength(2); // required at V1 and V2
    expect(procedures.getByText("p. 14")).toBeInTheDocument();
    const staffing = within(section("Staffing"));
    expect(staffing.getByText("Principal Investigator")).toBeInTheDocument();
    expect(staffing.getByText("MD")).toBeInTheDocument();
    const safety = within(section("Safety reporting"));
    expect(safety.getByText("Serious adverse event")).toBeInTheDocument();
    expect(safety.getByText("Timeline stated twice.")).toBeInTheDocument();
    expect(safety.getByText("60%")).toBeInTheDocument();
  });

  it("shows the right empty state for each empty section", async () => {
    await uploadPlan({ ...PLAN, visits: [], procedures: [], staffing: [], safety: [] });
    expect(within(section("Visit schedule")).getByText("No visits extracted.")).toBeInTheDocument();
    expect(within(section("Procedures")).getByText("No procedures extracted.")).toBeInTheDocument();
    expect(within(section("Pharmacy")).getByText("No pharmacy info extracted.")).toBeInTheDocument();
    for (const name of ["Staffing", "Safety reporting", "Billing", "Equipment", "Technology"]) {
      expect(within(section(name)).getByText("Nothing found in the protocol for this category.")).toBeInTheDocument();
    }
  });

  it("flags only items below 0.7 and counts them", async () => {
    await uploadPlan();
    const safety = within(section("Safety reporting"));
    // 0.6 is flagged and reviewable; exactly 0.7 is not.
    expect(safety.getAllByRole("button", { name: "Review" })).toHaveLength(1);
    expect(safety.getByText("1 to review")).toBeInTheDocument();
    expect(within(section("Staffing")).getByText("Looks good")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Review 1 flagged" })).toBeInTheDocument();
    expect(screen.getByText("item needs review")).toBeInTheDocument();
  });

  it("'Only show flagged items' hides the rest and explains empty results", async () => {
    const user = await uploadPlan();
    await user.click(screen.getByLabelText("Only show flagged items"));
    const safety = within(section("Safety reporting"));
    expect(safety.getByText("Serious adverse event")).toBeInTheDocument();
    expect(safety.queryByText("Pregnancy")).not.toBeInTheDocument();
    expect(within(section("Staffing")).getByText("No open flags here.")).toBeInTheDocument();
  });

  it("shows the fallback warning when the LLM could not be used", async () => {
    await uploadPlan({
      ...PLAN,
      extraction: "keyword",
      extraction_info: { method: "keyword", fallback: true, reason: "timeout", warning: "The AI service took too long to respond, so this plan was built by keyword search only." },
    });
    expect(screen.getByText("Limited extraction.")).toBeInTheDocument();
    expect(screen.getByText(/took too long to respond/)).toBeInTheDocument();
    expect(screen.getByText(/Early draft: CORA found these items by searching/)).toBeInTheDocument();
  });

  it("shows a section-level warning from the backend", async () => {
    await uploadPlan({ ...PLAN, section_reviews: { staffing: { needs_review: true, reason: "1 item(s) were left out." } } });
    expect(within(section("Staffing")).getByText("Check this section: 1 item(s) were left out.")).toBeInTheDocument();
    // The badge agrees with the warning instead of saying "Looks good".
    expect(within(section("Staffing")).getByText("Needs check")).toBeInTheDocument();
    expect(within(section("Staffing")).queryByText("Looks good")).not.toBeInTheDocument();
  });

  it("says when a saved plan was reused", async () => {
    await uploadPlan({ ...PLAN, plan_id: "p-1", reused: true, version: 2 });
    expect(screen.getByText(/opened the saved plan instead of extracting it again/)).toBeInTheDocument();
    expect(screen.getByText("NCT01234567 · 42 pages · version 2")).toBeInTheDocument();
  });
});

describe("role picker", () => {
  const order = () => screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent.replace(/^[▾▸]/, "").trim());

  it("moves the role's sections to the top and keeps the others available", async () => {
    const user = await uploadPlan();
    expect(order().slice(0, 2)).toEqual(["Visit schedule", "Procedures"]);

    await user.selectOptions(screen.getByLabelText("View as"), "Project manager");
    expect(order().slice(0, 2)).toEqual(["Staffing", "Safety reporting"]);
    expect(order()).toHaveLength(8);
    expect(screen.getByText("staff roles")).toBeInTheDocument(); // summary follows the role

    // Other sections are collapsed, not removed, and can be opened.
    const visitsToggle = screen.getByRole("button", { name: /Visit schedule/ });
    expect(visitsToggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("button", { name: /Staffing/ })).toHaveAttribute("aria-expanded", "true");
    await user.click(visitsToggle);
    expect(visitsToggle).toHaveAttribute("aria-expanded", "true");
  });

  it("remembers the choice across a reload", async () => {
    const user = await uploadPlan();
    await user.selectOptions(screen.getByLabelText("View as"), "Research operations leader");
    expect(localStorage.getItem("cora.role")).toBe("operations");

    // A reload is a brand-new app instance reading localStorage again.
    document.body.innerHTML = "";
    await uploadPlan();
    expect(screen.getAllByLabelText("View as").at(-1)).toHaveValue("operations");
  });
});

describe("review flow", () => {
  async function openReview(plan = PLAN) {
    const user = await uploadPlan(plan);
    await user.click(screen.getByRole("button", { name: "Review 1 flagged" }));
    return user;
  }

  it("opens the flagged item with its reason and a source-page pane", async () => {
    await openReview();
    expect(screen.getByRole("heading", { name: "Serious adverse event" })).toBeInTheDocument();
    expect(screen.getByText("0 of 1 reviewed")).toBeInTheDocument();
    expect(screen.getByText("Timeline stated twice.")).toBeInTheDocument();
    expect(screen.getByTitle("Source protocol PDF")).toHaveAttribute("src", expect.stringContaining("#page=30"));
  });

  it("asks for a reviewer name before recording a decision", async () => {
    const user = await openReview();
    await user.click(screen.getByRole("button", { name: "Accept" }));
    expect(screen.getByRole("status")).toHaveTextContent("Add your name first");
    expect(screen.getByText("0 of 1 reviewed")).toBeInTheDocument();
    expect(screen.getByLabelText("Reviewer")).toHaveFocus();
  });

  it("accepts an item, remembers the reviewer, and shows the done screen", async () => {
    const user = await openReview();
    await user.type(screen.getByLabelText("Reviewer"), "Ana");
    await user.click(screen.getByRole("button", { name: "Accept" }));

    expect(screen.getByText("1 of 1 reviewed")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "All flagged items reviewed" })).toBeInTheDocument();
    expect(screen.getByText("1 accepted · 0 edited · 0 rejected")).toBeInTheDocument();
    expect(localStorage.getItem("cora.reviewer")).toBe("Ana");

    await user.click(screen.getByRole("button", { name: "Back to plan" }));
    expect(within(section("Safety reporting")).getByRole("button", { name: "Accepted" })).toBeInTheDocument();
    expect(within(section("Safety reporting")).getByText("Looks good")).toBeInTheDocument();
  });

  it("records a changed field as an edit, shows 'Was:', and undo restores it", async () => {
    const user = await openReview();
    await user.type(screen.getByLabelText("Reviewer"), "Ana");
    const timeline = screen.getByLabelText("Timeline");
    await user.clear(timeline);
    await user.type(timeline, "Within 48 hours");
    await user.type(screen.getByLabelText("Comment"), "Per section 9.2");
    await user.click(screen.getByRole("button", { name: "Accept with edits" }));
    expect(screen.getByText("0 accepted · 1 edited · 0 rejected")).toBeInTheDocument();

    // Open the decided item from the queue list.
    await user.click(within(screen.getByRole("list")).getByRole("button", { name: /Serious adverse event/ }));
    expect(screen.getByText("Was: Within 24 hours")).toBeInTheDocument();
    expect(screen.getByLabelText("Timeline")).toHaveValue("Within 48 hours");
    expect(screen.getByLabelText("Timeline")).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Undo decision" }));
    expect(screen.getByLabelText("Timeline")).toHaveValue("Within 24 hours");
    expect(screen.getByText("0 of 1 reviewed")).toBeInTheDocument();
  });

  it("rejects an item and greys it out in the plan", async () => {
    const user = await openReview();
    await user.type(screen.getByLabelText("Reviewer"), "Ana");
    await user.click(screen.getByRole("button", { name: "Reject" }));
    await user.click(screen.getByRole("button", { name: "Back to plan" }));
    const row = within(section("Safety reporting")).getByText("Serious adverse event").closest("tr");
    expect(row).toHaveClass("row-rejected");
  });

  it("supports the A keyboard shortcut, but not while typing", async () => {
    const user = await openReview();
    await user.type(screen.getByLabelText("Reviewer"), "Ana a"); // typing "a" must not accept
    expect(screen.getByText("0 of 1 reviewed")).toBeInTheDocument();
    await user.click(screen.getByRole("heading", { name: "Serious adverse event" })); // leave the input
    await user.keyboard("a");
    expect(screen.getByText("1 of 1 reviewed")).toBeInTheDocument();
  });

  it("the sample has no PDF, and the source pane says so", async () => {
    render(<App />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Try a sample protocol" }));
    await user.click(await screen.findByRole("button", { name: /Review \d+ flagged/ }));
    expect(screen.getByText(/fictional protocol, so there's no PDF to show/)).toBeInTheDocument();
  });

  it("saves decisions to the server for a stored plan, and removes them on undo", async () => {
    const user = await openReview({ ...PLAN, plan_id: "plan-123" });
    fetch.mockClear();
    fetch.mockImplementation(() => Promise.resolve(json({ status: "accepted" })));
    await user.type(screen.getByLabelText("Reviewer"), "Ana");
    await user.click(screen.getByRole("button", { name: "Accept" }));

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    const [url, options] = fetch.mock.calls[0];
    expect(url).toBe("http://localhost:8000/api/plans/plan-123/reviews/safety%3A0");
    expect(options.method).toBe("PUT");
    expect(JSON.parse(options.body)).toMatchObject({ status: "accepted", reviewer: "Ana" });

    await user.click(within(screen.getByRole("list")).getByRole("button", { name: /Serious adverse event/ }));
    await user.click(screen.getByRole("button", { name: "Undo decision" }));
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    expect(fetch.mock.calls[1][1].method).toBe("DELETE");
  });

  it("keeps a decision on screen and says so when saving fails", async () => {
    const user = await openReview({ ...PLAN, plan_id: "plan-123" });
    fetch.mockImplementation(() => Promise.reject(new TypeError("Failed to fetch")));
    await user.type(screen.getByLabelText("Reviewer"), "Ana");
    await user.click(screen.getByRole("button", { name: "Accept" }));

    expect(await screen.findByText(/Couldn't save that decision to the server/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Back to plan" }));
    expect(within(section("Safety reporting")).getByText(/Not saved to the server/)).toBeInTheDocument();
    expect(within(section("Safety reporting")).getByRole("button", { name: "Accepted" })).toBeInTheDocument();
  });

  it("does not call the server for the sample or an unsaved plan", async () => {
    const user = await openReview(); // PLAN has no plan_id
    fetch.mockClear();
    await user.type(screen.getByLabelText("Reviewer"), "Ana");
    await user.click(screen.getByRole("button", { name: "Accept" }));
    expect(fetch).not.toHaveBeenCalled();
  });

  it("loads the reviewer's earlier decisions with a reused plan", async () => {
    await uploadPlan({
      ...PLAN, plan_id: "plan-123", reused: true,
      reviews: { "safety:0": { status: "edited", reviewer: "Ana", comment: "fixed", values: { timeline: "Within 48 hours" }, original: { timeline: "Within 24 hours" } } },
    });
    const safety = within(section("Safety reporting"));
    expect(safety.getByRole("button", { name: "Edited" })).toBeInTheDocument();
    expect(safety.getByText("Within 48 hours")).toBeInTheDocument();
    expect(safety.getByText("Ana: fixed")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Review \d+ flagged/ })).not.toBeInTheDocument();
  });
});

describe("exports", () => {
  it("Download Word posts the plan with the role's section order and saves the file", async () => {
    const user = await uploadPlan();
    await user.selectOptions(screen.getByLabelText("View as"), "Project manager");
    fetch.mockClear();
    fetch.mockImplementation(() =>
      Promise.resolve(new Response("docx", { status: 200, headers: { "Content-Disposition": 'attachment; filename="drug-y-operational-plan.docx"' } }))
    );
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    await user.click(screen.getByRole("button", { name: "Download Word" }));
    await waitFor(() => expect(click).toHaveBeenCalled());
    const body = JSON.parse(fetch.mock.calls[0][1].body);
    expect(fetch.mock.calls[0][0]).toBe("http://localhost:8000/api/export/docx");
    expect(body.plan.protocol.title).toBe("A Study of Drug Y");
    expect(body.section_order.slice(0, 2)).toEqual(["staffing", "safety"]);
    expect(body.section_order).toHaveLength(8);
  });

  it("explains a failed Word export", async () => {
    const user = await uploadPlan();
    fetch.mockImplementation(() => Promise.reject(new TypeError("Failed to fetch")));
    await user.click(screen.getByRole("button", { name: "Download Word" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Couldn't reach the backend");
  });
});
