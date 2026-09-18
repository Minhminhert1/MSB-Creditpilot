# Project Guidance For Coding Agents

## Product Goal

This project is a browser-based AI Credit Proposal Copilot for Relationship Managers (RM). The long-term product should help an RM create a credit proposal case, upload supporting documents, extract and reuse business facts, collect missing RM inputs, generate proposal sections, validate consistency, and assemble a final proposal document.

## Non-Negotiable Document Assumption

Input documents are heterogeneous and structurally unstable. Never assume a stable:

- filename
- folder
- page
- Excel sheet
- cell
- layout
- GAS SOUTH-specific structure

The stable layer must be the business fact schema and proposal requirements, not the shape of one customer's files.

## Core Principle

ONE BUSINESS FACT
=
ONE CANONICAL INPUT
=
MANY OUTPUT BINDINGS

If a fact is known once, every section that needs it should read from the same canonical fact. Do not ask the RM to enter the same fact repeatedly for different proposal sections.

## Fact Handling Rules

- If information already exists in uploaded documents, prefill it.
- If information is missing, ask the RM.
- If information is uncertain, ask the RM to confirm.
- If information requires RM judgment, explicitly collect it from the RM.
- Never silently invent a missing business fact.

## Deterministic Code vs AI

Deterministic code owns:

- calculations
- totals
- mappings
- units
- validation
- state
- output bindings
- document rendering
- cross-section consistency

AI/LLM may be used later for:

- semantic document understanding
- document classification
- semantic fact extraction
- normalization
- missing-information reasoning
- evidence-grounded proposal narrative

AI output must remain grounded in explicit facts, evidence, and section instructions.

## Development Corpus

`Data/DEMO GAS SOUTH_PUBLIC DATA/` is the current local public development corpus. GAS SOUTH is a development case only. Do not build GAS SOUTH-specific extraction logic.

The corpus may contain supporting documents, public financial information, legal/business documents, and RM input templates. RM input templates are real possible workflow inputs, not merely static references.

## Section Development

Proposal sections must be developed one at a time. Existing Section A-D code and specifications are references/prototypes only until explicitly validated by the RM/product owner.

Do not assume existing A-D prototypes are complete or correct. Detailed section business rules may be revised later by the RM/product owner.

Do not invent banking-policy rules. If code, templates, sample data, and specifications conflict, flag the conflict instead of choosing a rule silently.

Preserve existing source documents and templates unless explicitly asked to change them.
