"""Cross-section dependency integration for Section A (Phase 9).

Binds Section E credit relation facts into Section A canonical case data
without asking the RM to enter them repeatedly.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from .enums import FactValueType, SourceCategory
from .models import CanonicalValue
from .review_session import SectionAReviewSession


@dataclass(frozen=True)
class SectionECreditReportData:
    """Standardized Section E credit exposure output to feed canonical case data."""

    loan_outstanding_at_msb: Decimal
    total_credit_exposure_at_msb: Decimal
    regulatory_limit_status: str | None = None  # "TRONG_GIOI_HAN" or "VUOT_GIOI_HAN"
    unit: str = "triệu đồng"

    def __post_init__(self) -> None:
        if not isinstance(self.loan_outstanding_at_msb, Decimal):
            raise TypeError("loan_outstanding_at_msb must be a Decimal instance.")
        if not isinstance(self.total_credit_exposure_at_msb, Decimal):
            raise TypeError("total_credit_exposure_at_msb must be a Decimal instance.")
        if self.loan_outstanding_at_msb < 0 or self.total_credit_exposure_at_msb < 0:
            raise ValueError("Credit exposure amounts cannot be negative.")
        if self.total_credit_exposure_at_msb < self.loan_outstanding_at_msb:
            raise ValueError("Total credit exposure cannot be less than loan outstanding.")
        if self.regulatory_limit_status and self.regulatory_limit_status not in (
            "TRONG_GIOI_HAN",
            "VUOT_GIOI_HAN",
        ):
            raise ValueError(
                f"Invalid regulatory_limit_status: '{self.regulatory_limit_status}'. "
                "Allowed: ('TRONG_GIOI_HAN', 'VUOT_GIOI_HAN')."
            )


class SectionEDependencyConnector:
    """Connects Section E outputs to Section A review session."""

    def link_section_e_data(
        self,
        session: SectionAReviewSession,
        data: SectionECreditReportData,
    ) -> None:
        """Apply Section E credit figures directly to Section A canonical facts.

        Clears PENDING_SECTION_DEPENDENCY and applies CROSS_SECTION_LINKED category.
        """
        session.link_cross_section_fact(
            canonical_key="credit_relation.loan_outstanding_at_msb",
            value=data.loan_outstanding_at_msb,
            unit=data.unit,
        )
        session.link_cross_section_fact(
            canonical_key="credit_relation.total_credit_exposure_at_msb",
            value=data.total_credit_exposure_at_msb,
            unit=data.unit,
        )

        if data.regulatory_limit_status:
            session.set_rm_selected(
                canonical_key="credit_relation.regulatory_limit_status",
                selection=data.regulatory_limit_status,
            )
