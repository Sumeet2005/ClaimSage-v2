"""Seed exactly five new synthetic claims (3 Health, 2 Motor) with realistic synthetic evidence PDFs.

Claims:
1. CLM-DEMO-HEALTH-001 (Health v3): Rohan Varma - Emergency Laparoscopic Appendectomy (INR 74,500)
2. CLM-DEMO-HEALTH-002 (Health v3): Priya Nambiar - Planned Day-Care Cataract Surgery (INR 38,200)
3. CLM-DEMO-HEALTH-003 (Health v3): Siddharth Sen - Acute Severe Gastroenteritis (INR 46,800, 1 day ICU cap check, missing microbiology lab report)
4. CLM-DEMO-MOTOR-001 (Motor v1): Vikrant Roy - Own Damage Road Median Collision (INR 32,400, DL-01-SY-8412)
5. CLM-DEMO-MOTOR-002 (Motor v1): Meera Deshmukh - Multi-Vehicle Rear-End Collision with Police FIR & Surveyor Assessment (INR 89,500, MH-02-SY-4591)
"""

from __future__ import annotations

import logging
import os
import tempfile
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

import pymupdf
from sqlalchemy import select
from sqlalchemy.orm import Session

from claimsage.db.models import (
    AuditEvent,
    Claim,
    ClaimEvidenceChunk,
    ClaimEvidenceDocument,
    Employee,
    PolicyDocument,
)
from claimsage.db.session import SessionLocal
from claimsage.services.evidence_persistence import persist_claim_evidence
from claimsage.services.storage import (
    generate_secure_object_key,
    get_storage_service,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


SYNTHETIC_CLAIMS = [
    {
        "claim_number": "CLM-DEMO-HEALTH-001",
        "claimant_name": "Rohan Varma",
        "claim_type": "health",
        "policy_identifier": "DEMO-HEALTH-SECURE-2026-V3",
        "insurer_name": "ClaimSage Synthetic Assurance Ltd. (fictional)",
        "product_name": "Demo Health Secure Plan",
        "status": "under_review",
        "loss_date": date(2026, 2, 10),
        "summary": (
            "Emergency inpatient hospitalization for acute appendicitis. Laparoscopic appendectomy "
            "performed under general anesthesia. General ward admission for 3 days (room rent INR 4,500/day). "
            "Total claimed expenses INR 74,500."
        ),
        "evidence_files": [
            {
                "filename": "health_claim1_discharge_summary.pdf",
                "title": "City Care Hospital - Final Discharge Summary",
                "text": (
                    "CITY CARE MULTISPECIALTY HOSPITAL (FICTIONAL)\n"
                    "Department of General and Laparoscopic Surgery\n"
                    "INDOOR PATIENT DISCHARGE SUMMARY\n\n"
                    "Patient Name: Rohan Varma | Age: 34 | Gender: Male\n"
                    "IPD Number: IPD-2026-7841 | Claim Reference: CLM-DEMO-HEALTH-001\n"
                    "Date of Admission: 10 Feb 2026, 04:15 AM (Emergency)\n"
                    "Date of Discharge: 13 Feb 2026, 11:30 AM\n"
                    "Admitting Unit: General Ward Bed #302\n\n"
                    "FINAL DIAGNOSIS: Acute Suppurative Appendicitis without perforation.\n\n"
                    "CLINICAL PRESENTATION & HISTORY:\n"
                    "Patient presented to the emergency triage with severe right lower quadrant abdominal pain, "
                    "nausea, low-grade pyrexia (100.8 F), and localized rebound tenderness at McBurney's point. "
                    "Emergency ultrasonography revealed a dilated, non-compressible appendix (8.4 mm outer diameter) "
                    "with periappendiceal fat stranding and free fluid.\n\n"
                    "OPERATIVE PROCEDURE (10 Feb 2026, 08:30 AM):\n"
                    "Emergency 3-port Laparoscopic Appendectomy under General Endotracheal Anesthesia. "
                    "Findings: Inflamed and edematous appendix with mesoappendix hyperemia. Base ligated with "
                    "Endoloop Vicryl suture. Specimen retrieved in endobag. Hemostasis secured. No intra-abdominal drainage required.\n\n"
                    "POST-OPERATIVE COURSE & CONDITION AT DISCHARGE:\n"
                    "Afebrile, hemodynamically stable, oral liquid tolerance achieved on post-op Day 1, soft diet on Day 2. "
                    "Surgical port wounds healthy without discharge. Discharged on oral medications with instructions for suture removal on Day 7."
                ),
            },
            {
                "filename": "health_claim1_itemized_bill.pdf",
                "title": "City Care Hospital - Itemized Final Bill and Payment Receipt",
                "text": (
                    "CITY CARE MULTISPECIALTY HOSPITAL (FICTIONAL)\n"
                    "INDOOR CASE FINAL ITEMIZED INVOICE & RECEIPT\n"
                    "Invoice No: CCH-INV-2026-10492 | Date: 13 Feb 2026\n"
                    "Claimant: Rohan Varma | Policy ID: DEMO-HEALTH-SECURE-2026-V3\n\n"
                    "BREAKDOWN OF CHARGES:\n"
                    "1. Room & Nursing Charges (General Ward): 3 days @ INR 4,500.00 = INR 13,500.00\n"
                    "   (Room rent is within policy sub-limit of INR 5,000 per day)\n"
                    "2. Operation Theatre Charges (Major OT): INR 15,000.00\n"
                    "3. Surgeon Consultation & Laparoscopic Procedure Fee: INR 35,000.00\n"
                    "4. Anesthetist Professional Fee: INR 8,000.00\n"
                    "5. Emergency Diagnostic & Pathology Investigations: INR 6,500.00\n"
                    "6. In-Hospital Medications, IV Fluids & Consumables: INR 7,500.00\n\n"
                    "TOTAL INVOICE AMOUNT: INR 85,500.00\n"
                    "Hospital Discount (Institutional): INR 11,000.00\n"
                    "NET PAYABLE BY CLAIMANT: INR 74,500.00\n"
                    "Payment Status: Paid in Full via Net Banking Txn #NB84920194 on 13 Feb 2026.\n"
                    "This is an illustrative, synthetic invoice."
                ),
            },
            {
                "filename": "health_claim1_surgeon_prescription.pdf",
                "title": "Dr. Vivek Anand (MS, Gen Surg) - Post-Operative Prescription",
                "text": (
                    "CONSULTING SURGICAL CLINIC - DR. VIVEK ANAND, MS (GENERAL SURGERY)\n"
                    "Reg. No: MMC-2008-84291\n"
                    "POST-DISCHARGE CONSULTATION & PRESCRIPTION NOTE\n\n"
                    "Patient: Rohan Varma | Age: 34 M | Date: 13 Feb 2026\n"
                    "Diagnosis: Post Laparoscopic Appendectomy (Day 3)\n\n"
                    "Rx (Medications prescribed for 5 days):\n"
                    "1. Tab. Amoxicillin + Clavulanate 625 mg - 1 tab twice daily after meals x 5 days\n"
                    "2. Tab. Aceclofenac 100 mg + Paracetamol 325 mg - 1 tab twice daily as needed for pain x 3 days\n"
                    "3. Tab. Pantoprazole 40 mg - 1 tab once daily before breakfast x 7 days\n"
                    "4. Syp. Lactulose 15 ml at bedtime as needed\n\n"
                    "ADVICE & INSTRUCTIONS:\n"
                    "- Keep port site dressings dry and clean.\n"
                    "- Avoid heavy lifting (>5 kg) and strenuous physical exercise for 3 weeks.\n"
                    "- Review in Surgical OPD on 20 Feb 2026 for suture inspection and wound evaluation.\n"
                    "- Emergency SOS contact hospital if high fever, severe abdominal distension, or persistent vomiting occurs."
                ),
            },
            {
                "filename": "health_claim1_ultrasound_report.pdf",
                "title": "Apex Diagnostics - Emergency Whole Abdomen Ultrasound Report",
                "text": (
                    "APEX DIAGNOSTIC & IMAGING CENTRE (FICTIONAL)\n"
                    "HIGH RESOLUTION WHOLE ABDOMEN & PELVIS ULTRASONOGRAPHY REPORT\n\n"
                    "Patient: Rohan Varma | Ref by: Dr. Vivek Anand | Date: 10 Feb 2026, 05:00 AM\n\n"
                    "ULTRASOUND FINDINGS:\n"
                    "- Liver, Gallbladder, Biliary Tree, Spleen, Pancreas, and Kidneys: Normal in size, contour, and echotexture.\n"
                    "- Right Iliac Fossa (Appendix):\n"
                    "  Visualized appendix is blind-ending, aperistaltic, non-compressible tubular structure arising from cecal base.\n"
                    "  Maximum outer diameter measures 8.4 mm (Normal <= 6.0 mm).\n"
                    "  Appendiceal wall shows circumferential thickening (3.2 mm) with prominent Doppler mural vascularity.\n"
                    "  Prominent pericecal and periappendiceal fat hyperechoic stranding with a small pocket of localized fluid (approx 4 ml).\n"
                    "  No appendicolith or localized abscess collection detected.\n\n"
                    "IMPRESSION:\n"
                    "Ultrasound features are characteristic of Acute Appendicitis with localized periappendiceal inflammatory changes.\n"
                    "Dr. Rajesh Khanna, MD (Radiodiagnosis) | Consultant Radiologist"
                ),
            },
        ],
    },
    {
        "claim_number": "CLM-DEMO-HEALTH-002",
        "claimant_name": "Priya Nambiar",
        "claim_type": "health",
        "policy_identifier": "DEMO-HEALTH-SECURE-2026-V3",
        "insurer_name": "ClaimSage Synthetic Assurance Ltd. (fictional)",
        "product_name": "Demo Health Secure Plan",
        "status": "under_review",
        "loss_date": date(2026, 3, 5),
        "summary": (
            "Planned day-care ophthalmic surgery. Micro-incision phacoemulsification with foldable "
            "hydrophobic monofocal intraocular lens (IOL) implantation under local topical anesthesia. "
            "Same-day admission and discharge (<24 hrs covered under Day-care Clause Section 2.2). "
            "Total claimed expenses INR 38,200."
        ),
        "evidence_files": [
            {
                "filename": "health_claim2_daycare_discharge.pdf",
                "title": "Netra Eye Institute - Day-Care Surgical Discharge Certificate",
                "text": (
                    "NETRA EYE SPECIALTY INSTITUTE & SURGICAL DAY-CENTRE (FICTIONAL)\n"
                    "DAY-CARE OPHTHALMIC SURGERY DISCHARGE CERTIFICATE\n\n"
                    "Patient: Priya Nambiar | Age: 58 | Gender: Female\n"
                    "Day-Care Reg No: DC-2026-4410 | Claim Ref: CLM-DEMO-HEALTH-002\n"
                    "Admission Date & Time: 05 Mar 2026, 08:00 AM\n"
                    "Discharge Date & Time: 05 Mar 2026, 03:30 PM (Duration: 7.5 hours)\n\n"
                    "DIAGNOSIS: Senile Nuclear Sclerotic Cataract (Grade III) - Left Eye.\n\n"
                    "PROCEDURE PERFORMED: Left Eye Micro-Incision Phacoemulsification with "
                    "Posterior Chamber Foldable Hydrophobic Acrylic Monofocal Intraocular Lens (IOL) Implantation "
                    "under Topical and Intracameral Anesthesia.\n\n"
                    "DAY-CARE ELIGIBILITY NOTE:\n"
                    "This procedure is a technologically advanced, listed day-care ophthalmic surgery requiring less than "
                    "24 hours hospital stay, fully conforming to Section 2.2 of Demo Health Secure Plan v3.0.\n\n"
                    "OPERATIVE DETAILS:\n"
                    "2.2 mm clear corneal incision, continuous curvilinear capsulorhexis, phacoemulsification of nucleus, "
                    "bimanual cortical aspiration, in-the-bag implantation of foldable IOL (Power: +21.5 D). "
                    "Stromal hydration of wounds. Subconjunctival antibiotic-steroid injection. No intraoperative complications.\n\n"
                    "CONDITION AT DISCHARGE:\n"
                    "Left eye patched with protective shield. Intraocular pressure normal (14 mmHg). Discharged in stable condition."
                ),
            },
            {
                "filename": "health_claim2_itemized_bill.pdf",
                "title": "Netra Eye Institute - Final Itemized Bill & Implant Sticker",
                "text": (
                    "NETRA EYE SPECIALTY INSTITUTE (FICTIONAL)\n"
                    "FINAL ITEMIZED DAY-CARE INVOICE & IMPLANT DETAILS\n"
                    "Invoice No: NEI-2026-8812 | Date: 05 Mar 2026\n"
                    "Claimant: Priya Nambiar | Policy: DEMO-HEALTH-SECURE-2026-V3\n\n"
                    "ITEMIZED BILLING PARTICULARS:\n"
                    "1. Day-Care Bed and Nursing Facility Charges: INR 3,000.00\n"
                    "2. Phacoemulsification Operation Theatre Fee & Consumables: INR 15,000.00\n"
                    "3. Surgeon Professional Fee: INR 12,000.00\n"
                    "4. Intraocular Lens Implant (Foldable Hydrophobic Acrylic IOL): INR 6,200.00\n"
                    "   (Implant Serial #IOL-HA-98241, Power: +21.5 D, Barcode Verified)\n"
                    "5. Ophthalmic Viscosurgical Device (OVD) & Pre-op Meds: INR 2,000.00\n\n"
                    "TOTAL CLAIMED AMOUNT: INR 38,200.00\n"
                    "Deductible Applicable under Policy: INR 0.00\n"
                    "Co-pay Applicable under Policy: 0%\n"
                    "Net Amount Paid by Patient: INR 38,200.00 (Receipt #REC-3901, Debit Card txn approved)\n"
                    "Documentary proof of lens implant barcode and sterilization lot number attached."
                ),
            },
            {
                "filename": "health_claim2_biometry_report.pdf",
                "title": "Netra Eye Institute - Optical Biometry and Surgeon Clinical Notes",
                "text": (
                    "NETRA EYE INSTITUTE - OPHTHALMIC BIOMETRY & PRE-OP CLINICAL NOTE\n"
                    "Consultant: Dr. Arvind Swaminathan, MS, DO (Ophthalmology)\n\n"
                    "Patient: Priya Nambiar | Date of Evaluation: 28 Feb 2026\n"
                    "Eye Evaluated: Left Eye (OS)\n\n"
                    "CLINICAL FINDINGS:\n"
                    "- Best Corrected Visual Acuity (BCVA): OD: 6/9 | OS: 6/36 (Defective vision left eye x 8 months)\n"
                    "- Slit Lamp Examination: Cornea clear, anterior chamber deep and quiet, Grade 3 Nuclear Sclerosis with posterior subcapsular haze OS.\n"
                    "- Fundus Examination: Clear media, normal disc and macula, no diabetic or hypertensive retinopathy.\n\n"
                    "OPTICAL BIOMETRY CALCULATION (IOL Master):\n"
                    "- Axial Length OS: 23.42 mm\n"
                    "- Keratometry: K1 = 43.75 D @ 180 deg | K2 = 44.25 D @ 90 deg\n"
                    "- Target Refraction: Emmetropia (0.00 D)\n"
                    "- Recommended Lens Model: Hydrophobic Monofocal Acrylic (+21.50 D, Predicted Refraction: -0.12 D)\n\n"
                    "PLAN: Elective day-care phacoemulsification with IOL under local anesthesia scheduled for 05 Mar 2026."
                ),
            },
        ],
    },
    {
        "claim_number": "CLM-DEMO-HEALTH-003",
        "claimant_name": "Siddharth Sen",
        "claim_type": "health",
        "policy_identifier": "DEMO-HEALTH-SECURE-2026-V3",
        "insurer_name": "ClaimSage Synthetic Assurance Ltd. (fictional)",
        "product_name": "Demo Health Secure Plan",
        "status": "documents_pending",
        "loss_date": date(2026, 4, 12),
        "summary": (
            "Hospitalization for severe acute gastroenteritis with systemic dehydration and electrolyte disturbance. "
            "Total 2 days hospitalization including 1 day in ICU. Total claim INR 46,800. Notice: Diagnostic stool "
            "culture and serum electrolyte lab report pending submission; ICU charge billed at INR 12,000 against INR 10,000 cap."
        ),
        "evidence_files": [
            {
                "filename": "health_claim3_discharge_summary.pdf",
                "title": "Apex Multispecialty Hospital - Discharge Summary",
                "text": (
                    "APEX MULTISPECIALTY HOSPITAL (FICTIONAL)\n"
                    "DEPARTMENT OF INTERNAL MEDICINE - DISCHARGE SUMMARY\n\n"
                    "Patient Name: Siddharth Sen | Age: 42 | Gender: Male\n"
                    "UHID: APX-904128 | Claim Ref: CLM-DEMO-HEALTH-003\n"
                    "Date & Time of Admission: 12 Apr 2026, 06:30 AM\n"
                    "Date & Time of Discharge: 14 Apr 2026, 01:00 PM (Total: 2 days)\n"
                    "Bed Classification: ICU (Day 1: 12-13 Apr) -> High Dependency Ward (Day 2: 13-14 Apr)\n\n"
                    "ADMISSION DIAGNOSIS & REASON FOR ICU ADMISSION:\n"
                    "Acute bacterial gastroenteritis with severe grade III dehydration, hypokalemia (K+ 2.8 mEq/L), "
                    "hypotension (BP 82/50 mmHg), and borderline tachycardia. Admitted to Intensive Care Unit for continuous "
                    "cardiac and hemodynamic monitoring, aggressive IV crystalloid resuscitation, and parenteral potassium repletion.\n\n"
                    "CLINICAL SUMMARY & TREATMENT GIVEN:\n"
                    "Patient resuscitated with IV Ringer Lactate and Normal Saline with KCl infusion under cardiac monitoring. "
                    "Blood pressure normalized to 118/74 mmHg by post-admission Hour 18. Shifted to step-down ward on 13 Apr. "
                    "Treated with IV Ceftriaxone, IV Ondansetron, and oral rehydration solution.\n\n"
                    "CONDITION AT DISCHARGE:\n"
                    "Hemodynamically stable, afebrile, tolerating light solid diet, bowel movements normalized. "
                    "Discharged with oral antibiotic course for 5 days. Diagnostic stool culture and sensitivity report pending from laboratory."
                ),
            },
            {
                "filename": "health_claim3_itemized_bill.pdf",
                "title": "Apex Multispecialty Hospital - Final Hospital Invoice",
                "text": (
                    "APEX MULTISPECIALTY HOSPITAL (FICTIONAL)\n"
                    "INDOOR PATIENT FINAL ITEMIZED INVOICE\n"
                    "Invoice No: APX-INV-2026-3490 | Date: 14 Apr 2026\n"
                    "Claimant: Siddharth Sen | Policy ID: DEMO-HEALTH-SECURE-2026-V3\n\n"
                    "ITEMIZED CHARGES:\n"
                    "1. Intensive Care Unit (ICU) Room & Monitoring: 1 day @ INR 12,000.00 = INR 12,000.00\n"
                    "   [POLICY REVIEW NOTE: Policy Section 3 sets ICU daily cap at INR 10,000.00 per day;\n"
                    "    billed INR 12,000 exceeds sub-limit by INR 2,000]\n"
                    "2. General Ward Bed Charges: 1 day @ INR 4,800.00 = INR 4,800.00\n"
                    "   (Within room rent limit of INR 5,000 per day)\n"
                    "3. Critical Care & Intensivist Consultation: INR 8,000.00\n"
                    "4. Attending Physician Medical Visits (2 days): INR 5,000.00\n"
                    "5. Intravenous Infusions, Medications & Consumables: INR 11,500.00\n"
                    "6. Emergency ECG, Arterial Blood Gas & Nursing Care: INR 5,500.00\n\n"
                    "TOTAL BILL AMOUNT: INR 46,800.00\n"
                    "Total Amount Paid by Patient: INR 46,800.00 (Receipt #REC-APX-890, UPI confirmation attached)\n"
                    "Note: Stool culture and diagnostic pathology bill will be reconciled upon receipt of final lab report."
                ),
            },
            {
                "filename": "health_claim3_physician_prescription.pdf",
                "title": "Dr. Sunita Rao (MD, Medicine) - Initial Admission & Treatment Order",
                "text": (
                    "APEX HOSPITAL - DEPARTMENT OF INTERNAL MEDICINE\n"
                    "CLINICAL ADMISSION & EMERGENCY CONSULTATION RECORD\n\n"
                    "Consultant: Dr. Sunita Rao, MD (Internal Medicine) | Reg No: MCI-99418\n"
                    "Patient: Siddharth Sen | Date: 12 Apr 2026, 06:45 AM\n\n"
                    "PRESENTING COMPLAINTS:\n"
                    "Profuse watery diarrhea (8-10 episodes), persistent vomiting, severe dizziness, muscular cramps, "
                    "and acute weakness for the preceding 14 hours following street food ingestion.\n\n"
                    "PHYSICAL EXAMINATION:\n"
                    "Dry buccal mucosa, sunken eyes, delayed skin turgor (>3 sec), Pulse: 112 bpm (weak, thready), BP: 82/50 mmHg.\n"
                    "Abdomen: Diffuse soft tenderness, hyperactive bowel sounds. No guarding or rigidity.\n\n"
                    "EMERGENCY ADMISSION ORDERS:\n"
                    "1. Immediate ICU admission for hemodynamic stabilization.\n"
                    "2. IV access x 2 wide-bore cannulas; 2 Liters RL stat over 2 hours, then maintenance infusion.\n"
                    "3. Blood investigations: CBC, Serum Electrolytes, Renal Function Tests, Blood Glucose stat.\n"
                    "4. Stool Routine Microscopy and Hanging Drop Culture to rule out bacterial pathogens (Lab to send report).\n"
                    "5. Inj. Ceftriaxone 1g IV BD; Inj. Ondansetron 4mg IV TDS; Inj. Pantoprazole 40mg IV OD."
                ),
            },
        ],
    },
    {
        "claim_number": "CLM-DEMO-MOTOR-001",
        "claimant_name": "Vikrant Roy",
        "claim_type": "auto",
        "policy_identifier": "DEMO-MOTOR-SECURE-2026-V1",
        "insurer_name": "ClaimSage Synthetic General Insurance Ltd. (fictional)",
        "product_name": "Demo Motor Secure Plan",
        "status": "under_review",
        "loss_date": date(2026, 3, 20),
        "summary": (
            "Own-damage motor accident claim for private passenger car DL-01-SY-8412 (2023 Sedan, IDV INR 650,000). "
            "Driver skidded during heavy rain at low speed and hit a concrete roadside median. Front bumper assembly "
            "and left headlamp damaged. No personal injuries or third-party property damage. Total repair estimate INR 32,400."
        ),
        "evidence_files": [
            {
                "filename": "motor_claim1_incident_statement.pdf",
                "title": "Driver Incident Statement and Claim Declaration Form",
                "text": (
                    "CLAIMSAGE SYNTHETIC GENERAL INSURANCE - MOTOR CLAIM INTAKE FORM\n"
                    "OWN-DAMAGE INCIDENT REPORT & DECLARATION\n\n"
                    "Policy Number: DEMO-MOTOR-SECURE-2026-V1 | Claim Number: CLM-DEMO-MOTOR-001\n"
                    "Insured / Claimant: Vikrant Roy | Contact: vikrant.roy.fictional@example.com\n"
                    "Vehicle Registration No: DL-01-SY-8412 | Make & Model: 2023 Compact Sedan Petrol 1.2L\n"
                    "Date & Time of Incident: 20 Mar 2026 at approx 09:45 PM\n"
                    "Location of Accident: Ring Road flyover descent, New Delhi\n\n"
                    "STATEMENT OF OCCURRENCE:\n"
                    "I was driving home during an unexpected torrential downpour at approximately 35-40 km/h. "
                    "While descending the flyover ramp, the vehicle encountered waterlogging and hydroplaned, causing "
                    "the front left corner to collide with the stationary concrete road median barrier. "
                    "The vehicle was immediately stopped. The front plastic bumper cover fractured and dislodged, and the left "
                    "headlamp lens cracked. The radiator and engine remained undamaged. "
                    "No other vehicle or third-party property was involved. No bodily injury occurred to myself or any other person.\n\n"
                    "DECLARATION:\n"
                    "I certify that I held a valid driving license, was not under the influence of alcohol or drugs, and the vehicle "
                    "was used strictly for personal, non-commercial purposes."
                ),
            },
            {
                "filename": "motor_claim1_rc_and_dl.pdf",
                "title": "Vehicle Registration Certificate (RC) & Driving Licence Dossier",
                "text": (
                    "GOVERNMENT TRANSPORT DEPARTMENT (SYNTHETIC RECORD)\n"
                    "CERTIFICATE OF REGISTRATION & DRIVING LICENCE RECORD\n\n"
                    "VEHICLE PARTICULARS:\n"
                    "- Registration Mark: DL-01-SY-8412 | Class: Motor Car (LMV - Private Personal)\n"
                    "- Owner Name: Vikrant Roy | Registration Date: 15 Apr 2023\n"
                    "- Chassis No: MA3EKB81SN0849201 | Engine No: K12M9482014\n"
                    "- Fuel Type: Petrol | Seating Capacity: 5 | Color: Pearl Arctic White\n"
                    "- Hypothecation: None (Unencumbered)\n\n"
                    "DRIVING LICENCE PARTICULARS:\n"
                    "- DL Number: DL-0120150948201\n"
                    "- Licensee: Vikrant Roy | DOB: 18 Aug 1988\n"
                    "- Entitlement: LMV (Non-Transport / Private Car)\n"
                    "- Date of Initial Issue: 12 Jun 2015\n"
                    "- Validity Period: 12 Jun 2015 to 17 Aug 2038 (Current & Fully Valid on Date of Loss)\n"
                    "- Badge / Commercial Endorsement: None (Not Required for Private Car)"
                ),
            },
            {
                "filename": "motor_claim1_repair_estimate.pdf",
                "title": "AutoCare Authorized Body Shop - Repair Estimate and Parts Schedule",
                "text": (
                    "AUTOCARE MOTORS AUTHORIZED SERVICE CENTRE (FICTIONAL)\n"
                    "DETAILED ACCIDENT REPAIR ESTIMATE & DEPRECIATION SCHEDULE\n"
                    "Estimate No: AC-EST-2026-992 | Date: 22 Mar 2026\n"
                    "Vehicle: DL-01-SY-8412 | Owner: Vikrant Roy | Claim Ref: CLM-DEMO-MOTOR-001\n\n"
                    "ESTIMATED PARTS & MATERIAL COSTS:\n"
                    "1. Front Bumper Cover (Material: Plastic / Polypropylene):\n"
                    "   Gross Part Price: INR 8,500.00 | Depreciation (50% Plastic Schedule): INR 4,250.00 | Net: INR 4,250.00\n"
                    "2. Headlamp Assembly Left (Material: Glass / Plastic Lens):\n"
                    "   Gross Part Price: INR 6,200.00 | Depreciation (50% Composite Lens): INR 3,100.00 | Net: INR 3,100.00\n"
                    "3. Front Radiator Grill (Plastic / Chrome Plated):\n"
                    "   Gross Part Price: INR 2,800.00 | Depreciation (50% Plastic): INR 1,400.00 | Net: INR 1,400.00\n"
                    "4. Bumper Mounting Brackets & Fasteners (Metal):\n"
                    "   Gross Part Price: INR 1,400.00 | Depreciation (Age 2-3 yrs, 15% Metal Schedule): INR 210.00 | Net: INR 1,190.00\n\n"
                    "LABOR & PAINTING CHARGES (Not subject to depreciation):\n"
                    "5. Bumper Removal, Fitting & Alignment Labor: INR 3,500.00\n"
                    "6. Surface Preparation, Primer & Paint (3-Stage Pearl Coat): INR 8,000.00\n"
                    "7. Left Fender Blending & Buffing: INR 2,000.00\n\n"
                    "TOTAL GROSS ESTIMATE: INR 32,400.00\n"
                    "Policy Compulsory Deductible to be Deducted upon Settlement: INR 1,000.00 (Section 3)\n"
                    "Net Admissible Estimate before Tax: INR 22,440.00"
                ),
            },
            {
                "filename": "motor_claim1_damage_photos.pdf",
                "title": "On-Site Vehicle Damage Photographic Dossier",
                "text": (
                    "CLAIMSAGE CLAIMS WORKSPACE - EVIDENCE INSPECTION DOSSIER\n"
                    "DIGITAL ACCIDENT PHOTOGRAPHY EVIDENCE SHEET\n"
                    "Claim ID: CLM-DEMO-MOTOR-001 | Vehicle: DL-01-SY-8412 | Inspection Date: 21 Mar 2026\n\n"
                    "INDEX OF RECORDED PHOTOGRAPHS:\n"
                    "Photo 1 [Front 45-degree angle]: Clear overview of vehicle registration plate DL-01-SY-8412 "
                    "showing longitudinal fracture on lower left quadrant of the plastic front bumper cover.\n"
                    "Photo 2 [Left Headlamp Detail]: Close-up capture of cracked outer polycarbonate lens "
                    "and distorted internal reflector housing.\n"
                    "Photo 3 [Odometer & Dashboard]: Instrument cluster showing odometer reading 22,481 km, "
                    "ignition ON, no engine malfunction or airbag warning lamps illuminated.\n"
                    "Photo 4 [Vehicle Identification Number / VIN Plate]: Stamped VIN MA3EKB81SN0849201 on B-pillar "
                    "matching Certificate of Registration.\n\n"
                    "Surveyor Initial Remark: Damage pattern is fresh and completely consistent with reported "
                    "low-speed collision with concrete median barrier."
                ),
            },
        ],
    },
    {
        "claim_number": "CLM-DEMO-MOTOR-002",
        "claimant_name": "Meera Deshmukh",
        "claim_type": "auto",
        "policy_identifier": "DEMO-MOTOR-SECURE-2026-V1",
        "insurer_name": "ClaimSage Synthetic General Insurance Ltd. (fictional)",
        "product_name": "Demo Motor Secure Plan",
        "status": "under_review",
        "loss_date": date(2026, 4, 5),
        "summary": (
            "Own-damage claim resulting from multi-vehicle collision. Insured vehicle MH-02-SY-4591 (2022 Executive Sedan, "
            "IDV INR 780,000) was rear-ended by a commercial pickup while waiting at a red traffic signal. Significant damage "
            "to rear trunk lid, rear bumper assembly, and both tail lamp clusters. Police Station Dairy Entry / FIR registered. "
            "Independent licensed surveyor assessment completed. Total workshop invoice INR 89,500."
        ),
        "evidence_files": [
            {
                "filename": "motor_claim2_claim_form.pdf",
                "title": "Motor Insurance Comprehensive Claim Form",
                "text": (
                    "CLAIMSAGE SYNTHETIC GENERAL INSURANCE LTD.\n"
                    "COMPREHENSIVE MOTOR ACCIDENT CLAIM FORM\n\n"
                    "Policy Number: DEMO-MOTOR-SECURE-2026-V1 | Claim No: CLM-DEMO-MOTOR-002\n"
                    "Insured Name: Meera Deshmukh | Phone: 98201-FICTIONAL | Email: meera.deshmukh@example.com\n"
                    "Vehicle: MH-02-SY-4591 | Make: 2022 Executive Sedan 1.5L Turbo Petrol | IDV: INR 780,000.00\n"
                    "Date & Time of Accident: 05 Apr 2026, 05:40 PM\n"
                    "Place of Accident: Eastern Express Highway junction, Mumbai\n\n"
                    "ACCIDENT DETAILS:\n"
                    "The insured vehicle was stationary at a traffic signal. A third-party light commercial vehicle "
                    "failed to brake in time and rammed forcefully into the rear of our vehicle, shunting it forward. "
                    "Extensive structural deformation occurred to the trunk boot lid, rear bumper, rear panel, and both "
                    "tail lamps were shattered. Police traffic patrol arrived at scene and directed both vehicles to the police station.\n"
                    "FIR recorded at Kurla Police Station (Station Dairy Entry #412/2026).\n\n"
                    "Driver at Time of Accident: Meera Deshmukh (Owner-driver, valid DL enclosed).\n"
                    "Third-Party Vehicle Details: MH-04-COMM-9912 (Commercial carrier)."
                ),
            },
            {
                "filename": "motor_claim2_rc_and_dl.pdf",
                "title": "Registration Certificate (RC) & Driving Licence Verification",
                "text": (
                    "MOTOR VEHICLES DEPARTMENT - MAHARASHTRA STATE (SYNTHETIC RECORD)\n"
                    "VEHICLE REGISTRATION & DRIVING LICENCE RECORD\n\n"
                    "REGISTRATION DETAILS:\n"
                    "- Registration Number: MH-02-SY-4591 | Class: LMV (Motor Car - Private)\n"
                    "- Owner: Meera Deshmukh | Registration Date: 12 Jan 2022 (Vehicle Age: 4 yrs 3 mos)\n"
                    "- Chassis No: MALCE51BP8490124 | Engine No: D4FB8491024\n"
                    "- Hypothecated to: Synthetic National Bank Ltd. (NOC obtained for claim processing)\n\n"
                    "DRIVING LICENCE PARTICULARS:\n"
                    "- Driving Licence No: MH-0220120049182\n"
                    "- Name: Meera Deshmukh | Date of Birth: 04 May 1984\n"
                    "- Authorized Vehicle Class: LMV-NT (Private Car)\n"
                    "- Valid Through: 03 May 2034\n"
                    "- Endorsements / Restrictions: None."
                ),
            },
            {
                "filename": "motor_claim2_police_fir.pdf",
                "title": "Kurla Police Station - First Information Report / Station Diary Extract",
                "text": (
                    "GOVERNMENT OF MAHARASHTRA - POLICE DEPARTMENT\n"
                    "KURLA TRAFFIC POLICE STATION - STATION DIARY EXTRACT & ACCIDENT REPORT\n"
                    "Station Diary Entry No: 412/2026 | Date: 05 Apr 2026, 19:15 hrs\n\n"
                    "INCIDENT REPORT SUMMARY:\n"
                    "On 05 Apr 2026 at approx 17:40 hrs, a vehicular collision occurred at Eastern Express Highway Junction. "
                    "Vehicle 1: Private Car MH-02-SY-4591 driven by Meera Deshmukh.\n"
                    "Vehicle 2: Commercial Delivery Van MH-04-COMM-9912 driven by Ramesh Lal.\n\n"
                    "POLICE ENQUIRY FINDINGS:\n"
                    "Vehicle 1 was halted in compliance with traffic signal. Vehicle 2 approaching from rear failed to maintain "
                    "safe braking distance due to wet surface and collided heavily into the rear of Vehicle 1. "
                    "No human fatalities or grievous bodily injuries occurred. Both drivers underwent mandatory breathalyzer "
                    "testing: BAC reading for both drivers was 0.0 mg/100ml (Negative for alcohol).\n"
                    "Panchnama recorded at site; photographs of vehicle damage and site sketch annexed to station diary.\n"
                    "Senior Police Inspector | Kurla Police Station"
                ),
            },
            {
                "filename": "motor_claim2_surveyor_report.pdf",
                "title": "IRDAI Licensed Surveyor & Loss Assessor - Final Assessment Report",
                "text": (
                    "ALPHA LOSS ASSESSORS & SURVEYORS LLP (FICTIONAL)\n"
                    "IRDAI LICENSED SURVEYOR & LOSS ADJUSTER REPORT\n"
                    "Surveyor License No: SLA-2016-89410 | Survey Date: 07 Apr 2026\n"
                    "Claim No: CLM-DEMO-MOTOR-002 | Policy: DEMO-MOTOR-SECURE-2026-V1\n"
                    "Insured: Meera Deshmukh | Vehicle: MH-02-SY-4591 (2022 Model, Age > 4 years)\n\n"
                    "ASSESSMENT OF LOSS:\n"
                    "Inspected vehicle at authorized body shop premises. Damage directly correlates with reported collision.\n\n"
                    "PART REPLACEMENTS & SCHEDULED DEPRECIATION (Per Policy Section 3):\n"
                    "1. Rear Bumper Assembly (Plastic): Gross INR 14,000.00 | 50% Depreciation = INR 7,000.00 | Net: INR 7,000.00\n"
                    "2. Tail Lamp Cluster Left & Right (Composite Glass/Plastic): Gross INR 11,000.00 | 50% Dep = INR 5,500.00 | Net: INR 5,500.00\n"
                    "3. Trunk Lid / Boot Door (Metal Part, Vehicle Age 4-5 yrs -> 35% Metal Depreciation Schedule):\n"
                    "   Gross INR 28,000.00 | 35% Depreciation = INR 9,800.00 | Net: INR 18,200.00\n"
                    "4. Rear Cross Member & Reinforcement Bar (Metal, 35% Dep):\n"
                    "   Gross INR 9,500.00 | 35% Depreciation = INR 3,325.00 | Net: INR 6,175.00\n\n"
                    "LABOR & PAINTING (No depreciation):\n"
                    "5. Rear Bodyshell Denting & Alignment Labor: INR 12,000.00\n"
                    "6. Computerized Paint Matching & Oven Baking: INR 15,000.00\n\n"
                    "SUMMARY OF ASSESSMENT:\n"
                    "Total Gross Invoice Value: INR 89,500.00\n"
                    "Less Scheduled Depreciation: INR 25,625.00\n"
                    "Less Compulsory Policy Deductible: INR 1,000.00\n"
                    "Net Recommended Admissible Settlement: INR 62,875.00\n"
                    "Signed: K. R. Namboodiri, IRDAI Licensed Surveyor"
                ),
            },
            {
                "filename": "motor_claim2_repair_invoice.pdf",
                "title": "Prime Auto Bodyshop - Final GST Tax Invoice and Receipt",
                "text": (
                    "PRIME MOTORS WORKSHOP & BODYSHOP LTD. (FICTIONAL)\n"
                    "AUTHORIZED ACCIDENT REPAIR FINAL TAX INVOICE\n"
                    "GSTIN: 27AAAAA0000A1Z5 | Invoice No: PMW-2026-4019 | Date: 16 Apr 2026\n"
                    "Customer: Meera Deshmukh | Vehicle: MH-02-SY-4591 | Claim: CLM-DEMO-MOTOR-002\n\n"
                    "TAX INVOICE PARTICULARS:\n"
                    "1. Part: Rear Bumper Cover Sub-Assy - INR 14,000.00\n"
                    "2. Part: Tail Lamp Assembly Combo (LH + RH) - INR 11,000.00\n"
                    "3. Part: Trunk Lid Panel Complete - INR 28,000.00\n"
                    "4. Part: Rear Bumper Reinforcement Beam - INR 9,500.00\n"
                    "5. Labor: Rear Quarter Panel Realignment & Structural Pulling - INR 12,000.00\n"
                    "6. Labor: Metallic Multi-Coat Oven Baking & Refinishing - INR 15,000.00\n\n"
                    "TOTAL TAXABLE VALUE: INR 89,500.00\n"
                    "CGST (0%) / SGST (0%) - Synthetic Demo Billing\n"
                    "TOTAL INVOICE AMOUNT: INR 89,500.00\n"
                    "Payment Received: Paid in full by Insured via Bank Transfer NEFT #N1094819 on 16 Apr 2026.\n"
                    "Vehicle gate pass issued upon final quality inspection."
                ),
            },
        ],
    },
]


def create_pdf_from_text(title: str, text: str, output_path: Path) -> None:
    """Render synthetic document text to a standardized PDF using PyMuPDF."""
    doc = pymupdf.open()
    try:
        page = doc.new_page()
        # Title
        page.insert_text((48, 45), title, fontsize=12, fontname="helv", color=(0.1, 0.2, 0.15))
        # Body text
        rect = pymupdf.Rect(48, 70, 550, 780)
        remaining = page.insert_textbox(rect, text, fontsize=9.5, fontname="helv", lineheight=1.35)
        if remaining < 0:
            # Need a second page
            page2 = doc.new_page()
            rect2 = pymupdf.Rect(48, 45, 550, 780)
            page2.insert_textbox(rect2, text[len(text) // 2:], fontsize=9.5, fontname="helv", lineheight=1.35)
        doc.save(str(output_path))
    finally:
        doc.close()


def seed_demo_claims() -> None:
    session = SessionLocal()
    storage = get_storage_service()
    storage.ensure_bucket_exists()

    try:
        # Get admin employee
        admin = session.scalar(
            select(Employee).where(Employee.email == "admin@claimsage.local")
        )
        if not admin:
            raise RuntimeError("Admin employee 'admin@claimsage.local' not found!")

        # Get primary claims adjuster/analyst
        adjuster = session.scalar(
            select(Employee).where(Employee.email == "alex.adjuster@claimsage.local")
        )
        if not adjuster:
            adjuster = admin

        temp_dir = Path(tempfile.mkdtemp(prefix="claimsage_demo_evidence_"))
        logger.info("Using temporary directory for PDF generation: %s", temp_dir)

        created_claims = 0
        created_docs = 0

        for claim_data in SYNTHETIC_CLAIMS:
            claim_number = claim_data["claim_number"]
            existing_claim = session.scalar(
                select(Claim).where(Claim.claim_number == claim_number)
            )

            if existing_claim is not None:
                logger.info("Claim %s already exists with ID %s. Skipping creation.", claim_number, existing_claim.id)
                claim = existing_claim
            else:
                claim = Claim(
                    id=uuid.uuid4(),
                    claim_number=claim_number,
                    claimant_name=claim_data["claimant_name"],
                    claim_type=claim_data["claim_type"],
                    policy_identifier=claim_data["policy_identifier"],
                    insurer_name=claim_data["insurer_name"],
                    product_name=claim_data["product_name"],
                    status=claim_data["status"],
                    loss_date=claim_data["loss_date"],
                    summary=claim_data["summary"],
                    assigned_employee_id=adjuster.id,
                    team_id=adjuster.team_id or "claims-team",
                )
                session.add(claim)
                session.flush()

                session.add(
                    AuditEvent(
                        actor_employee_id=admin.id,
                        claim_id=claim.id,
                        action="claim_created",
                        resource_type="claim",
                        resource_id=str(claim.id),
                        details=f"Synthetic demo claim {claim.claim_number} created for {claim.claimant_name}.",
                    )
                )
                session.commit()
                created_claims += 1
                logger.info("Created claim %s (%s) with ID: %s", claim.claim_number, claim.claim_type, claim.id)

            # Process evidence files for this claim
            for ev in claim_data["evidence_files"]:
                existing_doc = session.scalar(
                    select(ClaimEvidenceDocument).where(
                        ClaimEvidenceDocument.claim_id == claim.id,
                        ClaimEvidenceDocument.filename == ev["filename"],
                    )
                )
                if existing_doc is not None:
                    logger.info("Evidence %s already exists for claim %s", ev["filename"], claim.claim_number)
                    continue

                pdf_path = temp_dir / ev["filename"]
                create_pdf_from_text(ev["title"], ev["text"], pdf_path)

                # Upload to MinIO
                storage_key = generate_secure_object_key(f"evidence/{claim.id}")
                with pdf_path.open("rb") as f_obj:
                    stored_meta = storage.upload_document(
                        content=f_obj,
                        object_key=storage_key,
                        content_type="application/pdf",
                    )

                # Persist evidence document & chunks
                doc = persist_claim_evidence(
                    db=session,
                    file_path=pdf_path,
                    claim_id=claim.id,
                    uploader_employee_id=admin.id,
                    filename=ev["filename"],
                    storage_provider="s3",
                    storage_bucket=stored_meta.bucket,
                    storage_key=stored_meta.object_key,
                    storage_status="stored",
                )

                session.add(
                    AuditEvent(
                        actor_employee_id=admin.id,
                        claim_id=claim.id,
                        action="claim_evidence_uploaded",
                        resource_type="claim_evidence_document",
                        resource_id=str(doc.id),
                        details=f"Evidence document {doc.filename} persisted with {len(doc.chunks)} chunks.",
                    )
                )
                session.commit()
                created_docs += 1
                logger.info("Persisted evidence %s for claim %s (chunks: %d)", ev["filename"], claim.claim_number, len(doc.chunks))

        logger.info("=== Demo Claims Seeding Finished ===")
        logger.info("Newly created claims: %d", created_claims)
        logger.info("Newly created evidence documents: %d", created_docs)

    finally:
        session.close()


if __name__ == "__main__":
    seed_demo_claims()
