"""Module: bindings.py
Description: Canonical MB07 Template Binding Definitions and Metadata Model.
Maps business fact paths to explicit semantic anchors, target relationships,
and mutation types for deterministic, template-preserving rendering.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional, Tuple


class MutationType(Enum):
    """Classification of allowed in-place mutation behaviors."""
    SINGLE_VALUE = "SINGLE_VALUE"          # Single text run or cell value
    MULTILINE_TEXT = "MULTILINE_TEXT"      # Multiline narrative / paragraphs
    TABLE_ROWS = "TABLE_ROWS"              # Multi-row table population
    OPTIONAL_BLOCK = "OPTIONAL_BLOCK"      # Optional section / status marker
    FORM_FIELD = "FORM_FIELD"              # Form field dropdown or text field
    CHECKBOX = "CHECKBOX"                  # Word OOXML checkbox toggle


class TargetRelationship(Enum):
    """Spatial/structural relationship between semantic anchor and target element."""
    SELF = "SELF"                          # Mutate the anchor cell/paragraph itself
    NEIGHBOR_CELL_RIGHT = "NEIGHBOR_RIGHT" # Next cell in the same row
    NEIGHBOR_CELL_BELOW = "NEIGHBOR_BELOW" # Cell directly underneath in next row
    ASSOCIATED_TABLE = "ASSOCIATED_TABLE"  # Table immediately following the heading
    NARRATIVE_PARAGRAPH = "NARRATIVE_PARA" # Designated narrative paragraph following anchor


@dataclass(frozen=True)
class TemplateBinding:
    """Explicit binding configuration for a mutable MB07 field."""
    binding_id: str
    field_path: str
    anchor_text: str
    target_rel: TargetRelationship = TargetRelationship.NEIGHBOR_CELL_RIGHT
    mutation_type: MutationType = MutationType.SINGLE_VALUE
    required: bool = True
    expected_table_index: Optional[int] = None
    expected_row_offset: Optional[int] = None
    expected_col_index: Optional[int] = None
    allow_row_growth: bool = False
    max_growth_rows: Optional[int] = None
    description: str = ""


# Authoritative registry of standard MB07 semantic bindings
MB07_STANDARD_BINDINGS: Dict[str, TemplateBinding] = {
    # Header Metadata (Table 0)
    "meta_unit_name": TemplateBinding(
        binding_id="meta_unit_name",
        field_path="submission.unit_name",
        anchor_text="Đơn vị trình",
        target_rel=TargetRelationship.NEIGHBOR_CELL_RIGHT,
        mutation_type=MutationType.SINGLE_VALUE,
        expected_table_index=0,
        description="Đơn vị kinh doanh trình tờ trình",
    ),
    "meta_proposal_no": TemplateBinding(
        binding_id="meta_proposal_no",
        field_path="submission.proposal_no",
        anchor_text="Số tờ trình",
        target_rel=TargetRelationship.NEIGHBOR_CELL_RIGHT,
        mutation_type=MutationType.SINGLE_VALUE,
        expected_table_index=0,
        description="Số hiệu tờ trình MB07",
    ),
    "meta_rm_info": TemplateBinding(
        binding_id="meta_rm_info",
        field_path="submission.rm_name",
        anchor_text="Cán bộ quản lý quan hệ khách hàng",
        target_rel=TargetRelationship.NEIGHBOR_CELL_RIGHT,
        mutation_type=MutationType.SINGLE_VALUE,
        expected_table_index=0,
        description="Họ tên và chức danh cán bộ RM",
    ),

    # Section A: Profile (Table 1)
    "customer_name": TemplateBinding(
        binding_id="customer_name",
        field_path="company.name",
        anchor_text="Tên khách hàng",
        target_rel=TargetRelationship.NEIGHBOR_CELL_RIGHT,
        mutation_type=MutationType.SINGLE_VALUE,
        expected_table_index=1,
        description="Tên đầy đủ của doanh nghiệp",
    ),
    "customer_tax_code": TemplateBinding(
        binding_id="customer_tax_code",
        field_path="company.registration_no",
        anchor_text="Mã số thuế",
        target_rel=TargetRelationship.NEIGHBOR_CELL_RIGHT,
        mutation_type=MutationType.SINGLE_VALUE,
        expected_table_index=1,
        description="Mã số doanh nghiệp / Mã số thuế",
    ),
    "customer_cif": TemplateBinding(
        binding_id="customer_cif",
        field_path="relationship.cif",
        anchor_text="CIF",
        target_rel=TargetRelationship.NEIGHBOR_CELL_RIGHT,
        mutation_type=MutationType.SINGLE_VALUE,
        expected_table_index=1,
        description="Mã định danh khách hàng CIF tại MSB",
    ),
    "customer_address": TemplateBinding(
        binding_id="customer_address",
        field_path="company.address.headquarters",
        anchor_text="Địa chỉ trụ sở chính",
        target_rel=TargetRelationship.NEIGHBOR_CELL_RIGHT,
        mutation_type=MutationType.SINGLE_VALUE,
        expected_table_index=1,
        description="Địa chỉ đăng ký kinh doanh chính thức",
    ),
    "customer_legal_rep": TemplateBinding(
        binding_id="customer_legal_rep",
        field_path="company.legal_representative.name",
        anchor_text="Người đại diện theo pháp luật",
        target_rel=TargetRelationship.NEIGHBOR_CELL_RIGHT,
        mutation_type=MutationType.SINGLE_VALUE,
        expected_table_index=1,
        description="Họ tên Người đại diện theo pháp luật",
    ),

    # Section B: Facility Proposal
    "section_b_table": TemplateBinding(
        binding_id="section_b_table",
        field_path="facilities.proposed",
        anchor_text="NỘI DUNG ĐỀ XUẤT CẤP TÍN DỤNG",
        target_rel=TargetRelationship.ASSOCIATED_TABLE,
        mutation_type=MutationType.TABLE_ROWS,
        expected_table_index=15,
        description="Bảng đề xuất hạn mức tín dụng Phần B",
    ),

    # Section C: Business & Supply Chain
    "section_c_shareholders": TemplateBinding(
        binding_id="section_c_shareholders",
        field_path="business.shareholders",
        anchor_text="Cơ cấu cổ đông",
        target_rel=TargetRelationship.ASSOCIATED_TABLE,
        mutation_type=MutationType.TABLE_ROWS,
        expected_table_index=17,
        description="Bảng danh sách cổ đông lớn / góp vốn",
    ),
    "section_c_management": TemplateBinding(
        binding_id="section_c_management",
        field_path="business.management",
        anchor_text="Cơ cấu bộ máy quản trị",
        target_rel=TargetRelationship.ASSOCIATED_TABLE,
        mutation_type=MutationType.TABLE_ROWS,
        expected_table_index=20,
        description="Bảng thành viên ban lãnh đạo điều hành",
    ),

    # Section D: Financial Matrix
    "section_d_financials": TemplateBinding(
        binding_id="section_d_financials",
        field_path="financials.matrix_3y",
        anchor_text="TÌNH HÌNH TÀI CHÍNH DOANH NGHIỆP",
        target_rel=TargetRelationship.ASSOCIATED_TABLE,
        mutation_type=MutationType.TABLE_ROWS,
        expected_table_index=31,
        description="Bảng phân tích tài chính 3 năm (P&L, BS, Ratios)",
    ),

    # Section E: CIC Credit Relations
    "section_e_cic_relations": TemplateBinding(
        binding_id="section_e_cic_relations",
        field_path="cic.institution_relations",
        anchor_text="THÔNG TIN QUAN HỆ TÍN DỤNG CỦA KHÁCH HÀNG",
        target_rel=TargetRelationship.ASSOCIATED_TABLE,
        mutation_type=MutationType.TABLE_ROWS,
        expected_table_index=32,
        allow_row_growth=True,
        max_growth_rows=30,
        description="Bảng chi tiết quan hệ tín dụng CIC đa ngân hàng",
    ),
}
