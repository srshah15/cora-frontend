import { describe, expect, it, vi } from "vitest";

import { ApiError, deleteReview, exportDocx, saveReview, uploadProtocol } from "./api.js";

const pdf = () => new File(["%PDF-1.7 fake"], "protocol.pdf", { type: "application/pdf" });
const json = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("uploadProtocol", () => {
  it("POSTs the file as multipart field 'file' with the reviewer id header", async () => {
    fetch.mockResolvedValueOnce(json({ id: "x" }));
    const file = pdf();
    await expect(uploadProtocol(file)).resolves.toEqual({ id: "x" });

    const [url, options] = fetch.mock.calls[0];
    expect(url).toBe("http://localhost:8000/api/protocols");
    expect(options.method).toBe("POST");
    expect(options.body).toBeInstanceOf(FormData);
    expect(options.body.get("file")).toBe(file);
    expect([...options.body.keys()]).toEqual(["file"]);
    expect(options.headers["X-Reviewer-Id"]).toMatch(/^[0-9a-f-]{36}$/);
    // No Content-Type header: the browser must set the multipart boundary itself.
    expect(options.headers["Content-Type"]).toBeUndefined();
  });

  it("uses the same reviewer id on every call and URL-encodes the name", async () => {
    localStorage.setItem("cora.reviewer", "José");
    // A Response body can be read only once, so build a new one per call.
    fetch.mockImplementation(() => Promise.resolve(json({})));
    await uploadProtocol(pdf());
    await uploadProtocol(pdf());
    const [a, b] = fetch.mock.calls.map((c) => c[1].headers);
    expect(a["X-Reviewer-Id"]).toBe(b["X-Reviewer-Id"]);
    expect(a["X-Reviewer-Name"]).toBe("Jos%C3%A9");
  });

  it("turns a server error into its 'detail' message", async () => {
    fetch.mockResolvedValueOnce(json({ detail: "This protocol has 200 pages. CORA handles up to 150." }, 413));
    const err = await uploadProtocol(pdf()).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.kind).toBe("server");
    expect(err.status).toBe(413);
    expect(err.message).toContain("200 pages");
  });

  it("limits a very long server message to 200 characters", async () => {
    fetch.mockResolvedValueOnce(json({ detail: "x".repeat(500) }, 422));
    const err = await uploadProtocol(pdf()).catch((e) => e);
    expect(err.message).toHaveLength(200);
  });

  it("falls back to the status code when the error has no body", async () => {
    fetch.mockResolvedValueOnce(new Response("", { status: 500 }));
    const err = await uploadProtocol(pdf()).catch((e) => e);
    expect(err.message).toBe("Server returned 500");
  });

  it("reports an unreachable backend", async () => {
    fetch.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    const err = await uploadProtocol(pdf()).catch((e) => e);
    expect(err.kind).toBe("unreachable");
  });

  it("gives up after the timeout instead of waiting forever", async () => {
    // A backend that never answers: the promise only settles when aborted.
    fetch.mockImplementationOnce(
      (_url, { signal }) =>
        new Promise((_resolve, reject) =>
          signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")))
        )
    );
    const err = await uploadProtocol(pdf(), { timeoutMs: 20 }).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.kind).toBe("timeout");
  });
});

describe("review and export calls", () => {
  it("saves a decision with PUT and removes one with DELETE", async () => {
    fetch.mockImplementation(() => Promise.resolve(json({ status: "accepted" })));
    await saveReview("plan-1", "safety:0", { status: "accepted" });
    await deleteReview("plan-1", "safety:0");

    const [putUrl, put] = fetch.mock.calls[0];
    expect(putUrl).toBe("http://localhost:8000/api/plans/plan-1/reviews/safety%3A0");
    expect(put.method).toBe("PUT");
    expect(JSON.parse(put.body)).toEqual({ status: "accepted" });
    expect(put.headers["X-Reviewer-Id"]).toBeTruthy();
    expect(fetch.mock.calls[1][1].method).toBe("DELETE");
  });

  it("requests the Word export with the plan, reviews and section order", async () => {
    fetch.mockResolvedValueOnce(
      new Response("docx-bytes", { status: 200, headers: { "Content-Disposition": 'attachment; filename="xr-214-operational-plan.docx"' } })
    );
    const out = await exportDocx({ plan: { id: "p" }, reviews: {}, reviewer: "Ana", sectionOrder: ["staffing", "safety"] });

    expect(out.filename).toBe("xr-214-operational-plan.docx");
    const [url, options] = fetch.mock.calls[0];
    expect(url).toBe("http://localhost:8000/api/export/docx");
    expect(JSON.parse(options.body)).toEqual({
      plan: { id: "p" }, reviews: {}, reviewer: "Ana", section_order: ["staffing", "safety"],
    });
  });
});

describe("backend URL", () => {
  it("can be overridden with ?api=", async () => {
    window.history.replaceState({}, "", "/?api=https://cora.example.org/");
    fetch.mockResolvedValueOnce(json({}));
    await uploadProtocol(pdf());
    expect(fetch.mock.calls[0][0]).toBe("https://cora.example.org/api/protocols");
    window.history.replaceState({}, "", "/");
  });
});
