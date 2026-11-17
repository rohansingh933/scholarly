"""Starter catalogue.

Facts marked verified_on were read from public scholarship pages on 2026-11-12.
Those pages are third-party summaries, so every record tells students to confirm
on the official site. Records with verified_on = None are well-known schemes whose
2026-27 details have NOT been checked yet - the site flags them as such.

Run `python seed.py --reset` to wipe and reload the catalogue.
"""
import sys

import db
import store

NSP = "https://scholarships.gov.in/"
VERIFIED = "2026-11-12"

SEEDS = [
    {
        "name": "Reliance Foundation Undergraduate Scholarships",
        "provider": "Reliance Foundation", "provider_type": "private",
        "description": "Scholarship for first-year students in regular, full-time undergraduate degrees in any stream. Selection starts with a mandatory online aptitude test.",
        "amount_text": "Up to ₹2,00,000 over the full degree",
        "levels": "ug", "years": "1", "min_percentage": 60, "max_income": 1500000,
        "keywords": "merit, need-based, undergraduate, all streams, corporate, aptitude test",
        "documents": ["Passport-size photograph", "Proof of permanent address", "Aadhaar card (mandatory)",
                      "Class 10 and Class 12 marksheets", "Bonafide student certificate from your college",
                      "Family income proof from a Gram Panchayat, Ward Councillor, Sarpanch, SDM, DM, CO or Tehsildar",
                      "Disability certificate, if applicable", "PAN and bank details (after applying)"],
        "other_requirements": ["Resident Indian citizen",
                               "Regular, full-time degree only: online, hybrid, distance, 2-year and 6-year programmes are not eligible",
                               "Students who did a diploma after Class 10 are not eligible"],
        "selection_process": "Mandatory online aptitude test; the application is complete only after the test.",
        "deadline": "2026-10-05", "deadline_note": "2026-27 window closed on 5 Oct 2026. Watch for the next cycle.",
        "apply_url": "https://www.buddy4study.com/page/reliance-foundation-scholarships",
        "source_url": "https://www.buddy4study.com/article/reliance-foundation-ug-scholarships",
        "verified_on": VERIFIED,
    },
    {
        "name": "AICTE Pragati Scholarship for Girl Students",
        "provider": "AICTE, Ministry of Education (via NSP)", "provider_type": "government",
        "description": "Support for girls studying technical degree or diploma programmes at AICTE-approved institutes.",
        "amount_text": "₹50,000 per year", "amount_per_year": 50000,
        "courses": "engineering,pharmacy,architecture,management", "levels": "diploma,ug", "years": "1,2",
        "gender": "female", "max_income": 800000,
        "keywords": "girls, women, technical education, AICTE, NSP",
        "documents": ["Income certificate issued by the competent authority of your state/UT",
                      "Other documents are listed on NSP: check before applying"],
        "other_requirements": ["Maximum two girl children per family",
                               "Admitted to an AICTE-approved institute",
                               "First year, or second year through lateral entry"],
        "deadline": "2026-11-30",
        "deadline_note": "Sources disagree: 31 Oct 2026 vs 30 Nov 2026 (extended). Confirm on NSP.",
        "apply_url": NSP, "source_url": "https://www.buddy4study.com/article/aicte-scholarships",
        "verified_on": VERIFIED,
    },
    {
        "name": "AICTE Saksham Scholarship for Specially Abled Students",
        "provider": "AICTE, Ministry of Education (via NSP)", "provider_type": "government",
        "description": "Support for students with at least 40% disability studying technical degree or diploma programmes at AICTE-approved institutes.",
        "amount_text": "₹50,000 per year", "amount_per_year": 50000,
        "courses": "engineering,pharmacy,architecture,management", "levels": "diploma,ug", "years": "1,2",
        "disability_only": 1, "max_income": 800000,
        "keywords": "disability, divyang, specially abled, technical education, AICTE, NSP",
        "documents": ["Income certificate issued by the competent authority of your state/UT",
                      "Disability certificate showing 40% or more",
                      "Other documents are listed on NSP: check before applying"],
        "other_requirements": ["Disability of at least 40%", "Admitted to an AICTE-approved institute",
                               "First year, or second year through lateral entry"],
        "deadline": "2026-11-30",
        "deadline_note": "Sources disagree: 31 Oct 2026 vs 30 Nov 2026 (extended). Confirm on NSP.",
        "apply_url": NSP, "source_url": "https://www.buddy4study.com/article/aicte-scholarships",
        "verified_on": VERIFIED,
    },
    {
        "name": "HDFC Bank Parivartan's ECSS Scholarship",
        "provider": "HDFC Bank Parivartan", "provider_type": "private",
        "description": "Educational crisis support for students from low-income families, from school through diploma, ITI, polytechnic, undergraduate and postgraduate courses. Students who faced a personal or family crisis in the last three years get preference.",
        "amount_text": "₹18,000/year for diploma, ITI and polytechnic. UG and PG amounts: see the official site.",
        "levels": "diploma,ug,pg", "min_percentage": 55, "max_income": 250000,
        "keywords": "crisis, low income, need-based, diploma, ITI, polytechnic, undergraduate, postgraduate, bank CSR",
        "documents": ["Passport-size photograph", "Final marksheet of the last qualifying exam (2025-26)",
                      "Government-issued ID proof",
                      "2026-27 admission proof (fee receipt, admission letter, college ID or bonafide certificate)",
                      "Bank passbook copy or cancelled cheque in your or a parent's name",
                      "Income proof from a Gram Panchayat, Ward Councillor, Sarpanch, SDM, DM, CO or Tehsildar, plus an affidavit",
                      "Proof of personal or family crisis, if applicable"],
        "other_requirements": ["Indian national", "Study at a government, government-aided or private institution"],
        "selection_process": "Eligibility shortlisting, document verification, interview, then final list.",
        "deadline": "2026-12-15", "deadline_note": "Deadline was extended. Confirm on the official site.",
        "apply_url": "https://www.parivartanecss.com",
        "source_url": "https://school.careers360.com/articles/hdfc-parivartan-ecss-programme-2026",
        "verified_on": VERIFIED,
    },
    {
        "name": "Kotak Kanya Scholarship",
        "provider": "Kotak Education Foundation", "provider_type": "private",
        "description": "Scholarship for meritorious girls entering the first year of professional degrees at reputed (NIRF/NAAC accredited) institutes.",
        "amount_text": "Up to ₹1,50,000 per year (tuition, hostel, laptop, books and more)", "amount_per_year": 150000,
        "courses": "engineering,medical,law,science,architecture", "levels": "ug", "years": "1",
        "gender": "female", "min_percentage": 75, "max_income": 600000,
        "keywords": "girls, women, engineering, MBBS, integrated LLB, BS-MS, design, architecture, merit",
        "documents": ["Class 10 and Class 12 marksheets", "Income proof or ITR (2025-26)", "College fee structure",
                      "Seat allocation documents", "Entrance exam scorecards", "Aadhaar / personal ID",
                      "Bank passbook", "Passport-size photograph", "Disability certificate, if applicable"],
        "other_requirements": ["Admission in 2026-27 to Engineering, MBBS, Integrated LLB, Integrated BS-MS/BS-Research, IISER, IISc Bangalore, or Design/Architecture",
                               "Children of Kotak Mahindra Group and Kotak Education Foundation employees are not eligible"],
        "selection_process": "Merit and financial screening, document verification, shortlisting, interview, final selection.",
        "deadline": "2026-09-30", "deadline_note": "Reported deadline was 30 Sep (year not stated on the source page). Confirm for the next cycle.",
        "apply_url": "https://kotakeducationfoundation.org/kotak-kanya-scholarship",
        "source_url": "https://university.careers360.com/articles/kotak-kanya-scholarship-2026",
        "verified_on": VERIFIED,
    },
    {
        "name": "ONGC Merit Scholarship",
        "provider": "ONGC Foundation", "provider_type": "private",
        "description": "Scholarship for first-year students from SC, ST, OBC and economically weaker General categories in Engineering, MBBS, MBA and Master's in Geology/Geophysics. Half of the 2,000 awards are reserved for girls.",
        "amount_text": "₹48,000 per year (₹4,000 per month)", "amount_per_year": 48000,
        "courses": "engineering,medical,management,science", "levels": "ug,pg", "years": "1",
        "max_age": 30, "categories": "sc,st,obc,general,ews", "min_percentage": 60,
        "income_rules": "sc:450000,st:450000,obc:200000,general:200000,ews:200000",
        "keywords": "SC, ST, OBC, EWS, engineering, MBBS, MBA, geology, geophysics, PSU, CSR",
        "documents": ["Caste certificate (SC/ST/OBC only)", "Birth certificate or Class 10 marksheet (age proof)",
                      "Class 12 marksheet (Engineering/MBBS) or graduation marksheet (MBA/Geology/Geophysics)",
                      "Family income certificate", "Bank details in the prescribed ECS form, attested by the bank",
                      "PAN card copy", "College ID card and admission receipt", "Undertaking", "NSP OTR number"],
        "other_requirements": ["Indian national, aged up to 30 on 1 Aug 2026",
                               "Full-time regular course, first year only",
                               "Not receiving any other scholarship or financial assistance",
                               "Science applicants: Master's in Geology or Geophysics only",
                               "Minimum 60% (or CGPA 6.0/10) in Class 12 or graduation"],
        "deadline": "2026-11-30", "apply_url": "https://ongcscholar.org/#/",
        "source_url": "https://www.buddy4study.com/scholarship/ongc-merit-scholarship",
        "verified_on": VERIFIED,
    },
    {
        "name": "Aditya Birla Scholarship",
        "provider": "Aditya Birla Group", "provider_type": "private",
        "description": "Prestigious scholarship for top-ranked entrants at select IITs, BITS Pilani, IIMs, XLRI and leading National Law Universities.",
        "amount_text": "₹1.5 lakh (IIT/BITS) to ₹3 lakh (IIM/XLRI) per year", "amount_per_year": 150000,
        "courses": "engineering,management,law", "levels": "ug,pg", "years": "1",
        "keywords": "IIT, IIM, BITS, XLRI, NLU, law, management, merit, leadership",
        "documents": ["Application form", "Letters of recommendation from faculty or the director",
                      "Entrance exam scorecard (JEE / CAT / CLAT etc.)", "Recent passport-size photo",
                      "Mark sheets / transcripts", "ID and address proof", "Extracurricular certificates"],
        "needs_check": "Only for top-20 rankers at select IITs, BITS, IIMs, XLRI or law universities: confirm yours is eligible",
        "essay_required": 1, "essay_details": "Two essays of up to 250 words each, reviewed by a panel.",
        "other_requirements": ["Must be among the top 20 by entrance rank at admission",
                               "Applications go through your institute's Dean or Director"],
        "selection_process": "Application review, essay review, interview in Mumbai, final selection.",
        "deadline_note": "Expected around 31 Oct 2026, not confirmed. Check the official site.",
        "apply_url": "https://adityabirlascholars.net/",
        "source_url": "https://www.indiascholarships.in/scholarships/aditya-birla-scholarship-programme/last-date",
        "verified_on": VERIFIED,
    },
    {
        "name": "Post Matric Scholarship for SC Students",
        "provider": "Ministry of Social Justice and Empowerment (via NSP)", "provider_type": "government",
        "description": "Central scheme that supports SC students after Class 10 with maintenance allowance and course-fee support.",
        "amount_text": "Maintenance allowance plus course fees (varies by course group)",
        "levels": "diploma,ug,pg,phd", "categories": "sc", "max_income": 250000,
        "keywords": "SC, scheduled caste, post matric, central government, NSP",
        "documents": ["Caste certificate", "Income certificate", "Previous year marksheet", "Aadhaar",
                      "Bank passbook", "Admission / fee receipt", "NSP OTR registration"],
        "deadline": "2026-11-30", "deadline_note": "General NSP post-matric deadline after extension. Confirm for your state.",
        "apply_url": NSP, "source_url": "https://school.careers360.com/articles/nsp-scholarship-last-date-2026-27",
    },
    {
        "name": "Post Matric Scholarship for ST Students",
        "provider": "Ministry of Tribal Affairs (via NSP)", "provider_type": "government",
        "description": "Central scheme that supports ST students after Class 10 with maintenance allowance and course-fee support.",
        "amount_text": "Maintenance allowance plus course fees (varies by course group)",
        "levels": "diploma,ug,pg,phd", "categories": "st", "max_income": 250000,
        "keywords": "ST, scheduled tribe, tribal, post matric, central government, NSP",
        "documents": ["Caste certificate", "Income certificate", "Previous year marksheet", "Aadhaar",
                      "Bank passbook", "Admission / fee receipt", "NSP OTR registration"],
        "deadline": "2026-11-30", "deadline_note": "General NSP post-matric deadline after extension. Confirm for your state.",
        "apply_url": NSP, "source_url": "https://school.careers360.com/articles/nsp-scholarship-last-date-2026-27",
    },
    {
        "name": "Post Matric Scholarship for Minorities",
        "provider": "Ministry of Minority Affairs (via NSP)", "provider_type": "government",
        "description": "Central scheme for students from notified minority communities.",
        "amount_text": "Course fees plus maintenance allowance (varies by course)",
        "levels": "diploma,ug,pg,phd", "categories": "minority", "min_percentage": 50, "max_income": 200000,
        "keywords": "minority, Muslim, Christian, Sikh, Buddhist, Jain, Parsi, post matric, NSP",
        "documents": ["Community / minority proof as required", "Income certificate", "Previous year marksheet",
                      "Aadhaar", "Bank passbook", "Admission / fee receipt", "NSP OTR registration"],
        "deadline_note": "Check NSP for the 2026-27 window.",
        "apply_url": NSP,
    },
    {
        "name": "Central Sector Scheme of Scholarship for College and University Students",
        "provider": "Ministry of Education (via NSP)", "provider_type": "government",
        "description": "Merit-based support for students who were in the top 20 percentile in their Class 12 board exam and come from families with limited income.",
        "amount_text": "₹12,000/year for the first three years of UG; ₹20,000/year for later years and PG",
        "amount_per_year": 12000, "levels": "ug,pg", "max_income": 450000,
        "needs_check": "You must be in the top 20 percentile of your Class 12 board: confirm your rank",
        "keywords": "merit, top 20 percentile, class 12, central government, NSP, CSSS",
        "documents": ["Class 12 marksheet", "Income certificate", "Aadhaar", "Bank passbook",
                      "Admission / fee receipt", "NSP OTR registration"],
        "other_requirements": ["Top 20 percentile of successful candidates in your Class 12 board stream",
                               "Regular course; no other scholarship"],
        "deadline_note": "Check NSP; the window usually runs October to November.",
        "apply_url": NSP,
    },
]

for s in SEEDS:
    s.setdefault("source", "seed")
    s.setdefault("status", "active")


def seed_if_empty():
    db.init_db()
    conn = db.open_scholarships()
    try:
        if conn.execute("SELECT COUNT(*) FROM scholarships").fetchone()[0]:
            return 0
        for rec in SEEDS:
            store.insert_scholarship(conn, rec)
        conn.commit()
        return len(SEEDS)
    finally:
        conn.close()


if __name__ == "__main__":
    db.init_db()
    if "--reset" in sys.argv:
        conn = db.open_scholarships()
        conn.execute("DELETE FROM scholarships")
        conn.commit()
        conn.close()
    print(f"Seeded {seed_if_empty()} scholarships.")
