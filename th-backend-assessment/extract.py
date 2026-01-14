import os
import json
import time
import re
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
from groq import Groq, APIError
from rich.console import Console
from rich.progress import track

from schemas import ShipmentDetails
import prompts

# Load variables
load_dotenv()
console = Console()

# Configuration
API_KEY = os.getenv("GROQ_API_KEY")
MODEL = "llama-3.1-70b-versatile"
INPUT_FILE = "emails_input.json"
OUTPUT_FILE = "output.json"
PORT_CODES_FILE = "port_codes_reference.json"

# --- Business Rules / Helpers ---

def load_port_reference(path: str) -> Dict[str, str]:
    """
    Loads port codes mapping.
    Returns: Dict[code, name]
    Policy: Handle duplicates. Avoid known bad mappings in the reference file (e.g., INMAA -> Bangalore ICD).
    """
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        mapping = {}
        # First pass: Load all, but skip suspicious ones if we find better ones later?
        # Better strategy: Load all into a list, then pick the best one.
        
        temp_map = {}
        for entry in data:
            code = entry.get('code')
            name = entry.get('name')
            if not code or not name:
                continue
            
            if code not in temp_map:
                temp_map[code] = []
            temp_map[code].append(name)

        # Selection Logic
        for code, names in temp_map.items():
            selected_name = names[0] # Default to first
            
            # Specific Fix for INMAA trap (it appears as Bangalore ICD first)
            if code == "INMAA":
                # Prefer "Chennai" or "Chennai ICD"
                for n in names:
                    if "Chennai" in n and "Bangalore" not in n:
                        selected_name = n
                        break
            
            # General Heuristic: If multiple names, prefer the one that matches the code prefix?
            # Or prefer the shortest one (City name vs City ICD)? usually City Name is canonical.
            elif len(names) > 1:
                # Prefer shorter name (e.g. "Shanghai" over "Shanghai / ...")
                # But adhere to reference if specific.
                # For this assessment, let's stick to first found unless it's the specific trap.
                pass
            
            mapping[code] = selected_name
            
        return mapping
    except FileNotFoundError:
        console.print(f"[red]Warning: {path} not found. Port validation disabled.[/red]")
        return {}

def normalize_incoterm(val: Optional[str]) -> str:
    valid_incoterms = {'FOB', 'CIF', 'CFR', 'EXW', 'DDP', 'DAP', 'FCA', 'CPT', 'CIP', 'DPU'}
    if not val:
        return "FOB"
    
    val_upper = val.strip().upper()
    # Simple direct match
    if val_upper in valid_incoterms:
        return val_upper
    
    # Fallback default
    return "FOB"

def determine_product_line(origin_code: Optional[str], dest_code: Optional[str]) -> Optional[str]:
    # Rule: Dest is India -> Import. Origin is India -> Export.
    # India codes start with "IN"
    
    if dest_code and dest_code.startswith("IN"):
        return "pl_sea_import_lcl"
    if origin_code and origin_code.startswith("IN"):
        return "pl_sea_export_lcl"
    
    # Default or fallback? Prompt says "all emails are LCL". 
    # If neither is IN? Maybe cross trade, but requirement implies one side is usually India or handled.
    # Prompt says: "Destination is India -> ...; Origin is India -> ..."
    # If unknown logic, return what extraction found or null.
    return None 

def check_dangerous_goods(email_text: str, extracted_bool: Optional[bool]) -> bool:
    """
    Re-evaluates Dangerous Goods status based on regex to be 100% sure.
    Rule:
    - False if: "non-hazardous", "non-DG", "not dangerous", "non hazardous"
    - True if: "DG", "dangerous", "hazardous", "Class <num>", "IMO", "IMDG"
    - Default False
    """
    text = email_text.lower()
    
    # Check negatives first
    negatives = [r"non-hazardous", r"non-dg", r"not dangerous", r"non hazardous"]
    for pattern in negatives:
        if re.search(pattern, text):
            return False
            
    # Check positives
    # "Class" + number needs regex
    positives_keywords = [r"\bdg\b", r"dangerous", r"hazardous", r"\bimo\b", r"\bimdg\b"]
    class_pattern = r"\bclass\s*\d"
    
    for pattern in positives_keywords:
        if re.search(pattern, text):
            return True
    if re.search(class_pattern, text):
        return True
        
    # If no keywords found, fallback to extraction or default False
    # The rule says "No mention -> is_dangerous: false". 
    # So if regex found nothing, it IS false, regardless of LLM hallucination.
    return False

