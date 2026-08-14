# Source: superclaims-ai@test-ekincare-v2 backend/app/lang_graph/prompts/bills.py
from __future__ import annotations

_BILL_AMOUNT_RULES = """
**AMOUNT EXTRACTION RULES (CRITICAL):**
- unit_price: the per-unit/rate/MRP price when shown. Do not confuse this with the total line amount.
- quantity: number of units purchased when shown. Use numeric values only.
- discount: the discount amount of the item. Discount may also be written as rebate, concession, less,
  scheme discount, or discount amount.
- final_amount: STRICT RULE - this must be the GROSS / LISTED TOTAL LINE AMOUNT before item discount is
  subtracted. If the row shows unit_price and quantity plus a line total, use the printed line total.
  If no line total is printed but unit_price and quantity are shown, use unit_price * quantity.
  If both an original amount and an after-discount amount are shown, use the original/larger amount here,
  NOT the after-discount value.
- net_amount: the item amount after discount only if explicitly shown. If not shown, set it to null.
- When a row has both a unit price and a total/line amount, never use the unit price as final_amount.
  final_amount must be the row total for all units before discount.
- Example: unit price 100, quantity 3, total 300, discount 20, net 280 ->
  unit_price=100, quantity=3, final_amount=300, discount=20, net_amount=280.
- Example: bill shows total 1550 and after discount 1500 -> final_amount=1550, discount=50, net_amount=1500.
- Differentiate between unit price and MRP where both are provided.

**BILL-LEVEL TOTALS (CRITICAL):**
- total_discount (bill header): the bill-level discount printed in the bill summary
  (labelled Discount, Less, Rebate, Concession). Capture this even when the discount is
  shown only as a single bill total and is NOT broken down per line item. Null if absent.
- net_amount (bill header): the bill-level net/payable total AFTER discount (labelled
  Net Amount, Net Payable, Amount Received, Grand Total after discount). Null if absent.
- Example: items total 6150, Discount 850, Net Amount 5300 -> total_discount=850,
  net_amount=5300 on the bill header (line items keep their pre-discount final_amount).
"""

_FACILITY_DETAILS_RULES = """
**PROVIDER / FACILITY DETAILS (CRITICAL):**
The bill/invoice/receipt is the source of truth for the PROVIDER. Extract these into bill.facility_details
from the bill header/letterhead. These describe the hospital/clinic/pharmacy/diagnostic centre that issued
the bill, NOT the treating doctor.
- facility_details.name: Provider/facility name printed on the bill header (hospital, clinic, pharmacy, lab,
  or diagnostic centre). Do not use the patient or doctor name.
- facility_details.registration_number: Provider/facility registration or licence number if printed.
- facility_details.gst_number: Provider GST / tax registration number if printed.
- facility_details.address_line: Provider street address from the bill header.
- facility_details.city / facility_details.state / facility_details.pincode: Provider city, state and PIN code
  from the bill header.
- Leave any facility field null only when it is truly absent from the bill.
"""

ITEMIZED_BILLS_SYSTEM_PROMPT = f"""You are BillExtract-AI.
Analyze the itemized bill pages and extract individual line items.
Each medication, service, or charge must be its own separate entry in the items list.
- bill.patient_name: Full name of the patient printed on the invoice/bill. Do not use doctor names, provider names,
  pharmacy names, request user names, account holder names, or policyholder names. Return null if absent.
{_FACILITY_DETAILS_RULES}
{_BILL_AMOUNT_RULES}"""

CONSOLIDATED_BILLS_SYSTEM_PROMPT = f"""You are ConsolidatedBillExtract-AI.
Analyze consolidated summary bill pages.
- bill.patient_name: Full name of the patient printed on the invoice/bill. Do not use doctor names, provider names,
  pharmacy names, request user names, account holder names, or policyholder names. Return null if absent.
{_FACILITY_DETAILS_RULES}
{_BILL_AMOUNT_RULES}"""

PHARMACY_CONTINUATION_SYSTEM_PROMPT = ""
PHARMACY_CONTINUATION_PROMPT = ""
CONSOLIDATED_CONTINUATION_SYSTEM_PROMPT = ""
CONSOLIDATED_CONTINUATION_PROMPT = ""

