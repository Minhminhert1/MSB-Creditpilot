# MSB MB07 Template Fidelity Contract

## 1. Core Principle

The authoritative MSB MB07 credit proposal template (`MB07 Tờ trình đề xuất cấp tín dụng (ĐVKD) - thực hiện rà soát - tái cấp.docx`) is a standardized, compliance-governed banking document.

**Fundamental Rule:**
> **DO NOT rebuild the MB07 document from scratch.**
>
> The system must start with the authoritative MB07 template, create an in-memory or working copy, locate explicitly allowed data anchors, mutate ONLY those specific target cells/paragraphs, and preserve 100% of all other structural, typographic, XML, and layout properties.

---

## 2. Invariable Template Invariants (25 Mandatory Constraints)

The following 25 properties MUST remain unchanged between the input template and the generated output:

1. **Sections**: Total section count and section boundaries (`w:sectPr`) must be preserved.
2. **Section Ordering**: Logical flow of sections (Title, Header metadata, Section A through E, Approvals) must not be rearranged.
3. **Page Size**: Exact paper dimensions (A4: 11906 x 16838 dxa / 210mm x 297mm) must not change.
4. **Margins**: Exact page margins (top, bottom, left, right, header, footer margins) must remain identical to the authoritative template.
5. **Headers**: Existing header definitions (`header1.xml`, `header2.xml`, etc.) and bindings must be preserved.
6. **Footers**: Existing footer definitions (`footer1.xml`, `footer2.xml`, etc.), page numbers, and confidentiality notices must be preserved.
7. **Table Count**: Total table count must remain identical unless an explicit repeatable row expansion or approved section policy is executed.
8. **Table Order**: Exact ordinal sequence and document order of all tables must be preserved.
9. **Column Widths**: Base column definitions (`w:gridCol`, `w:tcW`) must not be arbitrarily squashed, expanded, or recalculated.
10. **Row Heights**: Fixed row heights (`w:trHeight`) and header properties (`w:tblHeader`, `w:cantSplit`) must be preserved.
11. **Cell Merges**: Horizontal merges (`w:gridSpan`, `w:hMerge`) and vertical merges (`w:vMerge`) must remain intact.
12. **Cell Borders**: Individual cell border properties (`w:tcBorders`, color, size, space, style) must remain unchanged.
13. **Cell Shading**: Official MSB background shading (`w:shd`, fill hex colors, patterns) must not be stripped or replaced unless explicitly requested by RM.
14. **Paragraph Styles**: Paragraph style IDs (`w:pStyle`, Normal, Heading 1-4, Table Body, Table Header) must be preserved.
15. **Run Styles**: Character style references (`w:rStyle`) and properties must not be discarded.
16. **Fonts**: Primary font family (`Times New Roman` / `Arial` as defined in `w:rFonts` `w:ascii`, `w:hAnsi`, `w:cs`) must remain consistent.
17. **Font Size**: Font size (`w:sz`, `w:szCs` e.g., 10pt = 20 half-points, 11pt = 22 half-points, 12pt = 24 half-points) must be preserved.
18. **Bold / Italic / Underline**: Formatting flags (`w:b`, `w:i`, `w:u`) on boilerplate labels and headers must remain untouched.
19. **Alignment**: Horizontal paragraph alignment (`w:jc` LEFT, CENTER, RIGHT, BOTH) and vertical cell alignment (`w:vAlign` TOP, CENTER, BOTTOM) must not change.
20. **Numbering**: Numbering definitions (`w:numPr`, `w:numId`, `w:ilvl`) and bullet structures must not be corrupted.
21. **Page Breaks**: Explicit page breaks (`w:br w:type="page"`, `w:lastRenderedPageBreak`) and `w:pageBreakBefore` settings must be respected.
22. **Signature Blocks**: Officer/Manager review blocks, stamp zones, and signatory tables must retain original structure.
23. **Existing Labels**: Fixed text labels (e.g., "1. Thông tin chung về khách hàng", "Mã số thuế:", "Vốn điều lệ:") must never be overwritten or deleted.
24. **Existing Boilerplate Text**: Standard bank policy text, disclaimer clauses, and instruction titles must remain intact.
25. **Word Field Codes**: Form field controls (`w:fldSimple`, `w:instrText`, `FORMCHECKBOX`, `w:sdt` content controls) must be updated in-place or preserved rather than destroyed.

---

## 3. Allowed Mutation Scope (Allowlist)

Only the following locations are permitted to be mutated:

| Scope | Target Description | Permitted Action | Forbidden Action |
|---|---|---|---|
| **Header Metadata** | Proposal No, Date, RM / Support / Manager contact info | Mutate value text within specific value run/cell | Deleting header table or labels |
| **Section A (Table 1)** | Customer identity, legal rep, business lines, segment | Mutate value cells, toggle checkboxes, select dropdowns | Deleting rows, changing borders, recreating table |
| **Section B (Table 15)** | Proposed credit limits, products, tenors, pricing | Fill table rows with structured credit facilities | Clearing table headers, altering grid columns |
| **Section C (Tables 17, 18, 20)** | Shareholders, parent/subsidiaries, key management | Populate data rows into designated table cells | Deleting whole table or Section C headers |
| **Section D (Table 31)** | Financial statements (BS, IS, Cashflow, Ratios) | Populate numbers into pre-formatted financial cells | Rebuilding financial matrix from scratch |
| **Section E (Tables 32, 34)** | CIC credit relations at MSB & other banks | Populate institution rows into pre-formatted CIC tables | Reconstructing CIC layout |
| **Narrative Anchors** | Business analysis, supply chain, credit evaluation | Inject verified text into designated narrative paragraphs | Overwriting preceding section headers or notes |

---

## 4. Mutation Execution Protocol

Every write operation must adhere to the 5-step safety lifecycle:

```
[1. Resolve Semantic Anchor]
        │
        ▼
[2. Assert Template Structure] ── (Mismatch) ──► Fail Closed with TemplateStructureError
        │
        ▼
[3. Snapshot Target Formatting] (Font, Size, Alignment, Color, Bold)
        │
        ▼
[4. Apply Safe In-Place Mutation] (Preserve XML node, mutate only text run)
        │
        ▼
[5. Verify Post-Mutation Invariants] (Assert table count, styles, borders unchanged)
```
