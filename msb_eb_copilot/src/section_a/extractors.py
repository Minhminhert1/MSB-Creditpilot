"""Semantic fact extractors for Section A document sources."""

from decimal import Decimal
import re
from typing import Any

from .enums import CandidateStatus, FactValueType, SourceCategory
from .evidence import EvidenceCandidate, Provenance
from .normalizers import normalize_date, normalize_identifier, normalize_monetary_to_million_vnd


class EnterpriseRegistrationExtractor:
    """Extracts candidate legal profile facts from Enterprise Registration documents (GPKD)."""

    def extract(
        self,
        document_id: str,
        text_content: str,
        original_filename: str = "",
    ) -> list[EvidenceCandidate]:
        candidates: list[EvidenceCandidate] = []
        prov_base = Provenance(document_id=document_id, original_filename=original_filename)

        # 1. Company legal name
        name_match = re.search(
            r"(?:Tên công ty viết bằng tiếng Việt|Tên công ty|Tên doanh nghiệp):\s*([^\n\r]+)",
            text_content,
            re.IGNORECASE,
        )
        if name_match:
            legal_name = name_match.group(1).strip()
            candidates.append(
                EvidenceCandidate(
                    canonical_key="company.legal_name",
                    candidate_value=legal_name,
                    source_category=SourceCategory.DOCUMENT_EXTRACTED,
                    confidence=0.95,
                    snippet=name_match.group(0),
                    provenance=prov_base,
                )
            )

        # 2. Company short name
        short_match = re.search(
            r"Tên công ty viết tắt:\s*([^\n\r]+)",
            text_content,
            re.IGNORECASE,
        )
        if short_match:
            short_name = short_match.group(1).strip()
            if short_name and short_name != "-":
                candidates.append(
                    EvidenceCandidate(
                        canonical_key="company.short_name",
                        candidate_value=short_name,
                        source_category=SourceCategory.DOCUMENT_EXTRACTED,
                        confidence=0.90,
                        snippet=short_match.group(0),
                        provenance=prov_base,
                    )
                )

        # 3. Enterprise Registration No / Tax Code
        reg_match = re.search(
            r"(?:Mã số doanh nghiệp|Mã số thuế|Mã số DN):\s*([0-9\s.\-]+)",
            text_content,
            re.IGNORECASE,
        )
        if reg_match:
            reg_no = normalize_identifier(reg_match.group(1))
            candidates.append(
                EvidenceCandidate(
                    canonical_key="company.registration_no",
                    candidate_value=reg_no,
                    source_category=SourceCategory.DOCUMENT_EXTRACTED,
                    confidence=0.98,
                    snippet=reg_match.group(0),
                    provenance=prov_base,
                )
            )

        # 4. Issue Dates (first registration vs amendment)
        first_reg_match = re.search(
            r"Đăng ký lần đầu:\s*([^\n\r,]+)",
            text_content,
            re.IGNORECASE,
        )
        if first_reg_match:
            first_date = normalize_date(first_reg_match.group(1))
            candidates.append(
                EvidenceCandidate(
                    canonical_key="company.registration_issue_date",
                    candidate_value=first_date,
                    source_category=SourceCategory.DOCUMENT_EXTRACTED,
                    confidence=0.95,
                    evidence_label="first registration date",
                    snippet=first_reg_match.group(0),
                    provenance=prov_base,
                )
            )

        amend_match = re.search(
            r"Đăng ký thay đổi lần thứ\s*(\d+)[\s:,]*([^\n\r]+)",
            text_content,
            re.IGNORECASE,
        )
        if amend_match:
            amend_date = normalize_date(amend_match.group(2))
            amend_num = amend_match.group(1)
            candidates.append(
                EvidenceCandidate(
                    canonical_key="company.registration_issue_date",
                    candidate_value=amend_date,
                    source_category=SourceCategory.DOCUMENT_EXTRACTED,
                    confidence=0.95,
                    evidence_label=f"amendment #{amend_num} date",
                    snippet=amend_match.group(0),
                    provenance=prov_base,
                )
            )

        # 5. Issue Place
        place_match = re.search(
            r"(Phòng Đăng ký kinh doanh[^\n\r,]+|Sở Kế hoạch và Đầu tư[^\n\r,]+)",
            text_content,
            re.IGNORECASE,
        )
        if place_match:
            place = place_match.group(1).strip()
            candidates.append(
                EvidenceCandidate(
                    canonical_key="company.registration_issue_place",
                    candidate_value=place,
                    source_category=SourceCategory.DOCUMENT_EXTRACTED,
                    confidence=0.90,
                    snippet=place_match.group(0),
                    provenance=prov_base,
                )
            )

        # 6. Registered Address
        addr_match = re.search(
            r"Địa chỉ trụ sở chính:\s*([^\n\r]+(?:\n[^\n\r]+)?)",
            text_content,
            re.IGNORECASE,
        )
        if addr_match:
            address = " ".join(addr_match.group(1).split())
            # Clean trailing labels like Điện thoại / Email
            address = re.split(r"(?i)\s*(Điện thoại|Email|Fax):", address)[0].strip()
            candidates.append(
                EvidenceCandidate(
                    canonical_key="company.registered_address",
                    candidate_value=address,
                    source_category=SourceCategory.DOCUMENT_EXTRACTED,
                    confidence=0.90,
                    snippet=addr_match.group(0)[:100],
                    provenance=prov_base,
                )
            )

        # 7. Legal Representative Name & Title
        rep_section = re.search(
            r"Người đại diện theo pháp luật.*?(?:Họ và tên|Họ tên):\s*([^\n\r]+).*?Chức danh:\s*([^\n\r]+)",
            text_content,
            re.IGNORECASE | re.DOTALL,
        )
        if rep_section:
            rep_name = rep_section.group(1).strip().upper()
            rep_title = rep_section.group(2).strip()
            candidates.append(
                EvidenceCandidate(
                    canonical_key="company.legal_representative.name",
                    candidate_value=rep_name,
                    source_category=SourceCategory.DOCUMENT_EXTRACTED,
                    confidence=0.95,
                    snippet=rep_section.group(0)[:100],
                    provenance=prov_base,
                )
            )
            candidates.append(
                EvidenceCandidate(
                    canonical_key="company.legal_representative.title",
                    candidate_value=rep_title,
                    source_category=SourceCategory.DOCUMENT_EXTRACTED,
                    confidence=0.90,
                    snippet=rep_section.group(0)[:100],
                    provenance=prov_base,
                )
            )

        # 8. Registered Capital (supporting candidate; Charter is primary source)
        cap_match = re.search(
            r"Vốn điều lệ:\s*([0-9\s.,]+)\s*(?:đồng|VND)",
            text_content,
            re.IGNORECASE,
        )
        if cap_match:
            cap_val = normalize_monetary_to_million_vnd(cap_match.group(1), source_unit="VND")
            candidates.append(
                EvidenceCandidate(
                    canonical_key="capital.registered_capital",
                    candidate_value=cap_val,
                    source_category=SourceCategory.DOCUMENT_EXTRACTED,
                    confidence=0.85,
                    unit="triệu đồng",
                    evidence_label="registered capital from GPKD",
                    snippet=cap_match.group(0),
                    provenance=prov_base,
                )
            )

        # 9. Primary Industry (Level 5 Code and Name)
        ind_match = re.search(
            r"(?:Ngành, nghề kinh doanh chính|Ngành chính)[^\n\r:]*:.*?(?:Mã ngành:?\s*)?(\d{4,5})\s*[-–:]\s*([^\n\r]+)",
            text_content,
            re.IGNORECASE | re.DOTALL,
        )
        if ind_match:
            code, name = ind_match.groups()
            candidates.append(
                EvidenceCandidate(
                    canonical_key="business.primary_industry.code_level_5",
                    candidate_value=code.strip(),
                    source_category=SourceCategory.DOCUMENT_EXTRACTED,
                    confidence=0.90,
                    snippet=ind_match.group(0),
                    provenance=prov_base,
                )
            )
            candidates.append(
                EvidenceCandidate(
                    canonical_key="business.primary_industry.name",
                    candidate_value=name.strip(),
                    source_category=SourceCategory.DOCUMENT_EXTRACTED,
                    confidence=0.90,
                    snippet=ind_match.group(0),
                    provenance=prov_base,
                )
            )

        # Non-negotiable rule: Never infer company.operation_start_date_or_year!
        return candidates