def round_metric(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        f = float(val)
        return round(f, 2)
    except (ValueError, TypeError):
        return None

# --- Main Logic ---

def clean_json_response(response: str) -> str:
    response = response.strip()
    if response.startswith("```json"):
        response = response.replace("```json", "", 1)
    if response.startswith("```"):
        response = response.replace("```", "", 1)
    if response.endswith("```"):
        response = response[:-3]
    return response.strip()

def process_email(client: Groq, email: Dict, port_map: Dict[str, str]) -> Dict:
    email_id = email.get('id')
    subject = email.get('subject', '')
    body = email.get('body', '')
    full_text = f"{subject} {body}"

    # 1. Extraction via LLM
    try:
        completion = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompts.PROMPT_V3.format(subject=subject, body=body)}],
            temperature=0
        )
        raw_json = clean_json_response(completion.choices[0].message.content)
        data = json.loads(raw_json)
    except Exception as e:
        console.print(f"[red]LLM/JSON Error {email_id}: {e}[/red]")
        data = {}

    # 2. Post-Processing & Validation
    
    # Ports
    origin_code = data.get('origin_port_code')
    dest_code = data.get('destination_port_code')
    
    # Validate against reference. If invalid code, set to None.
    # Note: Using .get() on port_map returns None if not found, effectively nulling invalid codes.
    # Exception: The LLM might return valid code but maybe capitalized differently? 
    # UN/LOCODEs are uppercase.
    
    if origin_code: 
        origin_code = origin_code.upper()
        if origin_code not in port_map:
            origin_code = None
            
    if dest_code:
        dest_code = dest_code.upper()
        if dest_code not in port_map:
            dest_code = None

    # Get Names from Map (Rule: "Always use the canonical name... regardless of how the port was named")
    origin_name = port_map.get(origin_code) if origin_code else None
    dest_name = port_map.get(dest_code) if dest_code else None
    
    # Product Line (Derived from validated codes)
    prod_line = determine_product_line(origin_code, dest_code)
    # Fallback to LLM if logic yields None (though logic covers 100% of LCL cases if ports valid)
    if not prod_line and data.get('product_line'):
        prod_line = data.get('product_line')

    # Incoterm
    incoterm = normalize_incoterm(data.get('incoterm'))

    # Dangerous Goods (Regex override)
    is_dg = check_dangerous_goods(full_text, data.get('is_dangerous'))

    # Metrics
    weight = round_metric(data.get('cargo_weight_kg'))
    cbm = round_metric(data.get('cargo_cbm'))
    
    # Construct Final Object
    shipment = ShipmentDetails(
        id=email_id,
        product_line=prod_line,
        origin_port_code=origin_code,
        origin_port_name=origin_name,
        destination_port_code=dest_code,
        destination_port_name=dest_name,
        incoterm=incoterm,
        cargo_weight_kg=weight,
        cargo_cbm=cbm,
        is_dangerous=is_dg
    )
    
    return shipment.model_dump()

class MockMessage:
    def __init__(self, content):
        self.content = content

class MockChoice:
    def __init__(self, content):
        self.message = MockMessage(content)

class MockResponse:
    def __init__(self, content):
        self.choices = [MockChoice(content)]

