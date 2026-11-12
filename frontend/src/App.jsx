import { useCallback, useEffect, useReducer, useRef, useState } from "react";

import { deleteReview, exportDocx, saveReview, uploadProtocol } from "./api.js";
import ProcessingView from "./components/ProcessingView.jsx";
import ResultsView from "./components/ResultsView.jsx";
import ReviewView from "./components/ReviewView.jsx";
import UploadView, { validateFile } from "./components/UploadView.jsx";
import { apiBase, timing } from "./config.js";
import { SAMPLE_PLAN } from "./data/samplePlan.js";
import { FIELDS, flaggedKeys, keyParts, same, slug } from "./lib/plan.js";
import { getReviewerName, setReviewerName } from "./lib/reviewer.js";
import { loadRole, orderedSections, saveRole } from "./lib/roles.js";
import { initialState, reducer } from "./state.js";

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export default function App() {
  const [state, dispatch] = useReducer(reducer, initialState);
  // Lazy initial state: the function runs once, on first render, to read localStorage.
  const [role, setRole] = useState(loadRole);
  const [reviewer, setReviewer] = useState(getReviewerName);
  const [toast, setToast] = useState(null);
  const [exporting, setExporting] = useState(false);
  const [pdfUrl, setPdfUrl] = useState(null); // object URL of the uploaded PDF, for the source pane

  // Refs hold values that must survive re-renders but shouldn't cause one.
  const pending = useRef(null); // the plan waiting for the processing animation to finish
  const requestId = useRef(0); // lets us ignore an answer to a request the user abandoned
  const reviewerInput = useRef(null);

  const { plan, view } = state;

  useEffect(() => {
    if (!toast) return undefined;
    const t = setTimeout(() => setToast(null), timing.toast);
    return () => clearTimeout(t);
  }, [toast]);

  // Keeps the uploaded PDF around (in this tab's memory only) so reviewers
  // can check items against it. Old object URLs are released.
  const setPdf = useCallback((file) => {
    setPdfUrl((old) => {
      if (old) URL.revokeObjectURL(old);
      return file ? URL.createObjectURL(file) : null;
    });
  }, []);

  useEffect(() => {
    window.scrollTo?.(0, 0);
  }, [view]);

  // ---------- upload ----------
  async function handleFile(file) {
    const problem = validateFile(file);
    if (problem) {
      dispatch({ type: "UPLOAD_FAILED", error: { kind: "validation", message: problem } });
      return;
    }
    const id = ++requestId.current;
    dispatch({ type: "PROCESSING_STARTED", filename: file.name });
    try {
      const result = await uploadProtocol(file);
      if (id !== requestId.current) return; // the user started over meanwhile
      pending.current = { plan: result, file };
      dispatch({ type: "PROCESSING_FINISHING", perStep: timing.finishStep });
    } catch (err) {
      if (id !== requestId.current) return;
      dispatch({ type: "UPLOAD_FAILED", error: { kind: err.kind || "server", message: err.message } });
    }
  }

  function runSample() {
    requestId.current++;
    pending.current = { plan: structuredClone(SAMPLE_PLAN), file: null };
    dispatch({ type: "PROCESSING_STARTED", filename: "sample-protocol-xr214.pdf" });
    dispatch({ type: "PROCESSING_FINISHING", perStep: timing.sampleStep });
  }

  function finishProcessing() {
    const loaded = pending.current;
    pending.current = null;
    if (!loaded) return;
    setPdf(loaded.file);
    dispatch({ type: "PLAN_LOADED", plan: loaded.plan, hasPdf: Boolean(loaded.file) });
  }

  function reset() {
    requestId.current++;
    pending.current = null;
    setPdf(null);
    dispatch({ type: "RESET" });
  }

  // ---------- review ----------
  function openReview(key) {
    if (!flaggedKeys(plan).length) return setToast("Nothing is flagged for review.");
    dispatch({ type: "REVIEW_OPENED", key });
  }

  function changeReviewer(name) {
    setReviewer(name);
    setReviewerName(name);
  }

  function decide(k, status, values, comment) {
    const name = reviewer.trim();
    if (!name) {
      reviewerInput.current?.focus();
      return setToast("Add your name first so the plan records who reviewed it.");
    }
    const { sec, item } = keyParts(plan, k);
    const fields = FIELDS[sec];
    const original = Object.fromEntries(fields.map((fd) => [fd.f, item[fd.f]]));
    // Accepting after changing a field is recorded as an edit.
    const edited = status === "accepted" && fields.some((fd) => !same(values[fd.f], item[fd.f]));
    const decision = {
      status: edited ? "edited" : status,
      comment,
      reviewer: name,
      at: new Date().toISOString(),
      original,
      ...(edited ? { values } : {}),
    };
    dispatch({ type: "DECIDED", decision });

    // Save in the background when this plan is stored on the server. The
    // decision shows immediately; if saving fails it stays on screen, marked.
    if (plan.plan_id) {
      saveReview(plan.plan_id, k, decision)
        .then(() => dispatch({ type: "SAVE_SUCCEEDED", key: k }))
        .catch(() => {
          dispatch({ type: "SAVE_FAILED", key: k });
          setToast("Couldn't save that decision to the server. It's kept on this screen.");
        });
    }
  }

  function undo(k) {
    dispatch({ type: "UNDONE" });
    if (plan.plan_id) {
      deleteReview(plan.plan_id, k).catch(() => setToast("Couldn't remove the saved decision from the server."));
    }
  }

  // ---------- export ----------
  async function exportPdf() {
    try {
      // Loaded on first use: jsPDF is most of the app's download size, and
      // many visits never export a PDF.
      const { buildPlanPdf } = await import("./lib/pdfExport.js");
      buildPlanPdf(plan, { reviews: state.reviews, reviewer: reviewer.trim(), sections: orderedSections(role) })
        .save(`${slug(plan)}-operational-plan.pdf`);
    } catch (err) {
      console.error(err);
      setToast("Couldn't generate the PDF.");
    }
  }

  async function exportWord() {
    setExporting(true);
    try {
      const { blob, filename } = await exportDocx({
        plan,
        reviews: state.reviews,
        reviewer: reviewer.trim(),
        sectionOrder: orderedSections(role).map((s) => s.key),
      });
      downloadBlob(blob, filename);
    } catch (err) {
      setToast(
        err.kind === "unreachable"
          ? `Couldn't reach the backend at ${apiBase()} to build the Word file.`
          : `Couldn't build the Word file. ${err.message}`
      );
    } finally {
      setExporting(false);
    }
  }

  function changeRole(key) {
    setRole(key);
    saveRole(key);
  }

  const onScrolled = useCallback(() => dispatch({ type: "SCROLLED" }), []);

  return (
    <>
      <header className="topbar">
        <div className="brand">
          <svg className="brand-mark" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M7 3h7l5 5v13H7z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
            <path d="M14 3v5h5M10 13h6M10 17h4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
          </svg>
          <span>CORA</span>
        </div>
        <div className="topbar-right">
          {plan && (
            <span id="modePill" className={`pill ${plan.is_sample ? "pill-muted" : "pill-warn"}`}>
              {plan.is_sample ? "Sample data" : "Draft, needs review"}
            </span>
          )}
          {view !== "upload" && (
            <button id="newBtn" className="btn btn-ghost" onClick={reset}>New protocol</button>
          )}
        </div>
      </header>

      <main>
        {view === "upload" && (
          <UploadView error={state.uploadError} apiBase={apiBase()} onFile={handleFile} onSample={runSample} />
        )}
        {view === "processing" && (
          <ProcessingView
            filename={state.processing.filename}
            finishing={state.processing.finishing}
            perStep={state.processing.perStep}
            onFinished={finishProcessing}
          />
        )}
        {view === "results" && (
          <ResultsView
            state={state}
            role={role}
            exporting={exporting}
            onRole={changeRole}
            onFlaggedOnly={(value) => dispatch({ type: "FLAGGED_ONLY", value })}
            onReview={openReview}
            onPdf={exportPdf}
            onDocx={exportWord}
            onScrolled={onScrolled}
          />
        )}
        {view === "review" && (
          <ReviewView
            state={state}
            pdfUrl={pdfUrl}
            reviewerName={reviewer}
            onReviewerName={changeReviewer}
            reviewerInput={reviewerInput}
            onDecide={decide}
            onUndo={undo}
            onMove={(index) => dispatch({ type: "REVIEW_MOVED", index })}
            onBack={() => dispatch({ type: "BACK_TO_PLAN" })}
            onPdf={exportPdf}
          />
        )}
      </main>

      {toast && <div id="toast" className="toast" role="status">{toast}</div>}

      <datalist id="designations">
        <option value="Sponsor" />
        <option value="Standard of care" />
        <option value="Not billable" />
      </datalist>
    </>
  );
}