class CompanyCharterExtractor:
    """Extracts candidate facts from Company Charter (Điều lệ)."""

    def extract(
        self,
        document_id: str,
        text_content: str,
        original_filename: str = "",
    ) -> list[EvidenceCandidate]:
        candidates: list[EvidenceCandidate] = []
        prov_base = Provenance(document_id=document_id, original_filename=original_filename)

        # 1. Group Name
        group_match = re.search(
            r"(?:thuộc Tập đoàn|là công ty con của|Tập đoàn|Tổng công ty):\s*([^\n\r,]+)",
            text_content,
            re.IGNORECASE,
        )
        if group_match:
            group_name = group_match.group(1).strip()
            candidates.append(
                EvidenceCandidate(
                    canonical_key="company.group_name",
                    candidate_value=group_name,
                    source_category=SourceCategory.DOCUMENT_EXTRACTED,
                    confidence=0.85,
                    evidence_label="group name from charter",
                    snippet=group_match.group(0),
                    provenance=prov_base,
                )
            )

        # 2. Registered Capital (Charter is primary source)
        cap_match = re.search(
            r"Vốn điều lệ của công ty là:\s*([0-9\s.,]+)\s*(?:đồng|VND)",
            text_content,
            re.IGNORECASE,
        )
        if cap_match:
            cap_val = normalize_monetary_to_million_vnd(cap_match.group(1), source_unit="VND")
            candidates.append(
                EvidenceCandidate(
                    canonical_key="capital.registered_capital",
                    candidate_value=cap_val,
                    source_category=SourceCategory.DOCUMENT_EXTRACTED,
                    confidence=0.95,
                    unit="triệu đồng",
                    evidence_label="charter registered capital (primary)",
                    snippet=cap_match.group(0),
                    provenance=prov_base,
                )
            )

        return candidates