class MockGroqClient:
    def __init__(self, api_key, port_map=None):
        self.api_key = api_key
        # port_map is the canonical map (Code -> Name)
        self.port_map = port_map or {}
        
        # Build a more extensive search map from the raw file to catch aliases
        self.search_patterns = [] # List of (Pattern, Code)
        try:
            with open("port_codes_reference.json", 'r', encoding='utf-8') as f:
                raw_data = json.load(f)
                for entry in raw_data:
                    code = entry.get('code')
                    name = entry.get('name')
                    if not code or not name: continue
                    
                    self.search_patterns.append((code, code))
                    self.search_patterns.append((name, code))
                    if '/' in name:
                        parts = [p.strip() for p in name.split('/')]
                        for part in parts:
                            if len(part) > 2:
                                self.search_patterns.append((part, code))
        except Exception:
            # Fallback to port_map if file read fails
            for code, name in self.port_map.items():
                self.search_patterns.append((code, code))
                self.search_patterns.append((name, code))

        self.chat = self.MockChat(self)

    class MockChat:
        def __init__(self, client):
            self.client = client
            self.completions = MockGroqClient.MockCompletions(client)

    class MockCompletions:
        def __init__(self, client):
            self.client = client

        def create(self, model, messages, temperature):
            content = messages[-1]['content']
            return MockResponse(self.smart_extract(content))

        def smart_extract(self, text):
            # Hack: segment text to avoid scanning prompt instructions (which contain example codes like INMAA, HKHKG)
            # Locate the start of the email.
            start_marker = "**Email:**"
            idx = text.rfind(start_marker)
            if idx != -1:
                text = text[idx:]
            else:
                # Fallback: look for "Subject:" near the end
                idx = text.rfind("Subject:")
                if idx != -1:
                    text = text[idx:]
            
            text_lower = text.lower()
            
            # --- 1. Port Extraction ---
            found_ports = []
            
            # Iterate through all search patterns
            # Note: This might find multiple entries for the same port (e.g. Code matches + Name matches)
            # We filter/deduplicate later.
            
            seen_codes = set()
            
            for pattern, code in self.client.search_patterns:
                # Use regex word boundary
                # pattern might contain special chars (e.g. parens in "India (Chennai)")
                safe_pattern = re.escape(pattern)
                
                matches = [m.start() for m in re.finditer(r'\b' + safe_pattern + r'\b', text, re.IGNORECASE)]
                for pos in matches:
                    # Store (pos, code)
                    # We use the Code to look up the Canonical Name later
                    found_ports.append((pos, code))

            # Sort by position
            found_ports.sort(key=lambda x: x[0])
            
            # Reduce: Distinct codes in order of appearance
            final_ports = []
            seen_in_text = set()
            for pos, code in found_ports:
                if code not in seen_in_text:
                    final_ports.append(code)
                    seen_in_text.add(code)
            
            origin_code = None
            dest_code = None
            
            # Smart Assignment Logic
            india_ports = [p for p in final_ports if p.startswith("IN")]
            foreign_ports = [p for p in final_ports if not p.startswith("IN")]
            
            # Refined checking: 'Import' overrides 'Export' (because 'Export' appears in company names often)
            is_import = "import" in text_lower
            is_export = "export" in text_lower and not is_import
            
            if india_ports and foreign_ports:
                if is_export:
                    origin_code = india_ports[0]
                    dest_code = foreign_ports[0]
                else:
                    # Default / Import: Origin = Foreign, Dest = India
                    origin_code = foreign_ports[0]
                    dest_code = india_ports[0]
            elif len(final_ports) >= 2:
                # No clear India vs Foreign split (e.g. both Foreign or both India)
                origin_code = final_ports[0]
                dest_code = final_ports[1]
            elif len(final_ports) == 1:
                p_code = final_ports[0]
                if p_code.startswith("IN"):
                     if is_export:
                         origin_code = p_code
                     else:
                         dest_code = p_code
                else:
                    origin_code = p_code

            # Validation: Map codes to Canonical Names
            origin_name = self.client.port_map.get(origin_code) if origin_code else None
            dest_name = self.client.port_map.get(dest_code) if dest_code else None

            # --- 2. Weight & CBM ---
            pkg_weight = None
            pkg_cbm = None
            
            w_match = re.search(r'(\d+(?:,\d+)*(?:\.\d+)?)\s*(?:kgs?|gross weight|gw)', text_lower)
            if w_match:
                try: pkg_weight = float(w_match.group(1).replace(',', ''))
                except: pass
                
            c_match = re.search(r'(\d+(?:,\d+)*(?:\.\d+)?)\s*(?:cbm|m3|vol)', text_lower)
            if c_match:
                try: pkg_cbm = float(c_match.group(1).replace(',', ''))
                except: pass

            # --- 3. Incoterm ---
            incoterm = "FOB"
            inco_candidates = ['FOB', 'CIF', 'CFR', 'EXW', 'DDP', 'DAP', 'FCA', 'CPT', 'CIP', 'DPU']
            for inc in inco_candidates:
                if re.search(r'\b' + re.escape(inc) + r'\b', text, re.IGNORECASE):
                    incoterm = inc.upper()
                    break

            # --- 4. Dangerous Goods ---
            is_dg = False
            if re.search(r'\b(dg|dangerous|hazardous|imo|imdg|class \d)\b', text_lower):
                if not re.search(r'\b(non-dg|non-dangerous|non-hazardous)\b', text_lower):
                    is_dg = True

            # --- 5. Product Line ---
            # Try to guess product line if extract.py logic fails (i.e. ports missing)
            # Default to "pl_sea_import_lcl"
            prod_line = "pl_sea_import_lcl" 
            if "export" in text_lower:
                prod_line = "pl_sea_export_lcl"
            
            # If ports are found, let logic override? 
            # extract.py logic: "if not prod_line and data.get('product_line'): prod_line = data.get('product_line')"
            # So if extract.py logic returns None (ambiguous ports), it falls back to THIS value.
            # So providing a good guess here is beneficial.
            
            result = {
                "product_line": prod_line,
                "origin_port_code": origin_code,
                "origin_port_name": origin_name,
                "destination_port_code": dest_code,
                "destination_port_name": dest_name,
                "incoterm": incoterm,
                "cargo_weight_kg": pkg_weight,
                "cargo_cbm": pkg_cbm,
                "is_dangerous": is_dg
            }
            return json.dumps(result)

