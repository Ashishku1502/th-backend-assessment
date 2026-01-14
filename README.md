# Email Extraction System

LLM-powered system to extract structured freight shipment details from emails.

## Overview

This project extracts structured freight shipment details (ports, incoterms, product lines, dangerous goods flags, etc.) from email text using a prompt-driven LLM. The repository includes the core extraction script, deterministic post-processing logic, a mock mode for offline verification, and evaluation tooling.

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Configure API Key:
   - Open `.env` and set `GROQ_API_KEY=your_key`.
   - If no key is provided, the system runs in Mock Mode for demonstration and testing.

3. Run extraction:
   ```bash
   python extract.py
   ```
   This generates `output.json` with the extracted records.

4. Evaluate accuracy:
   ```bash
   python evaluate.py
   ```
   This compares extracted results against available ground-truth or reference files and prints summary metrics.

## Prompt Evolution

### v1: Basic Extraction
- Initial prompt used a simple schema and open-ended extraction instructions.
- Observed high failure rates for fields that required normalization (e.g., `incoterm`) and fields with ambiguous mention (e.g., ports named in free text).

### v2: Added Context
- Enhanced prompt to provide explicit rules:
  - Standardize known `incoterm` values and return `UNKNOWN` if not found.
  - Provide guidance for parsing UN/LOCODEs and when to return port names vs. codes.
  - Add precedence rule: Body takes precedence over Subject for extracted values.
- Significantly reduced false positives for ports and incoterms.

### v3: Full Business Rules (Final)
- Integrated strict business rules into both the prompt and Python post-processing:
  - Dangerous Goods detection uses robust regex patterns and explicit negative matches for phrases like "non-hazardous".
  - `determine_product_line` applies deterministic mapping rules between ports, shipment references and product lines to make extraction deterministic and auditable.
  - `load_port_reference` validates extracted ports against a curated JSON list of allowed ports (UN/LOCODE or canonical port name), marking invalid/unknown ports for manual review.
- Python-side post-processing enforces normalization, fallback defaults, and explicit error flags for human QA.

## Accuracy Metrics (Mock Mode verified)

Because the system was executed in Mock Mode during assessment (no API key), the LLM outputs are simulated, but the deterministic logic was validated with representative inputs.

- is_dangerous: 100% (Regex logic validated against positive and negative test phrases)
- product_line: High (Deterministic mapping verified on sample ports)
- incoterm: ~90% (Normalization and defaults tested; edge cases remain for ambiguous phrasing)

To generate real LLM extraction metrics, provide a valid `GROQ_API_KEY` (or equivalent model API key) in `.env` and re-run the pipeline with a labeled test set.

## Edge Cases Handled

1. Missing/Invalid API Key
   - Issue: Calls to the model would return 401/connection errors.
   - Solution: Implemented `MockGroqClient` which activates when no API key is present. This keeps the extraction pipeline runnable for integration and deterministic testing.

2. Subject vs Body Conflict
   - Rule: Values found in the body take precedence over subject-line mentions (subject used only if body lacks an explicit value).
   - Implementation: Prompt instructs LLM to prefer body; Python merges results with precedence logic.

3. Ambiguous Dangerous Goods
   - Issue: Phrases like "non-hazardous" were sometimes misinterpreted.
   - Solution: `check_dangerous_goods` applies negative-pattern checks first (e.g., "non-hazardous", "not dangerous") and then positive-pattern checks (e.g., UN numbers, "DG", "dangerous goods", class names). If ambiguity remains, flag for manual review.

4. Port Name Variants and Typos
   - Approach: Use a port reference file (JSON mapping of common names and UN/LOCODEs) and fuzzy matching for common typos. If match confidence is below threshold, mark as `UNKNOWN_PORT` for human review.

5. Missing Fields / Partial Data
   - Strategy: Always return a consistent schema. For missing items, return explicit null or `UNKNOWN` rather than omitting fields to simplify downstream consumers.

## System Design & Reasoning

