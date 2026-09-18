"""Authoritative code-level Section A field registry.

The definitions in this module mirror ``docs/section_A/SECTION_A_FIELD_SPEC.md``.
They intentionally contain no customer values, document coordinates, extraction
rules, UI implementation, rendering bindings, or banking calculations.
"""

from dataclasses import dataclass
from typing import Mapping

from .enums import (
    ConditionalRequirementKind,
    DataBehavior,
    FactValueType,
    RequirementMode,
    RMConfirmationMode,
)


MILLION_VND = "triệu đồng"


@dataclass(frozen=True)
class ConditionalRequirement:
    """Declarative metadata for conditional requiredness.

    This is not a validation engine. It records approved dependency metadata so
    future readiness/validation code can implement only product-approved rules.
    """

    kind: ConditionalRequirementKind
    field_key: str | None = None
    equals: str | None = None
    condition_code: str | None = None
    description: str = ""


@dataclass(frozen=True)
class SectionAFieldDefinition:
    """Immutable metadata for one canonical Section A business fact."""

    canonical_key: str
    label: str
    behaviors: tuple[DataBehavior, ...]
    value_type: FactValueType
    unit: str | None = None
    allowed_values: tuple[str, ...] = ()
    requirement_mode: RequirementMode = RequirementMode.OPTIONAL
    conditional_requiredness: ConditionalRequirement | None = None
    rm_confirmation_mode: RMConfirmationMode = RMConfirmationMode.NONE
    cross_section_linked: bool = False
    notes: str = ""

    @property
    def is_unconditionally_required(self) -> bool:
        return self.requirement_mode == RequirementMode.REQUIRED


def _field(
    canonical_key: str,
    label: str,
    behaviors: tuple[DataBehavior, ...],
    value_type: FactValueType,
    *,
    unit: str | None = None,
    allowed_values: tuple[str, ...] = (),
    requirement_mode: RequirementMode = RequirementMode.OPTIONAL,
    conditional_requiredness: ConditionalRequirement | None = None,
    rm_confirmation_mode: RMConfirmationMode = RMConfirmationMode.NONE,
    notes: str = "",
) -> SectionAFieldDefinition:
    return SectionAFieldDefinition(
        canonical_key=canonical_key,
        label=label,
        behaviors=behaviors,
        value_type=value_type,
        unit=unit,
        allowed_values=allowed_values,
        requirement_mode=requirement_mode,
        conditional_requiredness=conditional_requiredness,
        rm_confirmation_mode=rm_confirmation_mode,
        cross_section_linked=DataBehavior.CROSS_SECTION_LINKED in behaviors,
        notes=notes,
    )


DOCUMENT_EXTRACTED = (DataBehavior.DOCUMENT_EXTRACTED,)
DOCUMENT_EXTRACTED_RM_CONFIRMED = (
    DataBehavior.DOCUMENT_EXTRACTED,
    DataBehavior.RM_CONFIRMED,
)
RM_PROVIDED = (DataBehavior.RM_PROVIDED,)
RM_SELECTED = (DataBehavior.RM_SELECTED,)
CROSS_SECTION_LINKED = (DataBehavior.CROSS_SECTION_LINKED,)


