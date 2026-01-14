# Prompt iterations

PROMPT_V1 = """
Extract the following details from the email:
- product_line (pl_sea_import_lcl or pl_sea_export_lcl)
- origin_port_code
- origin_port_name
- destination_port_code
- destination_port_name
- incoterm (FOB, CIF, etc.)
- cargo_weight_kg
- cargo_cbm
- is_dangerous (boolean)

Return valid JSON only.

Email:
Subject: {subject}
Body: {body}
"""

PROMPT_V2 = """
You are an expert in logistics and freight forwarding. Your task is to extract structured shipment details from the provided email.

**Context:**
- All shipments are LCL (Less than Container Load).
- Product Line Logic: 
    - Destination is India -> pl_sea_import_lcl
    - Origin is India -> pl_sea_export_lcl
- Use UN/LOCODEs for ports (e.g., INMAA for Chennai, HKHKG for Hong Kong).

**Output Format:**
Return valid JSON adhering to this structure:
{
  "product_line": "pl_sea_import_lcl",
  "origin_port_code": "HKHKG",
  "origin_port_name": "Hong Kong",
  "destination_port_code": "INMAA",
  "destination_port_name": "Chennai",
  "incoterm": "FOB",
  "cargo_weight_kg": 500.0,
  "cargo_cbm": 2.5,
  "is_dangerous": false
}

**Email:**
Subject: {subject}
Body: {body}
"""

PROMPT_V3 = """
You are an expert freight forwarding assistant. Your task is to extract structured shipment details from the email below, strictly following the business rules.

### Input Data
Ref: Port Codes = Use UN/LOCODE (5 chars, e.g., INMAA, HKHKG).

### Business Rules

1. **Product Line**:
   - `pl_sea_import_lcl` if Destination is India (UN/LOCODE starts with 'IN').
   - `pl_sea_export_lcl` if Origin is India (UN/LOCODE starts with 'IN').
   - Default/Context: All shipments are LCL.

2. **Ports**:
   - Identify Origin and Destination ports.
   - Return the 5-letter UN/LOCODE.
   - If a port is not found or ambiguous, return `null`.

3. **Incoterm**:
   - Allowed: FOB, CIF, CFR, EXW, DDP, DAP, FCA, CPT, CIP, DPU.
   - Default: `FOB` if missing, ambiguous, or invalid.
   - Conflict: Body < Subject (Body wins).

4. **Cargo**:
   - `cargo_weight_kg`: Number (kgs). Convert lbs (* 0.4536) or tonnes (* 1000).
   - `cargo_cbm`: Number (m3). Extract explicit volume. Do not calc from dims.
   - Round to 2 decimals.
   - "0" is 0.0. "TBD"/"N/A" is null.

5. **Dangerous Goods**:
   - `true` if email mentions: "DG", "hazardous", "Class <num>", "IMO", "IMDG".
   - `false` if email says: "non-hazardous", "non-DG", "not dangerous".
   - Default to `false`.

6. **General**:
   - If multiple shipments, extract the FIRST one.
   - Return valid JSON only.

### Output Schema
{{
  "product_line": "string or null",
  "origin_port_code": "string or null",
  "origin_port_name": "string or null",
  "destination_port_code": "string or null",
  "destination_port_name": "string or null",
  "incoterm": "string",
  "cargo_weight_kg": number or null,
  "cargo_cbm": number or null,
  "is_dangerous": boolean
}}

**Email:**
Subject: {subject}
Body: {body}

**JSON Response:**
"""