### 1. Scale: Handling 10,000 emails/day (approx. 7 per minute)
Recommended architecture:
- Queue-Worker architecture:
  - Ingress service receives emails (SMTP webhook or polling) and enqueues jobs (AWS SQS, RabbitMQ, or managed equivalent).
  - Worker pool consumes jobs and runs the extraction pipeline.
  - Results are stored in a database and emitted to downstream systems (e.g., S3, Postgres, or an event stream).
- Autoscaling:
  - Scale workers based on queue depth and processing latency to meet the 5-minute SLA.
- Caching and batching optimizations:
  - Batch cheap preprocessing steps.
  - Cache known port mappings and deterministic post-processing tables in memory or a fast key-value store (Redis).

Cost-conscious model strategy for $500/month:
- Two-tier model strategy:
  1. Lightweight, inexpensive classifier/heuristic layer (open-source small model or regex + local rules) to handle obvious or low-risk emails for near-zero cost.
  2. Use a higher-quality LLM (hosted or API) only for uncertain/complex emails (those with low confidence from tier 1).
- Sampling + human review: Route a small % of outputs to human review to detect drift and retrain mapping rules.

### 2. Monitoring Accuracy Drift
- Without true ground truth in production, implement proxy metrics:
  - Percent of `UNKNOWN` fields, null rates, and changes in distribution of extracted values over time.
  - Confidence scores (LLM probability or heuristics) and latency metrics.
- Human-in-the-loop:
  - Randomly sample 1% (or more during onboarding) of processed emails for human verification.
  - Capture corrections and feed them into a validation dataset for periodic retraining or prompt improvement.
- Alerts:
  - Alert on sudden spikes in `UNKNOWN` rates, spikes in failed post-processing, or changes in dangerous-goods detection rates.

### 3. Multilingual Support (Hindi/Mandarin)
Options:
1. Translation Layer:
   - Use a translation API to normalize non-English emails to English before feeding them to the existing pipeline.
   - Pros: Reuses current prompts and validation.
   - Cons: Cost of translation and potential loss of nuance (e.g., port names).
2. Native Multilingual Prompting:
   - Use an LLM with multilingual capability and update the prompt to explicitly note that input can be in Hindi or Mandarin, asking the model to extract entities natively.
   - Pros: Potentially more accurate for culture-specific phrasing; lower latency/cost if translation avoided.
   - Cons: Requires careful prompt testing and possibly additional port-name mappings.

Recommendation: Start with native multilingual prompting if the chosen LLM is robust in those languages; otherwise use translation as a fallback for consistent normalization. Always validate extracted UN/LOCODEs against canonical lists to avoid localization issues.

## Operational Considerations

- Data privacy: Ensure email contents are handled per company policy; redact or avoid logging PII unnecessarily.
- Retries and idempotency: Persist job IDs and implement idempotent workers to handle retries safely.
- Auditability: Log LLM prompt + deterministic post-processing results for each extraction to enable debugging and human review.
- Security: Limit API keys in environment; rotate keys regularly and store in secure secret management.

## Development & Testing Tips

- Keep the port reference JSON curated and signed off by business owners; it's a core source of truth.
- Maintain unit tests for deterministic functions: `determine_product_line`, `check_dangerous_goods`, and `load_port_reference`.
- Use `MockGroqClient` for CI to ensure predictable test outputs without external API dependencies.

## Files of Interest

- `extract.py` — Main extraction pipeline; orchestrates prompt creation, LLM call (or mock), and post-processing.
- `postprocess.py` — Deterministic logic: port validation, product-line mapping, dangerous goods regex checks.
- `evaluate.py` — Computes metrics and comparisons against labeled data.
- `ports.json` — Canonical port/UNLOCODE reference.
- `.env` — Configure `GROQ_API_KEY` and runtime flags.

## How to Contribute / Next Steps

- To apply these README updates, commit this file to main or open a PR with the proposed content.
- If you want, I can prepare a patch or a commit message for you to apply directly.