SECTION_A_FIELDS: tuple[SectionAFieldDefinition, ...] = (
    _field("company.legal_name", "Tên khách hàng doanh nghiệp", DOCUMENT_EXTRACTED, FactValueType.TEXT, requirement_mode=RequirementMode.REQUIRED),
    _field("company.short_name", "Viết tắt", DOCUMENT_EXTRACTED, FactValueType.TEXT, notes="Optional if unavailable; allow RM input fallback without inventing an abbreviation."),
    _field("company.legal_type", "Loại hình doanh nghiệp", DOCUMENT_EXTRACTED, FactValueType.TEXT, requirement_mode=RequirementMode.REQUIRED_WHEN_EVIDENCE_AVAILABLE, notes="Required when found in legal registration evidence."),
    _field("relationship.customer_status", "Tình trạng khách hàng", RM_SELECTED, FactValueType.SELECTION, allowed_values=("KH_MOI", "KH_HIEN_HUU"), requirement_mode=RequirementMode.REQUIRED),
    _field(
        "relationship.cif",
        "CIF",
        RM_PROVIDED,
        FactValueType.TEXT,
        requirement_mode=RequirementMode.CONDITIONAL,
        conditional_requiredness=ConditionalRequirement(kind=ConditionalRequirementKind.FIELD_EQUALS, field_key="relationship.customer_status", equals="KH_HIEN_HUU", description="Required only for existing customers."),
    ),
    _field("relationship.segment", "Đối tượng khách hàng", RM_SELECTED, FactValueType.SELECTION, allowed_values=("LC", "LMC", "KHAC"), requirement_mode=RequirementMode.REQUIRED),
    _field(
        "relationship.segment_other_description",
        "Đối tượng khách hàng - mô tả khác",
        RM_PROVIDED,
        FactValueType.TEXT,
        requirement_mode=RequirementMode.CONDITIONAL,
        conditional_requiredness=ConditionalRequirement(kind=ConditionalRequirementKind.FIELD_EQUALS, field_key="relationship.segment", equals="KHAC", description="Required only when customer segment is KHAC."),
    ),
    _field("company.group_name", "Thuộc nhóm, tập đoàn", DOCUMENT_EXTRACTED_RM_CONFIRMED, FactValueType.TEXT, requirement_mode=RequirementMode.REQUIRED, rm_confirmation_mode=RMConfirmationMode.REQUIRED, notes="May be suggested from charter evidence; RM must confirm, edit, replace, or enter manually."),
    _field("company.registered_address", "Địa chỉ trụ sở chính", DOCUMENT_EXTRACTED, FactValueType.TEXT, requirement_mode=RequirementMode.REQUIRED_WHEN_EVIDENCE_AVAILABLE, notes="Required when available from legal registration evidence."),
    _field("company.registration_no", "Số đăng ký kinh doanh", DOCUMENT_EXTRACTED, FactValueType.TEXT_IDENTIFIER, requirement_mode=RequirementMode.REQUIRED, notes="Preserve as a string identifier so leading zeros are not lost."),
    _field("company.registration_issue_date", "Ngày cấp", DOCUMENT_EXTRACTED, FactValueType.DATE, requirement_mode=RequirementMode.REQUIRED_WHEN_EVIDENCE_AVAILABLE, notes="Required when available; preserve distinct labeled candidates until a business rule chooses date basis."),
    _field("company.registration_issue_place", "Nơi cấp", DOCUMENT_EXTRACTED, FactValueType.TEXT, requirement_mode=RequirementMode.REQUIRED_WHEN_EVIDENCE_AVAILABLE, notes="Required when available."),
    _field("company.operation_start_date_or_year", "Thời gian bắt đầu hoạt động", DOCUMENT_EXTRACTED_RM_CONFIRMED, FactValueType.DATE_OR_YEAR_OR_TEXT, requirement_mode=RequirementMode.REQUIRED, rm_confirmation_mode=RMConfirmationMode.WHEN_EVIDENCE_NOT_EXPLICIT, notes="Business revenue-start time; do not infer automatically from registration, establishment, or incorporation date."),
    _field("company.legal_representative.name", "Người đại diện theo pháp luật - họ tên", DOCUMENT_EXTRACTED, FactValueType.TEXT, requirement_mode=RequirementMode.REQUIRED, notes="Conflicting sources require RM confirmation."),
    _field("company.legal_representative.title", "Người đại diện theo pháp luật - chức vụ", DOCUMENT_EXTRACTED, FactValueType.TEXT, requirement_mode=RequirementMode.REQUIRED, notes="Conflicting sources require RM confirmation."),
    _field("proposal.credit_request_representative.name", "Người đại diện đề nghị cấp tín dụng - họ tên", RM_PROVIDED, FactValueType.TEXT, requirement_mode=RequirementMode.REQUIRED),
    _field("proposal.credit_request_representative.title", "Người đại diện đề nghị cấp tín dụng - chức vụ", RM_PROVIDED, FactValueType.TEXT, requirement_mode=RequirementMode.REQUIRED),
    _field("compliance.restricted_credit_subject", "Khách hàng thuộc đối tượng hạn chế cấp tín dụng hay không?", RM_SELECTED, FactValueType.SELECTION, allowed_values=("CO", "KHONG"), requirement_mode=RequirementMode.REQUIRED, notes="No automatic default; AI must not decide."),
    _field("compliance.esg_assessment_required", "Quản lý rủi ro MTXH", RM_SELECTED, FactValueType.SELECTION, allowed_values=("BAT_BUOC_DANH_GIA", "KHONG_BAT_BUOC_DANH_GIA"), requirement_mode=RequirementMode.REQUIRED, notes="No automatic default; AI must not decide."),
    _field("financial.latest_net_revenue", "Doanh thu năm gần nhất", DOCUMENT_EXTRACTED, FactValueType.MONETARY_AMOUNT, unit=MILLION_VND, requirement_mode=RequirementMode.REQUIRED_WHEN_EVIDENCE_AVAILABLE, notes="Required when financial evidence is available; preserve basis conflicts."),
    _field(
        "financial.latest_revenue_year",
        "Năm doanh thu gần nhất",
        DOCUMENT_EXTRACTED,
        FactValueType.YEAR,
        requirement_mode=RequirementMode.CONDITIONAL,
        conditional_requiredness=ConditionalRequirement(kind=ConditionalRequirementKind.FIELD_PRESENT, field_key="financial.latest_net_revenue", description="Required companion fact when latest net revenue is present."),
        notes="Required companion fact for latest net revenue.",
    ),
    _field("business.primary_industry.code_level_5", "Ngành nghề kinh doanh chính - Mã ngành cấp 5", RM_PROVIDED, FactValueType.TEXT, requirement_mode=RequirementMode.REQUIRED),
    _field("business.primary_industry.name", "Ngành nghề kinh doanh chính - Tên ngành", RM_PROVIDED, FactValueType.TEXT, requirement_mode=RequirementMode.REQUIRED),
    _field("business.primary_industry.revenue_share_pct", "Tỷ trọng/Doanh thu", RM_PROVIDED, FactValueType.PERCENTAGE, requirement_mode=RequirementMode.REQUIRED),
    _field("business.main_products", "Các sản phẩm chính", RM_PROVIDED, FactValueType.REPEATABLE_TEXT_LIST, requirement_mode=RequirementMode.REQUIRED, notes="Support multiple products."),
    _field("capital.registered_capital", "Vốn đăng ký", DOCUMENT_EXTRACTED, FactValueType.MONETARY_AMOUNT, unit=MILLION_VND, requirement_mode=RequirementMode.REQUIRED_WHEN_EVIDENCE_AVAILABLE, notes="Required when charter/legal evidence is available."),
    _field("capital.paid_in_capital", "Vốn thực góp", DOCUMENT_EXTRACTED_RM_CONFIRMED, FactValueType.MONETARY_AMOUNT, unit=MILLION_VND, requirement_mode=RequirementMode.REQUIRED, rm_confirmation_mode=RMConfirmationMode.REQUIRED, notes="May be prefilled from financial statements; RM must confirm or edit before final use."),
    _field(
        "capital.paid_in_capital_as_of",
        "Tính đến ngày",
        DOCUMENT_EXTRACTED_RM_CONFIRMED,
        FactValueType.DATE,
        requirement_mode=RequirementMode.CONDITIONAL,
        conditional_requiredness=ConditionalRequirement(kind=ConditionalRequirementKind.FIELD_PRESENT, field_key="capital.paid_in_capital", description="Required when paid-in capital is provided."),
        rm_confirmation_mode=RMConfirmationMode.REQUIRED,
        notes="May be prefilled from financial statements; RM must confirm or edit.",
    ),
    _field("internal_rating.case_id", "Mã ID hồ sơ XHTD", RM_PROVIDED, FactValueType.TEXT, requirement_mode=RequirementMode.REQUIRED),
    _field("internal_rating.grade", "Hạng", RM_PROVIDED, FactValueType.TEXT, requirement_mode=RequirementMode.REQUIRED),
    _field("internal_rating.score", "Số điểm", RM_PROVIDED, FactValueType.NUMBER, requirement_mode=RequirementMode.REQUIRED),
    _field("credit_relation.loan_outstanding_at_msb", "Dư nợ cho vay của Khách hàng và người có liên quan tại MSB", CROSS_SECTION_LINKED, FactValueType.MONETARY_AMOUNT, unit=MILLION_VND, requirement_mode=RequirementMode.REQUIRED, notes="Section E-owned linked value; pending dependency is represented without a placeholder number."),
    _field("credit_relation.total_credit_exposure_at_msb", "Tổng dư tín dụng của Khách hàng và người có liên quan tại MSB", CROSS_SECTION_LINKED, FactValueType.MONETARY_AMOUNT, unit=MILLION_VND, requirement_mode=RequirementMode.REQUIRED, notes="Section E-owned linked value; pending dependency is represented without a placeholder number."),
    _field("credit_relation.regulatory_limit_status", "So với quy định của NHNN", RM_SELECTED, FactValueType.SELECTION, allowed_values=("VUOT_GIOI_HAN", "TRONG_GIOI_HAN"), requirement_mode=RequirementMode.REQUIRED, notes="Selected by RM; not supplied by Section E and not automatically inferred."),
    _field("approval.existing_limit.total", "HMTD đã cấp cho KH & nhóm KH liên quan - Giá trị tổng HMTD", RM_PROVIDED, FactValueType.MONETARY_AMOUNT, unit=MILLION_VND, requirement_mode=RequirementMode.CONDITIONAL, conditional_requiredness=ConditionalRequirement(kind=ConditionalRequirementKind.BUSINESS_CONDITION, condition_code="EXISTING_APPROVED_LIMIT_APPLIES", description="Required when an existing approved limit applies; future workflow may explicitly represent zero/not applicable."), notes="Do not invent an existing limit."),
    _field("approval.existing_limit.unsecured", "HMTD đã cấp cho KH & nhóm KH liên quan - Giá trị HMTD không TSBĐ", RM_PROVIDED, FactValueType.MONETARY_AMOUNT, unit=MILLION_VND, requirement_mode=RequirementMode.CONDITIONAL, conditional_requiredness=ConditionalRequirement(kind=ConditionalRequirementKind.BUSINESS_CONDITION, condition_code="EXISTING_APPROVED_LIMIT_APPLIES", description="Required when an existing approved limit applies; future workflow may explicitly represent zero/not applicable."), notes="Do not invent an existing limit."),
    _field("approval.proposed_limit.total", "HMTD đề xuất cấp cho KH lần này - Giá trị tổng HMTD", RM_PROVIDED, FactValueType.MONETARY_AMOUNT, unit=MILLION_VND, requirement_mode=RequirementMode.REQUIRED),
    _field("approval.proposed_limit.unsecured", "HMTD đề xuất cấp cho KH lần này - Giá trị HMTD không TSBĐ", RM_PROVIDED, FactValueType.MONETARY_AMOUNT, unit=MILLION_VND, requirement_mode=RequirementMode.REQUIRED),
    _field("approval.aggregate_limit.total", "Tổng cộng - Giá trị tổng HMTD", RM_PROVIDED, FactValueType.MONETARY_AMOUNT, unit=MILLION_VND, requirement_mode=RequirementMode.REQUIRED, notes="RM-provided. There is no machine-readable derivation rule for this field."),
    _field("approval.aggregate_limit.unsecured", "Tổng cộng - Giá trị HMTD không TSBĐ", RM_PROVIDED, FactValueType.MONETARY_AMOUNT, unit=MILLION_VND, requirement_mode=RequirementMode.REQUIRED, notes="RM-provided. There is no machine-readable derivation rule for this field."),
    _field("approval.authority", "Thẩm quyền phê duyệt đề xuất lần này", RM_SELECTED, FactValueType.SELECTION, allowed_values=("HĐTD&ĐT", "HĐQT", "HĐTDCC"), requirement_mode=RequirementMode.REQUIRED, notes="Single canonical selected value; no automatic inference."),
    _field("approval.previous_approval_period", "Kỳ phê duyệt gần nhất (nếu có)", RM_PROVIDED, FactValueType.TEXT_OR_DATE_PERIOD, notes="Optional."),
    _field("proposal.request_type", "Đề xuất nhu cầu tín dụng", RM_SELECTED, FactValueType.SELECTION, allowed_values=("TAI_CAP", "CAP_MOI"), requirement_mode=RequirementMode.REQUIRED),
)


def _build_registry(fields: tuple[SectionAFieldDefinition, ...]) -> Mapping[str, SectionAFieldDefinition]:
    keys = [field.canonical_key for field in fields]
    duplicates = sorted({key for key in keys if keys.count(key) > 1})
    if duplicates:
        raise ValueError(f"Duplicate Section A canonical keys: {duplicates}")
    return {field.canonical_key: field for field in fields}


SECTION_A_FIELD_REGISTRY: Mapping[str, SectionAFieldDefinition] = _build_registry(SECTION_A_FIELDS)
