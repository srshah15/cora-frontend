// Fictional sample output. Mirrors the JSON shape the backend should return
// from POST /api/protocols (see README.md).
window.SAMPLE_PLAN = {
  id: "sample",
  is_sample: true,
  protocol: {
    title: "A Phase II, Randomized, Double-Blind, Placebo-Controlled Study of XR-214 in Adults with Moderate Persistent Asthma",
    short_title: "XR-214 Asthma Phase II",
    registry_id: "NCT-SAMPLE-0001",
    phase: "Phase II",
    sponsor: "Sample Therapeutics (fictional)",
    therapeutic_area: "Pulmonology",
    design: "Randomized 1:1, double-blind, placebo-controlled, parallel group",
    enrollment: 120,
    duration: "16 weeks per participant (12 wk treatment + 4 wk follow-up)",
    pages: 87,
  },

  visits: [
    { id: "V1", name: "Screening", day: "Day -28 to -1", window: null, type: "Clinic" },
    { id: "V2", name: "Baseline / Randomization", day: "Day 1", window: null, type: "Clinic" },
    { id: "V3", name: "Week 2", day: "Day 15", window: "±3 days", type: "Clinic" },
    { id: "V4", name: "Week 4", day: "Day 29", window: "±3 days", type: "Clinic" },
    { id: "V5", name: "Week 8", day: "Day 57", window: "±5 days", type: "Clinic" },
    { id: "V6", name: "Week 12 / End of Treatment", day: "Day 85", window: "±5 days", type: "Clinic" },
    { id: "V7", name: "Week 16 Follow-up", day: "Day 113", window: "±7 days", type: "Phone" },
    { id: "ET", name: "Early Termination", day: "As needed", window: null, type: "Clinic" },
  ],

  procedures: [
    { name: "Informed consent", category: "Regulatory", visits: ["V1"], source_page: 34, confidence: 0.98 },
    { name: "Eligibility review", category: "Regulatory", visits: ["V1", "V2"], source_page: 22, confidence: 0.95 },
    { name: "Medical history", category: "Clinical", visits: ["V1"], source_page: 41, confidence: 0.97 },
    { name: "Physical exam", category: "Clinical", visits: ["V1", "V2", "V6", "ET"], source_page: 41, confidence: 0.93 },
    { name: "Vital signs", category: "Clinical", visits: ["V1", "V2", "V3", "V4", "V5", "V6", "ET"], source_page: 42, confidence: 0.96 },
    { name: "12-lead ECG", category: "Clinical", visits: ["V1", "V2", "V6", "ET"], source_page: 43, confidence: 0.91 },
    { name: "Spirometry (FEV1)", category: "Clinical", visits: ["V1", "V2", "V3", "V4", "V5", "V6", "ET"], source_page: 44, confidence: 0.94, notes: "Pre- and post-bronchodilator at V1 only" },
    { name: "Hematology & chemistry labs", category: "Lab", visits: ["V1", "V4", "V6", "ET"], source_page: 46, confidence: 0.89 },
    { name: "Serum pregnancy test", category: "Lab", visits: ["V1", "V6"], source_page: 46, confidence: 0.86, notes: "Women of childbearing potential" },
    { name: "Urine pregnancy test", category: "Lab", visits: ["V2", "V4", "V5"], source_page: 46, confidence: 0.62, notes: "Schedule text and SoA table disagree for Week 2" },
    { name: "PK blood sample", category: "Lab", visits: ["V2", "V4", "V6"], source_page: 48, confidence: 0.58, notes: "Timing relative to dose unclear (pre-dose vs 2h post)" },
    { name: "Randomization (IWRS)", category: "Study drug", visits: ["V2"], source_page: 36, confidence: 0.97 },
    { name: "Study drug dispensing", category: "Study drug", visits: ["V2", "V4", "V5"], source_page: 37, confidence: 0.9 },
    { name: "Drug accountability", category: "Study drug", visits: ["V3", "V4", "V5", "V6", "ET"], source_page: 38, confidence: 0.88 },
    { name: "Asthma Control Questionnaire (ePRO)", category: "PRO", visits: ["V2", "V3", "V4", "V5", "V6"], source_page: 50, confidence: 0.92 },
    { name: "Adverse event assessment", category: "Safety", visits: ["V2", "V3", "V4", "V5", "V6", "V7", "ET"], source_page: 55, confidence: 0.97 },
    { name: "Concomitant medication review", category: "Safety", visits: ["V1", "V2", "V3", "V4", "V5", "V6", "V7", "ET"], source_page: 40, confidence: 0.95 },
  ],

  staffing: [
    { role: "Principal Investigator", fte: 0.1, responsibilities: "Oversight, eligibility sign-off, AE causality assessment", confidence: 0.85 },
    { role: "Clinical Research Coordinator", fte: 0.6, responsibilities: "Scheduling, consent, visit conduct, EDC entry", confidence: 0.8 },
    { role: "Research Nurse", fte: 0.3, responsibilities: "Vitals, ECG, blood draws, PK sampling", confidence: 0.74 },
    { role: "Respiratory Therapist", fte: 0.15, responsibilities: "Spirometry at 7 visits, protocol-specific calibration", confidence: 0.66 },
    { role: "Research Pharmacist", fte: 0.1, responsibilities: "Blinded drug storage, dispensing, accountability", confidence: 0.82 },
    { role: "Regulatory Coordinator", fte: 0.1, responsibilities: "IRB submissions, amendments, deviation reporting", confidence: 0.78 },
  ],

  safety: [
    { event: "Serious adverse event (SAE)", timeline: "Within 24 hours of awareness", recipient: "Sponsor safety desk", method: "SAE form via EDC + fax backup", source_page: 57, confidence: 0.96 },
    { event: "Pregnancy", timeline: "Within 24 hours of awareness", recipient: "Sponsor safety desk", method: "Pregnancy report form", source_page: 58, confidence: 0.9 },
    { event: "Unanticipated problem", timeline: "Per local IRB policy (typically 7 days)", recipient: "IRB", method: "IRB portal", source_page: 59, confidence: 0.64, notes: "Protocol defers to local IRB; confirm UNC timeline" },
    { event: "Non-serious adverse event", timeline: "Record at each visit; enter in EDC within 5 business days", recipient: "Sponsor (EDC)", method: "EDC", source_page: 56, confidence: 0.88 },
    { event: "Asthma exacerbation requiring systemic steroids", timeline: "Within 72 hours", recipient: "Sponsor medical monitor", method: "Email + EDC", source_page: 60, confidence: 0.79 },
  ],

  billing: [
    { item: "Screening labs (hematology/chemistry)", designation: "Sponsor", visits: ["V1"], confidence: 0.84 },
    { item: "12-lead ECG", designation: "Sponsor", visits: ["V1", "V2", "V6", "ET"], confidence: 0.81 },
    { item: "Spirometry", designation: "Standard of care", visits: ["V1"], confidence: 0.55, notes: "Baseline spirometry may be SOC for asthma management; needs coverage analysis" },
    { item: "Spirometry (on-study)", designation: "Sponsor", visits: ["V2", "V3", "V4", "V5", "V6"], confidence: 0.83 },
    { item: "Physical exam", designation: "Standard of care", visits: ["V1"], confidence: 0.61 },
    { item: "PK sample processing & shipping", designation: "Sponsor", visits: ["V2", "V4", "V6"], confidence: 0.87 },
    { item: "Study drug", designation: "Sponsor", visits: ["V2", "V4", "V5"], confidence: 0.95 },
  ],

  equipment: [
    { item: "Calibrated spirometer (ATS/ERS compliant)", purpose: "FEV1 measurements", confidence: 0.92 },
    { item: "12-lead ECG machine", purpose: "Cardiac safety monitoring", confidence: 0.9 },
    { item: "Refrigerated centrifuge", purpose: "PK sample processing", confidence: 0.77 },
    { item: "-70°C freezer", purpose: "PK sample storage before batch shipping", confidence: 0.72 },
    { item: "Temperature-monitored storage (2–8°C)", purpose: "Study drug storage", confidence: 0.86 },
  ],

  pharmacy: {
    involved: true,
    items: [
      { item: "Blinded investigational product storage at 2–8°C with daily temperature logs", confidence: 0.9 },
      { item: "Dispensing per IWRS kit assignment", confidence: 0.93 },
      { item: "Returned drug accountability and destruction per sponsor instructions", confidence: 0.8 },
      { item: "Unblinding procedure for medical emergencies", confidence: 0.68, notes: "Protocol mentions 24/7 IWRS unblinding but no site-level backup" },
    ],
  },

  technology: [
    { system: "EDC (sponsor-provided)", purpose: "Case report forms", confidence: 0.93 },
    { system: "IWRS / IRT", purpose: "Randomization and drug kit assignment", confidence: 0.95 },
    { system: "ePRO device or app", purpose: "Asthma Control Questionnaire", confidence: 0.81 },
    { system: "Central ECG reading portal", purpose: "ECG upload and over-read", confidence: 0.63, notes: "Mentioned once; unclear if central read is required" },
  ],
};
