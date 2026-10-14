// This file contains a mock implementation of the OperationalPlan interface for testing purposes.

import type { OperationalPlan } from "./protocol";

export const mockProtocol: OperationalPlan = {
    protocol: {
        protocol_num: "20170625",
        title: "A Double- blind, Randomized, Placebo- controlled, Multicenter Study to Evaluate the Impact of Evolocumab on Major Cardiovascular Events in Patients at High Cardiovascular Risk Without Prior Myocardial Infarction or Stroke",
        short_title: "Effect of Evolocumab in Patients at High Cardiovascular Risk Without Prior Myocardial Infarction or Stroke",
        product: "Evolocumab",
        sponsor: "Amgen Inc.",
        date: "12 June 2023",
    },
    visits: [
        {
            name: "Screening",
            timing: "Up to 21 days before day 1 of treatment",
            procedures: [
                "Informed consent",
                "Inclusion and exclusion criteria",
                "Demographics",
                "Physical examination",
                "Physical measurements",
                "Medical history",
                "Substance use history",
                "Vital signs",
                "Serious adverse events",
                "Concomitant medications",
                "Serum or urine pregnancy test",
                "Chemistry",
                "Fasting or non-fasting lipid panel",
                "Placebo injection",
            ]
        },
        {
            name: "Day 1",
            timing: "Day 1 of treatment",
            procedures: [
                "Concomitant therapies",
                "Vital status",
                "Serum or urine pregnancy test",
                "Lipid panel, non-fasting",
                "Biomarker sample (optional)",
                "Pharmacogenetic sample (optional)",
                "Investigational product administration",
                "Investigational product dispensation",
            ]
        },
        {
            name: "Treatment Visit 1",
            timing: "Year 1 (week 48)",
            procedures: [
                "Treatment compliance (Q16W)",
                "Adverse events (continually)",
                "Potential endpoint data collection (continually)",
                "Concomitant therapies (Q16W)",
                "Vital status (Q16W)",
                "Lipid panel, non-fasting",
                "Biomarker sample (optional)",
                "Investigational product administration (Q2W)",
                "Observed in-person investigational product administration review",
                "Investigational product dispensation (Q16W)",
            ]
        },
        {
            name: "Treatment Visit 2",
            timing: "Year 2 (week 96)",
            procedures: [
                "Treatment compliance (Q16W)",
                "Adverse events (continually)",
                "Potential endpoint data collection (continually)",
                "Concomitant therapies (Q16W)",
                "Vital status (Q16W)",
                "Lipid panel, non-fasting",
                "Biomarker sample (optional)",
                "Investigational product administration (Q2W)",
                "Observed in-person investigational product administration review",
                "Investigational product dispensation (Q16W)",]
        },
        {
            name: "Treatment Visit 3",
            timing: "Year 3 (week 144+)",
            procedures: [
                "Treatment compliance (Q16W)",
                "Adverse events (continually)",
                "Potential endpoint data collection (continually)",
                "Concomitant therapies (Q16W)",
                "Vital status (Q16W)",
                "Biomarker sample (optional)",
                "Investigational product administration (Q2W)",
                "Observed in-person investigational product administration review",
                "Investigational product dispensation (Q16W)",
            ]
        },
        {
            name: "End of Study",
            timing: "After the treatment period has concluded",
            procedures: [
                "Vital signs",
                "Treatment compliance",
                "Adverse events",
                "Potential endpoint data collection",
                "Concomitant therapies",
                "Vital status",
                "Serum or urine pregnancy test",
                "Lipid panel, non-fasting",
                "Biomarker sample (optional)",
            ]
        },
        {
            name: "Follow-up",
            timing: "Safety follow-up visit within 30 days after the last dose of study drug, or within 60 days of discontinuation of study drug",
            procedures: [
                "Adverse events",
                "Concomitant therapies",
            ]
        }
    ]
}