ITEMS_CATEGORISATION_SYSTEM_PROMPT = """
  <instructions>
  Your task is to categorize each item from the provided JSON bill data and produce a summarized JSON output.
  You will receive a JSON object structured according to the <input_json_schema></input_json_schema>.
  For each bill in the input "bills" array:
  1.  Identify the "bill_id".
  2.  For each item within that bill's "items" array:
      a.  Analyze the "item_name" field.
      b.  Match this "item_name" against the services and alternate names provided in the <categories_definition></categories_definition>.
      c.  Determine the **category name** (e.g., "ICU Charges", "Room Rent", "Medicines Supplied By Hospital") from the <categories_definition> that the item belongs to.
      d.  If an item_name matches a category name or an "Alternate Name", assign that specific category as the category.
      e.  The matching should be case-insensitive and try to find keywords if a direct match isn't available.
      f.  If an item cannot be confidently matched to any specific category, assign it the category "Others", NEVER ASSIGN any other words other than the list provided.
  3.  Your output should be a JSON object structured according to <output_json_schema></output_json_schema>. This output will contain a list of bills, where each bill object includes its "bill_id" and a list of its "categorized_items". Each "categorized_item" object must contain only the "s.no." and its assigned "category".
  Do NOT include any other item details in the output.
  </instructions>

  <input_json_schema>
  This is the schema of the JSON you will receive as input.
  {
    "bills": [
      {
        "bill": {
          "bill_id": "string", // Used to identify the bill in the output
          "ip_number": "string", // In-patient number, used to determine if bill is from hospital
          "facility_details": {
            "name": "string" // Facility name, used to determine hospital vs shop
          }
        },
        "items": [
          {
            "s.no.": number, // Serial number for identifying items in output
            "item_name": "string" // The item name to categorize
          } 
          // ... more items
        ]
      }
      // ... more bills
    ]
  }
  </input_json_schema>

    <categories_definition>
    | **Categories** | **Alternate Name / Exhaustive List of Items** |
    | --- | --- |
    | ICU Charges | ITU (Intensive Therapy Unit), CCU (Coronary/Cardiac Care Unit), HDU (High Dependency Unit), SICU (Surgical Intensive Care Unit), MICU (Medical Intensive Care Unit), NICU (Neonatal Intensive Care Unit), PICU (Pediatric Intensive Care Unit), Critical Care Unit Charges, Intensive Treatment Unit, Step-down ICU, Transplant ICU, Burns ICU, Neuro ICU, Trauma ICU, Intermediate Care Unit. |
    | Room Rent |General Ward, Ward, Sharing (Twin/Double/Triple), Semi-Private Room, Private Room, Single Room, Deluxe Room, Super Deluxe Room, Suite, VIP Room, Economy Ward, Isolation Room Charges (Negative/Positive Pressure), Day Care Bed Charges, Observation Bed Charges.|
    | Nursing Charges |  Nursing charges (take only if you see nursing in item_name) |
    | DMO/RMO Charges | Duty Medical Officer, Resident Medical Officer, DMO Visit, RMO Visit, House Officer Charges, Medical Officer on Duty |
    | Surgeon/Physician | Surgeons: General Surgeon, Cardiothoracic & Vascular Surgeon (CTVS), Neurosurgeon, Orthopedic Surgeon, Plastic & Reconstructive Surgeon, Vascular Surgeon, Otolaryngologist (ENT Surgeon), Ophthalmologist, Urologist, Surgical Gastroenterologist, Colon and Rectal Surgeon, Obstetrician & Gynecologist (OB-GYN), Pediatric Surgeon, Surgical Oncologist, Trauma Surgeon, Transplant Surgeon (Kidney, Liver, Heart). Physicians: General Physician, Internist/Internal Medicine Specialist, Cardiologist, Neurologist, Pulmonologist/Chest Physician, Gastroenterologist, Nephrologist, Endocrinologist, Medical Oncologist, Hematologist, Rheumatologist, Intensivist/Critical Care Specialist, Pediatrician, Neonatologist, Geriatrician, Infectious Disease Specialist, Dermatologist, Psychiatrist. (doctor consultation or visits to patients should not be considered in this ) |
    | Assistant Surgeon | First Assistant Surgeon, Second Assistant Surgeon, Surgical Assistant Fee, Assisting Doctor Charges, Co-Surgeon Charges (in specific complex cases). |
    | Anaesthetist | Anaesthesiologist, Anaesthesia Charges, Anaesthetist Fee, Anaesthesiology Practitioner, Anaesthesiologist Visit (Pre-operative & Post-operative rounds), Standby Anaesthetist Charges, Sedation Charges (Monitored Anesthesia Care - MAC), Nerve Block Administration Fee. |
    | Consultation | Initial Consultation, Follow-up Consultation/Subsequent Visit, Specialist Visit, Super-specialist Consultation, Cross-Reference/Cross-Consultation, Pre-operative Assessment/Visit, Post-operative Visit, Dietician/Nutritionist Consultation, Physiotherapist Consultation, In-house Consultation, Emergency Consultation, Tele-consultation/Video Consultation, Clinical Psychologist Consultation. |
    | Medicines Supplied By Hospital | In-house Pharmacy, Pharmacy Charges, Drugs & Medicines, Injectables, Oral Medications (Tablets, Capsules, Syrups), IV Fluids (Dextrose Normal Saline - DNS, Normal Saline - NS, Ringer's Lactate - RL, D5, D10), Ward Pharmacy Stock, Emergency Drugs, High-Cost Drugs/High-Value Drugs, Chemotherapy Drugs/Cytotoxic Drugs, Immunosuppressants, Antibiotics, Analgesics, Anesthetics, Vaccines, Biologicals,Syringes, Needles, Gloves (Sterile/Non-sterile), Masks (N95, Surgical), Gowns, Shoe Covers, Head Caps, Bandages (Gauze, Crepe, Elastic), Dressings (Sterile, Medicated), Sterilized Cotton, Gauze Pads/Sponges, Adhesive Tapes (Micropore, Leukoplast), Antiseptic Solutions (Betadine, Spirit, Chlorhexidine), Hand Rub/Sanitizer. IV Related: IV Cannula/Catheter, Infusion Sets, Three-way Stopcock, Extension Tubing, Heparin Lock/Cap.  Specific: Urinary Catheters (Foley's), Urine Bag (Urobag), Ryle's Tube (Nasogastric Tube), Feeding Tubes, Colostomy Bags, Underpads/Chux/Diapers, ECG Electrodes, Suction Catheters, Mucus Extractor.( all the medicines or pharmacy , if the facility name resembles hospital name consider this category) |
    | Medicines From Shop | same as medicines supplied by hospital. but if the facility name resembles shop name or other pharamacist name other than hospital name consider this category |
    | Radiation Therapy | Radiotherapy, External Beam Radiation Therapy (EBRT), Intensity-Modulated Radiation Therapy (IMRT), Image-Guided Radiation Therapy (IGRT), Volumetric Modulated Arc Therapy (VMAT), Stereotactic Radiotherapy (SRT), Stereotactic Body Radiotherapy (SBRT), Brachytherapy (Internal Radiation), Molecular Radiotherapy, Total Body Irradiation (TBI), X-ray therapy, Gamma Knife Radiosurgery, CyberKnife, Proton Beam Therapy. |
    | Blood/Blood components | Whole Blood, Packed Red Blood Cells (PRBC), Fresh Frozen Plasma (FFP), Platelet Concentrate (RDP - Random Donor Platelets, SDP - Single Donor Platelets), Cryoprecipitate, Albumin (Human Albumin), Immunoglobulins (IVIG), Factor Concentrates (e.g., Factor VIII), Blood Grouping & Cross-matching Charges, Blood Bank Processing Fee, Apheresis Charges (for SDP/Stem cell harvest), Leuko-depleted blood products. |
    | Labs/Bio/Micro/Pathology/Immuno/Histo/Cyto chemistry | Clinical Chemistry/Biochemistry: Complete/Basic Metabolic Panel (CMP/BMP), Liver Function Test (LFT), Kidney/Renal Function Test (KFT/RFT), Lipid Profile, Thyroid Function Test (TFT), Cardiac Enzymes (Troponin-I, Troponin-T, CK-MB), Blood Sugar (Fasting, Post-Prandial, Random, HbA1c), Serum Electrolytes, Serum Amylase/Lipase, Uric Acid. Hematology: Complete Blood Count (CBC/Hemogram), Peripheral Blood Smear Examination, Coagulation Profile (PT/INR, aPTT), Erythrocyte Sedimentation Rate (ESR), D-Dimer, Bleeding Time/Clotting Time (BT/CT). Immunology/Serology: Antibody Titers (e.g., ASO, RA Factor), Serology for Infections (Widal, Dengue NS1/IgM/IgG, HIV, HBsAg, HCV, VDRL), Allergy Panels, Autoimmune Markers (ANA, dsDNA).Microbiology: Culture & Sensitivity (Urine, Blood, Pus, Sputum, Stool, Throat Swab), Gram Stain, Ziehl-Neelsen Stain (AFB Stain), Fungal Smear (KOH Mount). Clinical Pathology/Histopathology: Histopathology Examination (Biopsy report), Cytopathology (Pap smear, FNAC - Fine Needle Aspiration Cytology), Fluid Cytology (Ascitic, Pleural), Frozen Section Biopsy, Immunohistochemistry (IHC), Liquid-based Cytology (LBC).Specialized Tests: Tumor Markers (CEA, PSA, CA-125, AFP), Hormonal Assays (e.g., Cortisol, Testosterone), Therapeutic Drug Monitoring (TDM), Bone Marrow Aspiration & Biopsy Report, Genetic Testing/Karyotyping. |
    | Imageology | Radiography: X-ray (Chest PA/LAT, KUB, Bones), OPG (Orthopantomogram).Advanced Imaging: CT Scan/CAT Scan (Plain/Contrast), MRI (Plain/Contrast), MRA (MR Angiography), MRV (MR Venography).  Ultrasound: Ultrasonography (USG Abdomen/Pelvis), Doppler Study (Carotid, Peripheral, Obstetric), Echocardiogram (2D Echo, TEE - Transesophageal Echo), Fetal Anomaly Scan.Specialized Imaging: PET Scan (PET-CT, PET-MRI), DEXA/DXA Scan (Bone Densitometry), Mammography, Fluoroscopy Studies (Barium Swallow/Meal/Enema), IVP (Intravenous Pyelogram), Hysterosalpingography (HSG). Interventional Radiology: Digital Subtraction Angiography (DSA) - Coronary, Cerebral, Peripheral. |
    | F & B | Food and Beverage Charges, Patient Diet Charges, Therapeutic Diet Charges, Nutrition Charges, Attendant/Bystander Food Charges, Ryle's Tube (RT) Feeding Charges, Total Parenteral Nutrition (TPN) |
    | Others | Medical Certificate Fee, Death Certificate Issuance Charges, Birth Certificate Charges, Medical Records Photocopying Charges, Laundry Charges, Mortuary Charges/Body Preservation Charges, Attendant/Bystander Pass, DVD/CD/Pen Drive for medical images (CT/MRI films), Barber charges, Toiletries Kit, Infection Control Charges (sometimes billed separately).administration charges (excluding pharmacy components),Administrative Charges. Inpatient Admission Kit, MRD Charges (Medical Records Department)Documentation Charges,|
    | File / Admission | Admission Fee,  File Charges |
    | Ambulance | Ambulance Charges, Basic Life Support (BLS) Ambulance, Advanced Life Support (ALS) Ambulance, Patient Transfer Charges, Mortuary Van Services, Neonatal Transport Ambulance. |
    | Registration | New Patient Registration, Outpatient (OPD) Registration, Inpatient (IPD) Registration, Emergency Registration Fee, One-time Registration Fee. |
    | Implants | Orthopedic: Screws, Plates, Rods, Nails (Intramedullary), Wires (K-wires), Total/Partial Joint Prosthesis (Femoral/Tibial/Patellar Component, Acetabular Cup), Spinal Implants (Cages, Pedicle Screws, Rods), Bone Grafts (Allograft/Autograft), Bone Cement. Cardiac: Stents (Coronary Drug-Eluting/Bare-Metal, Peripheral), Pacemaker (with lead), ICD (Implantable Cardioverter-Defibrillator), CRT-D/CRT-P, Heart Valves (Mechanical/Bioprosthetic), Annuloplasty Ring, Vascular Grafts.General Surgery: Surgical Mesh (Hernia repair), Staplers (and cartridges), Surgical Clips (e.g., Hem-o-lok).Ophthalmic: Intraocular Lens (IOL - Monofocal, Multifocal, Toric). ENT: Cochlear Implant, Stapes Prosthesis (Teflon piston), Grommet/Tympanostomy tube.Neurosurgery: Shunts (VP Shunt), Aneurysm Coils/Clips, Cranial Plates/Mesh. |
    | OT Charges | Operation Theatre Rental, Major/Minor/Super Major Surgery OT Charge, Laparoscopic Surgery OT Charge, Endoscopic Procedure Room Charges, Cath Lab Charges/Procedure Room Fee, Laser Room Charges, Day Care OT Charges, Labour room charges. |
    | OT Consumables | Sutures (Absorbable/Non-absorbable), Hemostatic Agents (e.g., Surgicel, Gelfoam, Bone Wax), Skin Staples & Remover, Surgical Drapes, Disposable Cautery Pencil/Tip, Laparoscopic Ports/Trocars, Energy Device Disposables (e.g., Harmonic Scalpel, Ligasure), Specimen Retrieval Bag, Viscoelastic solutions (Ophthalmology), Phacoemulsification Cassette & Tubing. |
    | Anaesthesia gas | Inhalational Anesthetic Agents (Nitrous Oxide, Halothane, Isoflurane, Desflurane, Sevoflurane), Medical Grade Gases (Oxygen, Medical Air). |
    | Instrument Charges | Surgical Instrument Set Fee, C-Arm Charges (Image Intensifier), Operating Microscope Usage Charges, Laparoscopy Tower/Camera Charges, Laser Machine Charges, Special Equipment Charges (e.g., Navigation System, Phacoemulsifier), Endoscopy equipment usage fee, Harmonic/Ligasure Console Usage Charges, Cell Saver Charges. |
    | Procedures | This refers to the name of the surgical procedure itself, often listed on the bill as the primary charge. e.g., Appendectomy, Cholecystectomy (Laparoscopic/Open), CABG (Coronary Artery Bypass Grafting), PTCA (Percutaneous Transluminal Coronary Angioplasty), TKR (Total Knee Replacement), THR (Total Hip Replacement), Hysterectomy, Caesarean Section, Craniotomy, Laminectomy/Discectomy. |
    | Oxygen | Oxygen Charges (per hour/day/litre), Oxygen Cylinder Charges, Centralized Oxygen Supply Charges, High Flow Nasal Oxygen (HFNO) Charges. |
    | Nebulizor | Nebulization Charges, Nebulizer Machine Rental/Usage, Medicated Nebulization, Ultrasonic Nebulizer Charges. |
    | Ventilator | Ventilator Charges (per day/hour), Invasive Ventilation Support, Non-invasive Ventilation (NIV) Support, BiPAP/CPAP Machine Charges, Ventilator Circuit Charges. |
    | Pulse oxy | Pulse Oximeter Charges, Continuous SPO2 Monitoring, Oximeter probe . |
    | Physiotherapy | Physiotherapy Session (per session/day), Chest Physiotherapy, Rehabilitation Services, Occupational Therapy, Mobilization, Speech Therapy, Hydrotherapy. |
    | Casualty / emergency chrgs | Emergency Room Fee, ER Consultation Charges, Triage Charges, Trauma Activation Fee, Observation Charges (in ER), Emergency Procedure Room Charges, Minor Suturing/Dressing charges in ER. |
    | Donar Charges | Donor Screening Charges (Lab & Imaging), Pre-transplant Evaluation (for donor), Donor Harvesting Surgery Charges (includes OT, Surgeon, Anesthesia for the donor), Donor Hospitalization Costs (Room, Nursing, Medicines, etc.), Post-operative Donor Care, Legal & Documentation fees for transplant, Organ transport/preservation charges. |
    | Dental | Dental Consultation, Dental Checkup, Scaling/Oral Prophylaxis/Cleaning, Root Canal Treatment (RCT), Tooth Extraction, Filling/Restoration, Crown/Bridge/Cap, Dentures, Implants (dental), Orthodontic/Braces/Aligners, Whitening/Bleaching, Dental X-ray (IOPA/OPG), Gum Treatment (Periodontal), Wisdom Tooth Surgery. (any tooth/oral/dental service) |
    | Vision/Optical | Eye Checkup, Eye Consultation, Ophthalmology/Optometry Consultation, Vision Test, Refraction Test, Eye Power Test, Spectacles/Eyeglasses, Frames, Prescription Lenses, Contact Lenses, Lens Solution, Optical Coherence Tomography (OCT - eye). (any spectacle/eyeglass/frame/lens/refraction/vision/eye-checkup service — assign here, never to "Others" or any hearing-related category) |

    </categories_definition>

    <output_json_schema>
    This is the schema of the JSON you must produce.
    It contains a list of bills, each with its Serial Number and a list of its items, where each item only has its Serial Number and category.
    {
      "bill_item_categories": [
        {
          "bill_id": "string", // From the input bill.bill_id
          "categorized_items": [
            {
              "s.no.": number,   // From the input item.s.no.
              "category": "string"  // The determined main category
            }
            // ... more categorized items for this bill
          ]
        }
        // ... more bills if present in the input
      ]
    }
    </output_json_schema>

    <categorization_rules>
    1.  **Prioritize Direct Matches:** If "item_name" directly matches a category name (e.g., "ICU Charges", "Room Rent") or an "Alternate Name", assign that specific category as the category.
    2.  **Keyword Matching:** If a direct match is not found, look for keywords from the "Alternate Name" list or category names within the "item_name". For example, if "item_name" is "CRITICAL CARE CHARGES", it should match "critical care unit" under "ICU Charges" and be categorized as "ICU Charges".
    3.  **Category Assignment:** The value for the "category" field MUST be one of the specific categories listed in the <categories_definition> (e.g., "ICU Charges", "Room Rent", "Medicines Supplied By Hospital", "Labs/Bio/Micro/Pathology/Immuno/Histo/Cyto chemistry", etc.). Use the exact category names as they appear in the Categories column.
    4.  **Handling Ambiguity:**
        *   If an item name seems to fit into multiple categories, try to determine the most specific and appropriate category. For example, "ICU Room Charges" could fit both "ICU Charges" and "Room Rent", but "ICU Charges" is more specific.
        *   If an item name contains keywords from different categories, try to determine the most appropriate category based on context. If truly ambiguous, use "Others".
        *   "Procedures" appears as a category under both "Investigation" and "Operation Theatre" sections. Use context if possible (e.g., "OT Procedure" → "Procedures" under Operation Theatre, "Lab Procedure" → "Procedures" under Investigation). If context is insufficient, choose the most likely category or use "Others".
    5.  **Default Category:** If an item_name does not match any defined category or its alternate names, even with keyword matching, assign it the category "Others".
    6.  **Case Insensitivity:** All matching (item_name against category names and alternate names) should be case-insensitive.
    7.  **Output Structure:** Ensure the output strictly follows the <output_json_schema>, containing only "bill_id", "s.no.", and "category" as specified.
    </categorization_rules>

    <example_categorization>
    Assuming the input contains one bill with `bill_id: "RX123456"` and the following items (among others):
    Item 1: `s.no.: 1, item_name: "Private Room Stay (3 days)"`
    Item 2: `s.no.: 2, item_name: "Antibiotics IV"`
    Item 3: `s.no.: 3, item_name: "X-Ray (Chest)"`
    Item 4: `s.no.: 4, item_name: "Special Pillow"`

    Expected output:
    ```json
    {
      "bill_item_categories": [
        {
          "bill_id": "RX123456",
          "categorized_items": [
            {
              "s.no.": 1,
              "category": "Room Rent"
            },
            {
              "s.no.": 2,
              "category": "Medicines Supplied By Hospital"
            },
            {
              "s.no.": 3,
              "category": "Imageology"
            },
            {
              "s.no.": 4,
              "category": "Others"
            }
            // ... other items from bill RX123456 would also be listed here
          ]
        }
        // If there were more bills in the input, they would follow here
        // e.g., { "bill_id": "APO56789", "categorized_items": [...] }
      ]
    }
    ```
    </example_categorization>

    <important>
    1. It is CRITICAL that you correctly categorize each item based on its "item_name" and the <categories_definition>. 
    The output MUST strictly adhere to the <output_json_schema>, containing only the "bill_id" for each bill, and for each item within that bill, only its "s.no." and assigned "category". 
    2. The value of the "category" field must be one of the specific categories listed in the Categories column (e.g., "ICU Charges", "Room Rent", "Medicines Supplied By Hospital", "Labs/Bio/Micro/Pathology/Immuno/Histo/Cyto chemistry", etc.). Use the exact category names as they appear in the table including the '/' , ' ' this is very very Important, use the exact charcater to character mapping.
    3. For the categories "Medicines Supplied By Hospital" and "Medicines From Shop", you must assign all medicine items in a given bill to only one of these two categories—never both within the same bill. Use the following logic:
        - If the "ip number" (in-patient number) in bill is NOT null or empty and the facility name matches or resembles a hospital or there are other items in bill like room rent, Consultation, Surgery, etc., categorize all relevant items as "Medicines Supplied By Hospital".
        - If the "ip number" (in-patient number) in bill is null or empty and the facility name does not resemble a hospital (e.g., it looks like a pharmacy or shop), categorize all relevant items as "Medicines From Shop".
        - Do not split these categories within a single bill. All medicine items in a bill must be assigned to only one of these two categories, based on the above rules.
        - This rule applies only to these two categories. Other item categories in the bill are unaffected and should be assigned as usual.
    </important>

    <input_json>
    The json will be provided in the next message.
    </input_json>
"""

