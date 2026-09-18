# MSB Credit Proposal Copilot

## Problem

Enterprise Banking Relationship Managers (RM) currently have to:

- read multiple heterogeneous credit and customer documents (legal dossiers, financial statements, loan applications, CIC reports)
- manually re-enter customer and financial information across disparate systems and templates
- analyze multi-year financial statements and cross-check balance sheet balancing
- calculate complex banking credit metrics (DIO, DSO, DPO, CCC, working capital demands, turnover)
- prepare MB09 / RORWA-related risk-adjusted return inputs
- draft narrative and structured MB07 credit proposal content under tight deadlines

*(No unsupported impact numbers or unverified time-savings figures are assumed).*

## Target User

Enterprise Banking Relationship Manager (RM) and Credit Approvers at Vietnam Maritime Commercial Joint Stock Bank (MSB).

## Product Goal

Transform raw, heterogeneous customer documents into an executive, audit-ready credit proposal:

Customer Documents -> Verified Business Facts -> Deterministic Credit Analysis -> MB07 Proposal (.docx)

## User Journey

1. Open/create case: RM selects an existing customer case (e.g. PSD, GAS SOUTH, THEP TAY DO) or creates a new case with core registration info.
2. Upload legal documents: RM uploads customer legal dossier (Giấy phép ĐKKD / Điều lệ / Quyết định bổ nhiệm) as PDF (digital or scanned).
3. GreenNode extracts legal facts: GreenNode Document AI extracts structured legal facts strictly paired with page citation and verbatim evidence quotes.
4. RM reviews evidence: RM inspects extracted legal fields side-by-side with original document evidence snippets and confidence audit status.
5. Confirm: RM resolves conflicts if any and confirms; verified facts are committed to the canonical customer profile (section_a).
6. Upload BCTC: RM uploads 3-year audited Financial Statements (BCTC) as PDF.
7. GreenNode extracts financial SOURCE_FACT: GreenNode extracts multi-year balance sheet, income statement, and cash flow source facts with page markers and exact textual quotes.
8. RM reviews: RM reviews previewed financial facts, balance sheet sanity checks, and conflict disclosures.
9. Confirm: RM confirms financial facts into canonical storage (section_d); financial lineage is locked.
10. Python calculates financial metrics: Deterministic Python engine computes all ratios, working capital turnover, cash cycle, and limit demands.
11. Existing proposal engines process A-E: Section A-E builders assemble customer governance, credit request limits, business model, financial analysis, and banking relationship data.
12. Generate MB07: System generates a 100% clean, fully formatted, highlight-free, bank-standard MB07 proposal Word document ready for committee review.

## Sections

- Section A (Customer / Legal):
  - Status: Implemented & Verified.
  - Company identity, tax code, charter capital, legal representative, governance, founding date, business activities. Evidence-backed GreenNode extraction with RM confirm pipeline.
- Section B (Credit Request & Debt Service):
  - Status: Implemented & Verified.
  - Credit facility limits (short-term loan, medium/long-term loan, LC, guarantee), financing purpose, security/collateral, cashflow commitments, and EWT conditions.
- Section C (Business & Management Assessment):
  - Status: Implemented & Verified.
  - Business model archetype, shareholder structure, key management personnel, products/services, warehouse/factory infrastructure, supplier and customer networks, and RM management assessment.
- Section D (Financial Analysis / MB09 / RORWA):
  - Status: Implemented & Verified.
  - 3-year financial statements, canonical financial lineage, deterministic Python ratio calculations, working capital demand, TORWA/RORWA computation, and RM financial review.
- Section E (CIC & Banking Relationship):
  - Status: Implemented & Verified.
  - Multi-bank credit relations, historical debt groups, collateral breakdown, CASA average balance, and RM credit assessment.
- Planned for Future Phases:
  - Autonomous CIC PDF extraction agent.
  - Autonomous Business intelligence agent.
  - Multi-agent collaboration runtime for end-to-end parallel ingestion.

## AI Responsibility

GreenNode:
- READ
- UNDERSTAND
- EXTRACT
- WRITE
(Semantic document understanding, OCR transcription for scanned documents, verbatim evidence-backed fact extraction, grounded narrative drafting strictly within provided facts).

Python:
- VALIDATE
- NORMALIZE
- CALCULATE
- APPLY RULES
- RENDER
(Data schema validation, type checking, conflict detection, currency/unit normalization, deterministic financial formulas, working capital turnover, banking policy rule verification, Word document template rendering and formatting).

## Human In The Loop

Relationship Manager owns:
- conflict resolution: When extracted values differ from existing data, RM explicitly selects use_extracted or keep_existing.
- credit request: RM defines proposed facility structures, credit limits, and sub-limits.
- facility limits: RM determines operational bounds and covenants.
- final review: RM performs the final comprehensive review and approves the generated MB07 proposal before submission.

## Trust Model

- NO EVIDENCE -> NO FACT: An AI-extracted fact is invalid unless backed by page number citation and exact verbatim excerpt.
- browser is not authoritative: Web client only transmits intent; all validations, mappings, and state transitions are executed server-side.
- financial calculations are deterministic: Zero LLM hallucination in financial math. All totals, margins, ratios, and demands are computed by pure Python code.
- AI never makes approval decisions: AI acts exclusively as an analytical copilot; credit approval decisions belong strictly to MSB credit authorities.

## GreenNode Architecture

- Reasoning / Text Model: z-ai/glm-5.2-hackathon via GreenNode MaaS (complex semantic extraction, evidence grounding, structured JSON parsing).
- Vision / OCR Model: qwen/qwen3.6-flash via GreenNode MaaS (high-fidelity visual OCR for scanned PDFs rendered at 150 DPI via pypdfium2).
- Runtime Target: GreenNode AgentBase Custom Agent Runtime (containerized HTTP service exposing /health and REST endpoints).

## Deployment Target

Local Workspace -> Docker Container -> GreenNode AgentBase Container Registry -> Custom Agent Runtime -> Public Endpoint
