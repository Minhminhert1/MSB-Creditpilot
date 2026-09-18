"""Authoritative MB07 template binding map for Section A (Phase 11).

Defines row, cell, prefix, and checkbox mappings from Section A canonical keys
to physical locations in Table 1 of the verified authoritative MB07 template.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class BindingType(str, Enum):
    """How a canonical fact binds to the authoritative MB07 template."""

    SIMPLE_CELL = "SIMPLE_CELL"
    PREFIXED_TEXT = "PREFIXED_TEXT"
    FORM_CHECKBOX_GROUP = "FORM_CHECKBOX_GROUP"
    CONTENT_CONTROL_DROPDOWN = "CONTENT_CONTROL_DROPDOWN"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True)
class FieldBinding:
    """Binding specification for a single Section A canonical key.

    Attributes:
        canonical_key: Approved canonical field key.
        binding_type: Mechanism used to write the value into MB07.
        row_index: Zero-based row index in Section A Table 1 (0 to 29).
        cell_index: Physical cell index within the row (when applicable).
        prefix: Fixed label prefix inside the value run (e.g. 'CIF:', 'Ngày cấp:').
        suffix: Fixed suffix inside the value run (e.g. 'triệu đồng').
        checkbox_options: Mapping of allowed selection values to 0-based checkbox index within group.
        unresolved_reason: Explanation if binding is currently UNRESOLVED.
    """

    canonical_key: str
    binding_type: BindingType
    row_index: int | None = None
    cell_index: int | None = None
    prefix: str | None = None
    suffix: str | None = None
    checkbox_options: dict[str, int] = field(default_factory=dict)
    unresolved_reason: str | None = None


# Authoritative Section A Table 1 Bindings (Rows 0-29)
SECTION_A_BINDING_MAP: dict[str, FieldBinding] = {
    # Row 0: Legal name
    "company.legal_name": FieldBinding(
        canonical_key="company.legal_name",
        binding_type=BindingType.SIMPLE_CELL,
        row_index=0,
        cell_index=1,
    ),
    # Row 1: Short name
    "company.short_name": FieldBinding(
        canonical_key="company.short_name",
        binding_type=BindingType.SIMPLE_CELL,
        row_index=1,
        cell_index=1,
    ),
    # Row 2: Legal type (content control dropdown)
    "company.legal_type": FieldBinding(
        canonical_key="company.legal_type",
        binding_type=BindingType.CONTENT_CONTROL_DROPDOWN,
        row_index=2,
    ),
    # Row 3: Customer status (checkboxes) & CIF (prefixed text)
    "relationship.customer_status": FieldBinding(
        canonical_key="relationship.customer_status",
        binding_type=BindingType.FORM_CHECKBOX_GROUP,
        row_index=3,
        cell_index=1,
        checkbox_options={"KH_MOI": 0, "KH_HIEN_HUU": 1},
    ),
    "relationship.cif": FieldBinding(
        canonical_key="relationship.cif",
        binding_type=BindingType.PREFIXED_TEXT,
        row_index=3,
        cell_index=2,
        prefix="CIF:",
    ),
    # Row 4: Segment (checkboxes) & Segment other description (unresolved)
    "relationship.segment": FieldBinding(
        canonical_key="relationship.segment",
        binding_type=BindingType.FORM_CHECKBOX_GROUP,
        row_index=4,
        cell_index=1,
        checkbox_options={"LC": 0, "LMC": 1, "KHAC": 2},
    ),
    "relationship.segment_other_description": FieldBinding(
        canonical_key="relationship.segment_other_description",
        binding_type=BindingType.UNRESOLVED,
        unresolved_reason="MB07 has no confirmed free-text output slot for other segment description.",
    ),
    # Row 5: Group name
    "company.group_name": FieldBinding(
        canonical_key="company.group_name",
        binding_type=BindingType.SIMPLE_CELL,
        row_index=5,
        cell_index=1,
    ),
    # Row 6: Registered address
    "company.registered_address": FieldBinding(
        canonical_key="company.registered_address",
        binding_type=BindingType.SIMPLE_CELL,
        row_index=6,
        cell_index=1,
    ),
    # Row 7: Registration number, issue date, issue place
    "company.registration_no": FieldBinding(
        canonical_key="company.registration_no",
        binding_type=BindingType.SIMPLE_CELL,
        row_index=7,
        cell_index=1,
    ),
    "company.registration_issue_date": FieldBinding(
        canonical_key="company.registration_issue_date",
        binding_type=BindingType.PREFIXED_TEXT,
        row_index=7,
        cell_index=2,
        prefix="Ngày cấp:",
    ),
    "company.registration_issue_place": FieldBinding(
        canonical_key="company.registration_issue_place",
        binding_type=BindingType.PREFIXED_TEXT,
        row_index=7,
        cell_index=3,
        prefix="Nơi cấp:",
    ),
    # Row 8: Operation start date/year
    "company.operation_start_date_or_year": FieldBinding(
        canonical_key="company.operation_start_date_or_year",
        binding_type=BindingType.SIMPLE_CELL,
        row_index=8,
        cell_index=1,
    ),
    # Row 9: Legal representative name & title
    "company.legal_representative.name": FieldBinding(
        canonical_key="company.legal_representative.name",
        binding_type=BindingType.SIMPLE_CELL,
        row_index=9,
        cell_index=1,
    ),
    "company.legal_representative.title": FieldBinding(
        canonical_key="company.legal_representative.title",
        binding_type=BindingType.PREFIXED_TEXT,
        row_index=9,
        cell_index=2,
        prefix="Chức vụ:",
    ),
    # Row 10: Proposal representative name & title
    "proposal.credit_request_representative.name": FieldBinding(
        canonical_key="proposal.credit_request_representative.name",
        binding_type=BindingType.SIMPLE_CELL,
        row_index=10,
        cell_index=1,
    ),
    "proposal.credit_request_representative.title": FieldBinding(
        canonical_key="proposal.credit_request_representative.title",
        binding_type=BindingType.PREFIXED_TEXT,
        row_index=10,
        cell_index=2,
        prefix="Chức vụ:",
    ),
    # Row 11: Restricted credit subject (checkbox Có/Không across cell 1 and 2)
    "compliance.restricted_credit_subject": FieldBinding(
        canonical_key="compliance.restricted_credit_subject",
        binding_type=BindingType.FORM_CHECKBOX_GROUP,
        row_index=11,
        checkbox_options={"CO": 0, "KHONG": 1},
    ),
    # Row 12: ESG assessment required (checkbox Có/Không across cell 1 and 2)
    "compliance.esg_assessment_required": FieldBinding(
        canonical_key="compliance.esg_assessment_required",
        binding_type=BindingType.FORM_CHECKBOX_GROUP,
        row_index=12,
        checkbox_options={"BAT_BUOC_DANH_GIA": 0, "KHONG_BAT_BUOC_DANH_GIA": 1},
    ),
    # Row 13: Latest net revenue & revenue year
    "financial.latest_net_revenue": FieldBinding(
        canonical_key="financial.latest_net_revenue",
        binding_type=BindingType.PREFIXED_TEXT,
        row_index=13,
        cell_index=1,
        suffix="triệu đồng",
    ),
    "financial.latest_revenue_year": FieldBinding(
        canonical_key="financial.latest_revenue_year",
        binding_type=BindingType.UNRESOLVED,
        unresolved_reason="MB07 template has no explicit visible year slot in row 13.",
    ),
    # Row 15: Primary industry
    "business.primary_industry.code_level_5": FieldBinding(
        canonical_key="business.primary_industry.code_level_5",
        binding_type=BindingType.SIMPLE_CELL,
        row_index=15,
        cell_index=1,
    ),
    "business.primary_industry.name": FieldBinding(
        canonical_key="business.primary_industry.name",
        binding_type=BindingType.SIMPLE_CELL,
        row_index=15,
        cell_index=2,
    ),
    "business.primary_industry.revenue_share_pct": FieldBinding(
        canonical_key="business.primary_industry.revenue_share_pct",
        binding_type=BindingType.SIMPLE_CELL,
        row_index=15,
        cell_index=3,
        suffix="%",
    ),
    # Row 16: Main products
    "business.main_products": FieldBinding(
        canonical_key="business.main_products",
        binding_type=BindingType.SIMPLE_CELL,
        row_index=16,
        cell_index=2,
    ),
    # Row 17: Registered capital
    "capital.registered_capital": FieldBinding(
        canonical_key="capital.registered_capital",
        binding_type=BindingType.PREFIXED_TEXT,
        row_index=17,
        cell_index=1,
        prefix="Vốn đăng ký:",
        suffix="triệu đồng",
    ),
    # Row 18: Paid-in capital & as-of date
    "capital.paid_in_capital": FieldBinding(
        canonical_key="capital.paid_in_capital",
        binding_type=BindingType.PREFIXED_TEXT,
        row_index=18,
        cell_index=1,
        prefix="Vốn thực góp:",
        suffix="triệu đồng",
    ),
    "capital.paid_in_capital_as_of": FieldBinding(
        canonical_key="capital.paid_in_capital_as_of",
        binding_type=BindingType.SIMPLE_CELL,
        row_index=18,
        cell_index=3,
    ),
    # Row 19: Internal rating case ID
    "internal_rating.case_id": FieldBinding(
        canonical_key="internal_rating.case_id",
        binding_type=BindingType.PREFIXED_TEXT,
        row_index=19,
        cell_index=1,
        prefix="Mã ID của hồ sơ (theo hệ thống XHTD):",
    ),
    # Row 20: Internal rating grade & score
    "internal_rating.grade": FieldBinding(
        canonical_key="internal_rating.grade",
        binding_type=BindingType.PREFIXED_TEXT,
        row_index=20,
        cell_index=1,
        prefix="Hạng:",
    ),
    "internal_rating.score": FieldBinding(
        canonical_key="internal_rating.score",
        binding_type=BindingType.PREFIXED_TEXT,
        row_index=20,
        cell_index=2,
        prefix="Số điểm:",
    ),
    # Row 21 & 22: Credit relation at MSB & regulatory limit status
    "credit_relation.loan_outstanding_at_msb": FieldBinding(
        canonical_key="credit_relation.loan_outstanding_at_msb",
        binding_type=BindingType.PREFIXED_TEXT,
        row_index=21,
        cell_index=1,
        suffix="triệu đồng",
    ),
    "credit_relation.total_credit_exposure_at_msb": FieldBinding(
        canonical_key="credit_relation.total_credit_exposure_at_msb",
        binding_type=BindingType.PREFIXED_TEXT,
        row_index=22,
        cell_index=1,
        suffix="triệu đồng",
    ),
    "credit_relation.regulatory_limit_status": FieldBinding(
        canonical_key="credit_relation.regulatory_limit_status",
        binding_type=BindingType.FORM_CHECKBOX_GROUP,
        row_index=21,
        cell_index=2,
        checkbox_options={"VUOT_GIOI_HAN": 0, "TRONG_GIOI_HAN": 1},
    ),
    # Row 24: Existing limit
    "approval.existing_limit.total": FieldBinding(
        canonical_key="approval.existing_limit.total",
        binding_type=BindingType.SIMPLE_CELL,
        row_index=24,
        cell_index=2,
    ),
    "approval.existing_limit.unsecured": FieldBinding(
        canonical_key="approval.existing_limit.unsecured",
        binding_type=BindingType.SIMPLE_CELL,
        row_index=24,
        cell_index=3,
    ),
    # Row 25: Proposed limit
    "approval.proposed_limit.total": FieldBinding(
        canonical_key="approval.proposed_limit.total",
        binding_type=BindingType.SIMPLE_CELL,
        row_index=25,
        cell_index=2,
    ),
    "approval.proposed_limit.unsecured": FieldBinding(
        canonical_key="approval.proposed_limit.unsecured",
        binding_type=BindingType.SIMPLE_CELL,
        row_index=25,
        cell_index=3,
    ),
    # Row 26: Aggregate limit
    "approval.aggregate_limit.total": FieldBinding(
        canonical_key="approval.aggregate_limit.total",
        binding_type=BindingType.SIMPLE_CELL,
        row_index=26,
        cell_index=2,
        suffix="trđ",
    ),
    "approval.aggregate_limit.unsecured": FieldBinding(
        canonical_key="approval.aggregate_limit.unsecured",
        binding_type=BindingType.SIMPLE_CELL,
        row_index=26,
        cell_index=3,
        suffix="trđ",
    ),
    # Row 27: Authority (checkboxes)
    "approval.authority": FieldBinding(
        canonical_key="approval.authority",
        binding_type=BindingType.FORM_CHECKBOX_GROUP,
        row_index=27,
        cell_index=1,
        checkbox_options={"HĐTD&ĐT": 0, "HĐQT": 1, "HĐTDCC": 2},
    ),
    # Row 28: Previous approval period
    "approval.previous_approval_period": FieldBinding(
        canonical_key="approval.previous_approval_period",
        binding_type=BindingType.SIMPLE_CELL,
        row_index=28,
        cell_index=1,
    ),
    # Row 29: Request type (checkboxes)
    "proposal.request_type": FieldBinding(
        canonical_key="proposal.request_type",
        binding_type=BindingType.FORM_CHECKBOX_GROUP,
        row_index=29,
        cell_index=1,
        checkbox_options={"TAI_CAP": 0, "CAP_MOI": 1},
    ),
}