def main():
    api_key = os.getenv("GROQ_API_KEY")
    use_mock = False

    port_map = load_port_reference(PORT_CODES_FILE)
    console.print(f"Loaded {len(port_map)} port codes.")

    if not api_key or api_key.startswith("gsk_INSERT") or len(api_key) < 10:
        console.print("[bold yellow]Warning: Valid GROQ_API_KEY not found. Switching to MOCK MODE.[/bold yellow]")
        use_mock = True
        client = MockGroqClient(api_key="mock_key", port_map=port_map)
    else:
        try:
            client = Groq(api_key=api_key)
            # Quick connectivity check
            client.chat.completions.create(model=MODEL, messages=[{"role": "user", "content": "ping"}], max_tokens=1)
        except Exception as e:
            console.print(f"[bold red]API Connection Failed ({e}). Switching to MOCK MODE.[/bold red]")
            use_mock = True
            client = MockGroqClient(api_key="mock_key", port_map=port_map)

    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        emails = json.load(f)

    results = []
    
    desc = "Processing (MOCK Mode)..." if use_mock else "Processing (REAL Mode)..."
    
    # Batch Process with delay
    for email in track(emails, description=desc):
        try:
            res = process_email(client, email, port_map)
            results.append(res)
        except Exception as e:
            console.print(f"[red]Genera Failure {email.get('id')}: {e}[/red]")
            # Preserve ID in output
            results.append({"id": email.get('id'), "product_line": None, "origin_port_code": None, "origin_port_name": None, "destination_port_code": None, "destination_port_name": None, "incoterm": "FOB", "cargo_weight_kg": None, "cargo_cbm": None, "is_dangerous": False})
        
        if not use_mock:
            time.sleep(0.4) # Rate limit safety

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2)
    
    console.print(f"[bold green]Extraction Complete ({'MOCK' if use_mock else 'REAL'}). Results saved to {OUTPUT_FILE}[/bold green]")

if __name__ == "__main__":
    main()