class FinancialWorkbookMB09Extractor:
    """Extracts candidate facts from MB09 financial workbooks, supporting HN/RL conflict detection."""

    def extract_from_sheets_data(
        self,
        document_id: str,
        sheets_data: dict[str, list[dict[str, Any]]],
        original_filename: str = "",
    ) -> list[EvidenceCandidate]:
        candidates: list[EvidenceCandidate] = []
        prov_base = Provenance(document_id=document_id, original_filename=original_filename)

        # Track multiple revenue candidates for conflict preservation
        revenue_candidates: list[EvidenceCandidate] = []

        for sheet_name, rows in sheets_data.items():
            sheet_prov = Provenance(
                document_id=document_id,
                original_filename=original_filename,
                sheet_name=sheet_name,
            )
            is_hn = "hn" in sheet_name.lower() or "hợp nhất" in sheet_name.lower()
            is_rl = "rl" in sheet_name.lower() or "riêng" in sheet_name.lower()
            basis_label = "HN" if is_hn else ("RL" if is_rl else "General")

            for row in rows:
                label = str(row.get("label", "")).lower()
                amount_raw = row.get("amount")
                year_raw = row.get("year")

                # Revenue row
                if "doanh thu thuần" in label or "doanh thu bán hàng" in label:
                    if amount_raw is not None:
                        val = normalize_monetary_to_million_vnd(amount_raw, source_unit=row.get("unit", "triệu đồng"))
                        year = str(year_raw) if year_raw else "2025"
                        cand = EvidenceCandidate(
                            canonical_key="financial.latest_net_revenue",
                            candidate_value=val,
                            source_category=SourceCategory.DOCUMENT_EXTRACTED,
                            unit="triệu đồng",
                            confidence=0.90,
                            period_context=f"{basis_label} {year}",
                            evidence_label=f"Revenue {basis_label}",
                            provenance=sheet_prov,
                        )
                        revenue_candidates.append(cand)

                        # Revenue year
                        candidates.append(
                            EvidenceCandidate(
                                canonical_key="financial.latest_revenue_year",
                                candidate_value=year,
                                source_category=SourceCategory.DOCUMENT_EXTRACTED,
                                confidence=0.95,
                                provenance=sheet_prov,
                            )
                        )

                # Paid-in Capital row
                if "vốn góp của chủ sở hữu" in label or "vốn thực góp" in label:
                    if amount_raw is not None:
                        paid_in_val = normalize_monetary_to_million_vnd(
                            amount_raw, source_unit=row.get("unit", "triệu đồng")
                        )
                        as_of_date = normalize_date(str(row.get("as_of", "2025-12-31")))
                        candidates.append(
                            EvidenceCandidate(
                                canonical_key="capital.paid_in_capital",
                                candidate_value=paid_in_val,
                                source_category=SourceCategory.DOCUMENT_EXTRACTED,
                                unit="triệu đồng",
                                confidence=0.90,
                                provenance=sheet_prov,
                            )
                        )
                        candidates.append(
                            EvidenceCandidate(
                                canonical_key="capital.paid_in_capital_as_of",
                                candidate_value=as_of_date,
                                source_category=SourceCategory.DOCUMENT_EXTRACTED,
                                confidence=0.90,
                                provenance=sheet_prov,
                            )
                        )

        # Conflict Preservation: If both HN and RL revenue exist with differing values, mark as CONFLICTING
        if len(revenue_candidates) > 1:
            first_val = revenue_candidates[0].candidate_value
            has_difference = any(c.candidate_value != first_val for c in revenue_candidates)
            if has_difference:
                # Mark all differing candidates as CONFLICTING
                for c in revenue_candidates:
                    candidates.append(
                        EvidenceCandidate(
                            canonical_key=c.canonical_key,
                            candidate_value=c.candidate_value,
                            source_category=c.source_category,
                            confidence=c.confidence,
                            unit=c.unit,
                            status=CandidateStatus.CONFLICTING,
                            period_context=c.period_context,
                            evidence_label=c.evidence_label,
                            provenance=c.provenance,
                        )
                    )
            else:
                candidates.extend(revenue_candidates)
        elif revenue_candidates:
            candidates.extend(revenue_candidates)

        return candidates
