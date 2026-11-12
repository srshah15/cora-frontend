# CORA manual test plan (issue #33)

A blank template for a hands-on test pass of the deployed or local build.

**Rules**
- Fill in the run details before you start.
- Write down what actually happened in **Actual result**, then mark **Pass/Fail**.
- A test you did not run stays blank or is marked `not run`. Never fill in a result you didn't observe.
- Copy this file for each test pass (for example `manual-test-2026-11-20.md`) and keep the blank template unchanged.

## Run details

| Field | Value |
| --- | --- |
| Tester | |
| Date | |
| OS and version | |
| Browser and version | |
| Python version | |
| Node version | |
| Commit (SHA) | |
| Frontend URL | |
| Backend URL | |
| `CORA_EXTRACTOR` (keyword / claude) | |
| `DATABASE_URL` set? (yes / no) | |
| Tesseract installed? (yes / no) | |

## Test cases

| ID | Area | Steps / input | Expected result | Actual result | Pass/Fail |
| --- | --- | --- | --- | --- | --- |
| U-01 | Upload | Drop a `.docx` or `.png` file on the upload area | "That doesn't look like a PDF…" message; no request is sent | | |
| U-02 | Upload | Choose a PDF larger than 50 MB | "That file is over 50 MB…" message before anything uploads | | |
| U-03 | Upload | Upload an empty file renamed to `.pdf` | Clear error message, no crash, upload area still usable | | |
| U-04 | Upload | Use click-to-browse, drag and drop, and Enter/Space on the drop area | All three open or accept a file; the drop area highlights while dragging | | |
| U-05 | Upload | Look at the upload screen | "Public protocols only" notice is shown | | |
| U-06 | Upload | Stop the backend, then upload a PDF | "Couldn't reach the backend at …" message with "View sample output instead" | | |
| P-01 | Processing | Upload a normal text-based public protocol | Four steps (Ingestion, Extraction, Structuring, Review check) advance with the file name shown, then the results appear | | |
| P-02 | Processing | Upload a protocol with more than 150 pages | Message saying how many pages it has and that CORA handles up to 150 | | |
| P-03 | Processing | With `CORA_REQUEST_TIMEOUT_SECONDS` set very low (for example 1), upload a long protocol | A timeout message appears; the screen does not stay on processing | | |
| P-04 | Processing | With Tesseract installed, upload `backend/tests/fixtures/scanned_protocol.pdf` | A plan comes back with text from the scanned page | | |
| P-05 | Processing | Without Tesseract, upload the scanned PDF | "This PDF looks scanned (it has little or no selectable text), and OCR isn't installed on this server…" message | | |
| E-01 | Extraction | `CORA_EXTRACTOR=keyword`: upload a protocol | Results show the "Early draft" note | | |
| E-02 | Extraction | `CORA_EXTRACTOR=claude` with a valid key: upload a protocol | Visits, procedures and staffing appear with page numbers; low-confidence items are flagged | | |
| E-03 | Extraction | `CORA_EXTRACTOR=claude` with an invalid key: upload a protocol | A keyword plan appears with a warning banner naming the API key problem | | |
| E-04 | Extraction | `CORA_EXTRACTOR=claude` with no key: start the backend | The server refuses to start and names `ANTHROPIC_API_KEY` and `backend/.env` | | |
| R-01 | Results | Open a plan | Summary, stats, section nav with flag counts, and all eight sections render; empty sections show their empty message | | |
| R-02 | Results | Turn on "Only show flagged items" | Only flagged rows remain; sections with none say "No open flags here." | | |
| R-03 | Results | Pick each role (coordinator, project manager, operations leader) | That role's sections move to the top and open; others stay available, collapsed | | |
| R-04 | Results | Pick a role, then reload the page | The same role is still selected | | |
| V-01 | Review | Click "Review N flagged" | Queue opens at the first open item with "X of Y reviewed" and the source PDF at the item's page | | |
| V-02 | Review | Accept an item without entering a reviewer name | The name field is focused and a message asks for a name | | |
| V-03 | Review | Edit a field, then accept | Button reads "Accept with edits"; the edit is applied and "Was: …" shows the original | | |
| V-04 | Review | Reject an item, then press "Undo decision" | Fields unlock and the original values return | | |
| V-05 | Review | Use keys A, R, ← and → (also while typing in a field) | Shortcuts work outside fields and are ignored while typing | | |
| V-06 | Review | Review every flagged item | "All flagged items reviewed" screen with counts | | |
| X-01 | Export | Click "Download PDF" | PDF downloads with all tables, review highlights and sign-off block, in the chosen role's section order | | |
| X-02 | Export | Click "Download Word" | `.docx` downloads with review status, in the chosen role's section order | | |
| S-01 | Saving | `DATABASE_URL` set: upload the same PDF twice | The second upload returns at once with the note "This protocol was uploaded before, so CORA opened the saved plan…" and earlier decisions loaded | | |
| S-02 | Saving | `DATABASE_URL` set: make decisions as reviewer A, then open the same plan in another browser (reviewer B) | Reviewer B does not see A's decisions; A's decisions are still there when A reloads | | |
| S-03 | Saving | `DATABASE_URL` set: stop the database, then make a decision | The decision stays on screen, a "Couldn't save that decision…" message appears, and the row shows "Not saved to the server…" | | |
| O-01 | Other | Click "Try a sample protocol" | Fictional sample plan loads after a short simulated run, labeled "Sample data" | | |
| O-02 | Other | Switch the OS between light and dark mode | The app follows the system theme | | |
| O-03 | Other | Print the results page | Print layout is readable, with no buttons or navigation | | |
| O-04 | Other | Click "New protocol" | Returns to upload with the plan, reviews and errors cleared | | |

## Notes

Record anything unexpected here (with test ID, screenshot path and steps to reproduce).
