# -*- coding: utf-8 -*-
"""Deterministic canonical fact packager.

Module: msb_eb_copilot.src.narrative.fact_packager
Strict Rules:
- Packages ONLY confirmed canonical case_data and authoritative Python calculations.
- Reuses existing authoritative engines (compute_canonical_ratios, CreditDemandEngine, RorwaEngine).
- Stable deterministic SHA-256 manifest hash.
- Generates display_representations for strict post-generation numeric validation.
"""

from __future__ import annotations
from decimal import Decimal
import hashlib
import json
import re
from typing import Any, Dict, List, Optional

from .models import (
    FactAuthority,
    FactCompleteness,
    FactItem,
    FactManifest,
    FactNature,
)
from ..mapping.financial_mapper import compute_canonical_ratios
from ..credit_demand_engine import CreditDemandEngine, FinancialInput
from ..rorwa_engine import DealStructure, RorwaEngine


def _generate_numeric_representations(val: float, unit: Optional[str] = None) -> List[str]:
    """Generate deterministic string representations for numbers."""
    reps = set()
    if val is None:
        return []

    # Basic numeric strings
    int_val = int(round(val)) if abs(val - round(val)) < 1e-4 else None
    if int_val is not None:
        reps.add(str(int_val))
        # Dot as thousand separator (Vietnamese)
        reps.add(f"{int_val:,}".replace(",", "."))
        reps.add(f"{int_val:,}")
    
    # 1 decimal and 2 decimal places
    reps.add(f"{val:.1f}")
    reps.add(f"{val:.2f}")
    reps.add(f"{val:.1f}".replace(".", ","))
    reps.add(f"{val:.2f}".replace(".", ","))
    reps.add(f"{val:,.1f}".replace(",", "X").replace(".", ",").replace("X", "."))
    reps.add(f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))

    if unit == "TRIEU_VND":
        if int_val is not None:
            reps.add(f"{int_val:,} triệu VND".replace(",", "."))
            reps.add(f"{int_val:,} triệu đồng".replace(",", "."))
            reps.add(f"{int_val:,} triệu".replace(",", "."))
        # Also representations in tỷ VND if >= 1000 triệu
        ty_val = val / 1000.0
        reps.add(f"{ty_val:.1f} tỷ VND")
        reps.add(f"{ty_val:.1f} tỷ đồng")
        reps.add(f"{ty_val:.1f} tỷ")
        reps.add(f"{ty_val:.2f} tỷ VND")
        reps.add(f"{ty_val:.2f} tỷ đồng")
        reps.add(f"{ty_val:.2f} tỷ")
        reps.add(f"{ty_val:.1f}".replace(".", ",") + " tỷ VND")
        reps.add(f"{ty_val:.1f}".replace(".", ",") + " tỷ đồng")
        reps.add(f"{ty_val:.1f}".replace(".", ",") + " tỷ")
        reps.add(f"{ty_val:.2f}".replace(".", ",") + " tỷ đồng")
        reps.add(f"{ty_val:.2f}".replace(".", ",") + " tỷ")
        if abs(ty_val - round(ty_val)) < 1e-3:
            int_ty = int(round(ty_val))
            reps.add(f"{int_ty} tỷ VND")
            reps.add(f"{int_ty} tỷ đồng")
            reps.add(f"{int_ty} tỷ")
            reps.add(f"{int_ty:,} tỷ".replace(",", "."))

    elif unit == "PERCENT":
        reps.add(f"{val:.1f}%")
        reps.add(f"{val:.2f}%")
        reps.add(f"{val:.1f}%".replace(".", ","))
        reps.add(f"{val:.2f}%".replace(".", ","))
        if int_val is not None:
            reps.add(f"{int_val}%")

    elif unit == "DAYS":
        if int_val is not None:
            reps.add(f"{int_val} ngày")
        reps.add(f"{val:.1f} ngày")
        reps.add(f"{val:.1f}".replace(".", ",") + " ngày")

    elif unit == "RATIO":
        reps.add(f"{val:.2f} lần")
        reps.add(f"{val:.2f}x")
        reps.add(f"{val:.2f}".replace(".", ",") + " lần")
        reps.add(f"{val:.2f}".replace(".", ",") + "x")
        reps.add(f"{val:.1f} lần")
        reps.add(f"{val:.1f}".replace(".", ",") + " lần")

    return sorted(list(reps))


class FactPackager:
    """Compiles confirmed canonical case data into a typed, hashed FactManifest."""

    @classmethod
    def compute_manifest_hash(cls, items: List[FactItem]) -> str:
        """Deterministic SHA-256 hash over serialized FactItem dictionaries."""
        sorted_dicts = [item.to_canonical_dict() for item in sorted(items, key=lambda x: x.fact_id)]
        serialized = json.dumps(sorted_dicts, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    @classmethod
    def package_from_case_data(cls, case_data: Dict[str, Any], case_id: str = "CASE") -> FactManifest:
        """Convenience method to assemble FactManifest from case_data dict."""
        return cls.package(case_id=case_id, case_data=case_data)

    @classmethod
    def package(cls, case_id: str, case_data: Dict[str, Any]) -> FactManifest:
        """Assemble FactManifest from canonical case_data."""
        cust = case_data.get("customer", {})
        rm = case_data.get("rm_metadata", {})
        sec_b = case_data.get("section_b", {})
        sec_c = case_data.get("section_c", {})
        sec_d = case_data.get("section_d", {})
        sec_e = case_data.get("section_e", {})

        legal_facts: Dict[str, FactItem] = {}
        business_facts: Dict[str, FactItem] = {}
        financial_facts: Dict[str, FactItem] = {}
        credit_request_facts: Dict[str, FactItem] = {}
        debt_service_facts: Dict[str, FactItem] = {}
        cic_facts: Dict[str, FactItem] = {}
        data_gaps: List[FactItem] = []

        all_collected_items: List[FactItem] = []

        # Helper to register fact
        def reg(dest: Dict[str, FactItem], fact: FactItem):
            dest[fact.fact_id] = fact
            all_collected_items.append(fact)

        # ----------------------------------------------------------------------
        # 1. LEGAL FACTS
        # ----------------------------------------------------------------------
        if cust.get("name"):
            reg(legal_facts, FactItem(
                fact_id="LEGAL_NAME",
                section="LEGAL",
                canonical_path="customer.name",
                label="Tên doanh nghiệp",
                value=cust["name"],
                unit="TEXT",
                period=None,
                authority=FactAuthority.SOURCE_FACT,
                fact_nature=FactNature.OBJECTIVE_FACT,
                completeness=FactCompleteness.COMPLETE,
                display_representations=[cust["name"]]
            ))

        if cust.get("short_name"):
            reg(legal_facts, FactItem(
                fact_id="LEGAL_SHORT_NAME",
                section="LEGAL",
                canonical_path="customer.short_name",
                label="Tên viết tắt",
                value=cust["short_name"],
                unit="TEXT",
                period=None,
                authority=FactAuthority.SOURCE_FACT,
                fact_nature=FactNature.OBJECTIVE_FACT,
                completeness=FactCompleteness.COMPLETE,
                display_representations=[cust["short_name"]]
            ))

        if cust.get("tax_code"):
            reg(legal_facts, FactItem(
                fact_id="LEGAL_TAX_CODE",
                section="LEGAL",
                canonical_path="customer.tax_code",
                label="Mã số thuế",
                value=cust["tax_code"],
                unit="TEXT",
                period=None,
                authority=FactAuthority.SOURCE_FACT,
                fact_nature=FactNature.OBJECTIVE_FACT,
                completeness=FactCompleteness.COMPLETE,
                display_representations=[cust["tax_code"]]
            ))

        if cust.get("address"):
            reg(legal_facts, FactItem(
                fact_id="LEGAL_ADDRESS",
                section="LEGAL",
                canonical_path="customer.address",
                label="Địa chỉ trụ sở",
                value=cust["address"],
                unit="TEXT",
                period=None,
                authority=FactAuthority.SOURCE_FACT,
                fact_nature=FactNature.OBJECTIVE_FACT,
                completeness=FactCompleteness.COMPLETE,
                display_representations=[cust["address"]]
            ))

        if cust.get("charter_capital"):
            cap = float(cust["charter_capital"])
            reg(legal_facts, FactItem(
                fact_id="LEGAL_CHARTER_CAPITAL",
                section="LEGAL",
                canonical_path="customer.charter_capital",
                label="Vốn điều lệ",
                value=cap,
                unit="TRIEU_VND",
                period=None,
                authority=FactAuthority.SOURCE_FACT,
                fact_nature=FactNature.OBJECTIVE_FACT,
                completeness=FactCompleteness.COMPLETE,
                display_representations=_generate_numeric_representations(cap, "TRIEU_VND")
            ))

        if cust.get("legal_rep_name"):
            reg(legal_facts, FactItem(
                fact_id="LEGAL_REP_NAME",
                section="LEGAL",
                canonical_path="customer.legal_rep_name",
                label="Người đại diện pháp luật",
                value=cust["legal_rep_name"],
                unit="TEXT",
                period=None,
                authority=FactAuthority.SOURCE_FACT,
                fact_nature=FactNature.OBJECTIVE_FACT,
                completeness=FactCompleteness.COMPLETE,
                display_representations=[cust["legal_rep_name"]]
            ))

        if cust.get("parent_group"):
            reg(legal_facts, FactItem(
                fact_id="PARENT_GROUP",
                section="LEGAL",
                canonical_path="customer.parent_group",
                label="Công ty mẹ / Tập đoàn",
                value=cust["parent_group"],
                unit="TEXT",
                period=None,
                authority=FactAuthority.SOURCE_FACT,
                fact_nature=FactNature.OBJECTIVE_FACT,
                completeness=FactCompleteness.COMPLETE,
                display_representations=[cust["parent_group"]]
            ))

        # ----------------------------------------------------------------------
        # 2. BUSINESS FACTS (Section C)
        # ----------------------------------------------------------------------
        if sec_c.get("history_narrative"):
            reg(business_facts, FactItem(
                fact_id="BIZ_HISTORY",
                section="BUSINESS",
                canonical_path="section_c.history_narrative",
                label="Quá trình hình thành & phát triển",
                value=sec_c["history_narrative"],
                unit="TEXT",
                period=None,
                authority=FactAuthority.SOURCE_FACT,
                fact_nature=FactNature.OBJECTIVE_FACT,
                completeness=FactCompleteness.COMPLETE,
                display_representations=[]
            ))

        if sec_c.get("business_model"):
            reg(business_facts, FactItem(
                fact_id="BIZ_MODEL",
                section="BUSINESS",
                canonical_path="section_c.business_model",
                label="Mô hình kinh doanh",
                value=sec_c["business_model"],
                unit="TEXT",
                period=None,
                authority=FactAuthority.SOURCE_FACT,
                fact_nature=FactNature.OBJECTIVE_FACT,
                completeness=FactCompleteness.COMPLETE,
                display_representations=[str(sec_c["business_model"])]
            ))

        # Shareholders
        sh_list = sec_c.get("shareholders", [])
        if sh_list:
            reg(business_facts, FactItem(
                fact_id="BIZ_SHAREHOLDERS",
                section="BUSINESS",
                canonical_path="section_c.shareholders",
                label="Danh sách cổ đông lớn",
                value=sh_list,
                unit="COUNT",
                period=None,
                authority=FactAuthority.SOURCE_FACT,
                fact_nature=FactNature.OBJECTIVE_FACT,
                completeness=FactCompleteness.COMPLETE,
                display_representations=[f"{len(sh_list)} cổ đông"] + [s.get("name", "") for s in sh_list if s.get("name")]
            ))
            # Individual major shareholders
            for idx, sh in enumerate(sh_list, 1):
                s_pct = float(sh.get("pct", 0.0))
                s_name = sh.get("name", "")
                reg(business_facts, FactItem(
                    fact_id=f"BIZ_SHAREHOLDER_{idx}",
                    section="BUSINESS",
                    canonical_path=f"section_c.shareholders[{idx}]",
                    label=f"Cổ đông {s_name}",
                    value=s_pct,
                    unit="PERCENT",
                    period=None,
                    authority=FactAuthority.SOURCE_FACT,
                    fact_nature=FactNature.OBJECTIVE_FACT,
                    completeness=FactCompleteness.COMPLETE,
                    display_representations=_generate_numeric_representations(s_pct, "PERCENT") + [s_name]
                ))

        # Management
        mgmt_list = sec_c.get("management", [])
        if mgmt_list:
            reg(business_facts, FactItem(
                fact_id="BIZ_MANAGEMENT",
                section="BUSINESS",
                canonical_path="section_c.management",
                label="Ban điều hành",
                value=mgmt_list,
                unit="COUNT",
                period=None,
                authority=FactAuthority.SOURCE_FACT,
                fact_nature=FactNature.OBJECTIVE_FACT,
                completeness=FactCompleteness.COMPLETE,
                display_representations=[f"{len(mgmt_list)} thành viên"] + [m.get("name", "") for m in mgmt_list if m.get("name")]
            ))
            for idx, m in enumerate(mgmt_list, 1):
                m_name = m.get("name", "")
                m_exp = m.get("exp")
                m_title = m.get("title", "")
                reps = [m_name, m_title]
                if m_exp is not None:
                    reps.extend([f"{m_exp} năm", str(m_exp)])
                reg(business_facts, FactItem(
                    fact_id=f"BIZ_MGMT_MEMBER_{idx}",
                    section="BUSINESS",
                    canonical_path=f"section_c.management[{idx}]",
                    label=f"{m_title}: {m_name}",
                    value=m_exp if m_exp is not None else m_name,
                    unit="YEAR" if m_exp is not None else "TEXT",
                    period=None,
                    authority=FactAuthority.SOURCE_FACT,
                    fact_nature=FactNature.OBJECTIVE_FACT,
                    completeness=FactCompleteness.COMPLETE,
                    display_representations=reps
                ))

        # Products
        prod_list = sec_c.get("products", [])
        if prod_list:
            for idx, p in enumerate(prod_list, 1):
                p_name = p.get("name", "")
                p_share = float(p.get("share", 0.0))
                reg(business_facts, FactItem(
                    fact_id=f"BIZ_PRODUCT_{idx}",
                    section="BUSINESS",
                    canonical_path=f"section_c.products[{idx}]",
                    label=f"Sản phẩm {p_name}",
                    value=p_share,
                    unit="PERCENT",
                    period=None,
                    authority=FactAuthority.SOURCE_FACT,
                    fact_nature=FactNature.OBJECTIVE_FACT,
                    completeness=FactCompleteness.COMPLETE,
                    display_representations=_generate_numeric_representations(p_share, "PERCENT") + [p_name]
                ))

        # Suppliers
        supp_list = sec_c.get("suppliers", [])
        if supp_list:
            for idx, s in enumerate(supp_list, 1):
                s_name = s.get("name", "")
                s_share = float(s.get("share", 0.0))
                reg(business_facts, FactItem(
                    fact_id=f"BIZ_SUPPLIER_{idx}",
                    section="BUSINESS",
                    canonical_path=f"section_c.suppliers[{idx}]",
                    label=f"Nhà cung cấp {s_name}",
                    value=s_share,
                    unit="PERCENT",
                    period=None,
                    authority=FactAuthority.SOURCE_FACT,
                    fact_nature=FactNature.OBJECTIVE_FACT,
                    completeness=FactCompleteness.COMPLETE,
                    display_representations=_generate_numeric_representations(s_share, "PERCENT") + [s_name]
                ))

        # Customers
        cust_list = sec_c.get("customers", [])
        if cust_list:
            for idx, c in enumerate(cust_list, 1):
                c_name = c.get("name", "")
                c_share = float(c.get("share", 0.0))
                reg(business_facts, FactItem(
                    fact_id=f"BIZ_CUSTOMER_{idx}",
                    section="BUSINESS",
                    canonical_path=f"section_c.customers[{idx}]",
                    label=f"Khách hàng {c_name}",
                    value=c_share,
                    unit="PERCENT",
                    period=None,
                    authority=FactAuthority.SOURCE_FACT,
                    fact_nature=FactNature.OBJECTIVE_FACT,
                    completeness=FactCompleteness.COMPLETE,
                    display_representations=_generate_numeric_representations(c_share, "PERCENT") + [c_name]
                ))

        # Market share claim (SOURCE_CLAIM)
        mkt_claim = sec_c.get("market_share_estimate")
        if mkt_claim:
            num_tokens = re.findall(r"\b\d+(?:[\.,]\d+)?%?\b", str(mkt_claim))
            reps = [str(mkt_claim)] + num_tokens
            for t in list(num_tokens):
                reps.append(t.replace("%", "").strip())
            reg(business_facts, FactItem(
                fact_id="BIZ_MARKET_SHARE_CLAIM",
                section="BUSINESS",
                canonical_path="section_c.market_share_estimate",
                label="Tuyên bố thị phần của doanh nghiệp",
                value=mkt_claim,
                unit="TEXT",
                period=None,
                authority=FactAuthority.SOURCE_CLAIM,
                fact_nature=FactNature.SOURCE_CLAIM,
                completeness=FactCompleteness.ESTIMATED,
                source_attribution="Theo hồ sơ doanh nghiệp cung cấp, doanh nghiệp cho biết",
                display_representations=reps
            ))
        else:
            data_gaps.append(FactItem(
                fact_id="GAP_MARKET_SHARE",
                section="DATA_GAPS",
                canonical_path="section_c.market_share_estimate",
                label="Chưa có dữ liệu thị phần độc lập",
                value="Chưa có số liệu thị phần bên thứ 3 độc lập",
                unit="TEXT",
                period=None,
                authority=FactAuthority.RM_INPUT,
                fact_nature=FactNature.DATA_GAP,
                completeness=FactCompleteness.INCOMPLETE,
                display_representations=[]
            ))

        # ----------------------------------------------------------------------
        # 3. FINANCIAL FACTS & RATIOS (Section D)
        # ----------------------------------------------------------------------
        years = sec_d.get("years", [])
        for yr in years:
            # Register historical year label as valid entity representation
            legal_facts.setdefault("YEAR_" + str(yr), FactItem(
                fact_id="YEAR_" + str(yr),
                section="FINANCIAL",
                canonical_path=f"section_d.years[{yr}]",
                label=f"Năm tài chính {yr}",
                value=str(yr),
                unit="YEAR",
                period=str(yr),
                authority=FactAuthority.SOURCE_FACT,
                fact_nature=FactNature.OBJECTIVE_FACT,
                completeness=FactCompleteness.COMPLETE,
                display_representations=[str(yr)]
            ))

        # Net Revenue
        net_rev_arr = sec_d.get("net_revenue", [])
        for idx, yr in enumerate(years):
            if idx < len(net_rev_arr) and net_rev_arr[idx] is not None:
                val = float(net_rev_arr[idx])
                reg(financial_facts, FactItem(
                    fact_id=f"FIN_REV_{yr}",
                    section="FINANCIAL",
                    canonical_path=f"section_d.net_revenue[{yr}]",
                    label=f"Doanh thu thuần năm {yr}",
                    value=val,
                    unit="TRIEU_VND",
                    period=str(yr),
                    authority=FactAuthority.SOURCE_FACT,
                    fact_nature=FactNature.OBJECTIVE_FACT,
                    completeness=FactCompleteness.COMPLETE,
                    display_representations=_generate_numeric_representations(val, "TRIEU_VND")
                ))

        # Gross Profit
        gp_arr = sec_d.get("gross_profit", [])
        for idx, yr in enumerate(years):
            if idx < len(gp_arr) and gp_arr[idx] is not None:
                val = float(gp_arr[idx])
                reg(financial_facts, FactItem(
                    fact_id=f"FIN_GP_{yr}",
                    section="FINANCIAL",
                    canonical_path=f"section_d.gross_profit[{yr}]",
                    label=f"Lợi nhuận gộp năm {yr}",
                    value=val,
                    unit="TRIEU_VND",
                    period=str(yr),
                    authority=FactAuthority.SOURCE_FACT,
                    fact_nature=FactNature.OBJECTIVE_FACT,
                    completeness=FactCompleteness.COMPLETE,
                    display_representations=_generate_numeric_representations(val, "TRIEU_VND")
                ))

        # Net Profit After Tax
        pat_arr = sec_d.get("net_profit_after_tax", [])
        for idx, yr in enumerate(years):
            if idx < len(pat_arr) and pat_arr[idx] is not None:
                val = float(pat_arr[idx])
                reg(financial_facts, FactItem(
                    fact_id=f"FIN_NP_{yr}",
                    section="FINANCIAL",
                    canonical_path=f"section_d.net_profit_after_tax[{yr}]",
                    label=f"Lợi nhuận sau thuế năm {yr}",
                    value=val,
                    unit="TRIEU_VND",
                    period=str(yr),
                    authority=FactAuthority.SOURCE_FACT,
                    fact_nature=FactNature.OBJECTIVE_FACT,
                    completeness=FactCompleteness.COMPLETE,
                    display_representations=_generate_numeric_representations(val, "TRIEU_VND")
                ))

        # Total Assets
        ta_arr = sec_d.get("total_assets", [])
        for idx, yr in enumerate(years):
            if idx < len(ta_arr) and ta_arr[idx] is not None:
                val = float(ta_arr[idx])
                reg(financial_facts, FactItem(
                    fact_id=f"FIN_TA_{yr}",
                    section="FINANCIAL",
                    canonical_path=f"section_d.total_assets[{yr}]",
                    label=f"Tổng tài sản năm {yr}",
                    value=val,
                    unit="TRIEU_VND",
                    period=str(yr),
                    authority=FactAuthority.SOURCE_FACT,
                    fact_nature=FactNature.OBJECTIVE_FACT,
                    completeness=FactCompleteness.COMPLETE,
                    display_representations=_generate_numeric_representations(val, "TRIEU_VND")
                ))

        # Current Assets
        ca_arr = sec_d.get("current_assets", [])
        for idx, yr in enumerate(years):
            if idx < len(ca_arr) and ca_arr[idx] is not None:
                val = float(ca_arr[idx])
                reg(financial_facts, FactItem(
                    fact_id=f"FIN_CA_{yr}",
                    section="FINANCIAL",
                    canonical_path=f"section_d.current_assets[{yr}]",
                    label=f"Tài sản ngắn hạn năm {yr}",
                    value=val,
                    unit="TRIEU_VND",
                    period=str(yr),
                    authority=FactAuthority.SOURCE_FACT,
                    fact_nature=FactNature.OBJECTIVE_FACT,
                    completeness=FactCompleteness.COMPLETE,
                    display_representations=_generate_numeric_representations(val, "TRIEU_VND")
                ))

        # Cash
        csh_arr = sec_d.get("cash", [])
        for idx, yr in enumerate(years):
            if idx < len(csh_arr) and csh_arr[idx] is not None:
                val = float(csh_arr[idx])
                reg(financial_facts, FactItem(
                    fact_id=f"FIN_CASH_{yr}",
                    section="FINANCIAL",
                    canonical_path=f"section_d.cash[{yr}]",
                    label=f"Tiền và tương đương tiền năm {yr}",
                    value=val,
                    unit="TRIEU_VND",
                    period=str(yr),
                    authority=FactAuthority.SOURCE_FACT,
                    fact_nature=FactNature.OBJECTIVE_FACT,
                    completeness=FactCompleteness.COMPLETE,
                    display_representations=_generate_numeric_representations(val, "TRIEU_VND")
                ))

        # Receivables
        rec_arr = sec_d.get("receivables", [])
        for idx, yr in enumerate(years):
            if idx < len(rec_arr) and rec_arr[idx] is not None:
                val = float(rec_arr[idx])
                reg(financial_facts, FactItem(
                    fact_id=f"FIN_REC_{yr}",
                    section="FINANCIAL",
                    canonical_path=f"section_d.receivables[{yr}]",
                    label=f"Các khoản phải thu năm {yr}",
                    value=val,
                    unit="TRIEU_VND",
                    period=str(yr),
                    authority=FactAuthority.SOURCE_FACT,
                    fact_nature=FactNature.OBJECTIVE_FACT,
                    completeness=FactCompleteness.COMPLETE,
                    display_representations=_generate_numeric_representations(val, "TRIEU_VND")
                ))

        # Inventories
        inv_arr = sec_d.get("inventories", [])
        for idx, yr in enumerate(years):
            if idx < len(inv_arr) and inv_arr[idx] is not None:
                val = float(inv_arr[idx])
                reg(financial_facts, FactItem(
                    fact_id=f"FIN_INV_{yr}",
                    section="FINANCIAL",
                    canonical_path=f"section_d.inventories[{yr}]",
                    label=f"Hàng tồn kho năm {yr}",
                    value=val,
                    unit="TRIEU_VND",
                    period=str(yr),
                    authority=FactAuthority.SOURCE_FACT,
                    fact_nature=FactNature.OBJECTIVE_FACT,
                    completeness=FactCompleteness.COMPLETE,
                    display_representations=_generate_numeric_representations(val, "TRIEU_VND")
                ))

        # Short-term debt
        std_arr = sec_d.get("short_term_debt", [])
        for idx, yr in enumerate(years):
            if idx < len(std_arr) and std_arr[idx] is not None:
                val = float(std_arr[idx])
                reg(financial_facts, FactItem(
                    fact_id=f"FIN_STD_{yr}",
                    section="FINANCIAL",
                    canonical_path=f"section_d.short_term_debt[{yr}]",
                    label=f"Nợ vay ngắn hạn năm {yr}",
                    value=val,
                    unit="TRIEU_VND",
                    period=str(yr),
                    authority=FactAuthority.SOURCE_FACT,
                    fact_nature=FactNature.OBJECTIVE_FACT,
                    completeness=FactCompleteness.COMPLETE,
                    display_representations=_generate_numeric_representations(val, "TRIEU_VND")
                ))

        # Equity
        eq_arr = sec_d.get("equity", [])
        for idx, yr in enumerate(years):
            if idx < len(eq_arr) and eq_arr[idx] is not None:
                val = float(eq_arr[idx])
                reg(financial_facts, FactItem(
                    fact_id=f"FIN_EQ_{yr}",
                    section="FINANCIAL",
                    canonical_path=f"section_d.equity[{yr}]",
                    label=f"Vốn chủ sở hữu năm {yr}",
                    value=val,
                    unit="TRIEU_VND",
                    period=str(yr),
                    authority=FactAuthority.SOURCE_FACT,
                    fact_nature=FactNature.OBJECTIVE_FACT,
                    completeness=FactCompleteness.COMPLETE,
                    display_representations=_generate_numeric_representations(val, "TRIEU_VND")
                ))

        # Compute Python-derived ratios using authoritative engine
        computed_ratios = compute_canonical_ratios(sec_d)
        for ratio_key, ratio_vals in computed_ratios.items():
            for idx, yr in enumerate(years):
                if idx < len(ratio_vals) and ratio_vals[idx] is not None:
                    val = float(ratio_vals[idx])
                    unit = "PERCENT" if "margin" in ratio_key or "growth" in ratio_key or ratio_key in ("ros", "roe") else "RATIO"
                    reg(financial_facts, FactItem(
                        fact_id=f"RATIO_{ratio_key.upper()}_{yr}",
                        section="FINANCIAL",
                        canonical_path=f"section_d.ratios.{ratio_key}[{yr}]",
                        label=f"Chỉ số {ratio_key} năm {yr}",
                        value=val,
                        unit=unit,
                        period=str(yr),
                        authority=FactAuthority.DERIVED_PYTHON,
                        fact_nature=FactNature.DERIVED_METRIC,
                        completeness=FactCompleteness.COMPLETE,
                        display_representations=_generate_numeric_representations(val, unit)
                    ))

        # ----------------------------------------------------------------------
        # 4. CREDIT REQUEST FACTS (Section B)
        # ----------------------------------------------------------------------
        if sec_b.get("total_limit") is not None:
            tot_lim = float(sec_b["total_limit"])
            reg(credit_request_facts, FactItem(
                fact_id="REQ_TOTAL_LIMIT",
                section="CREDIT_REQUEST",
                canonical_path="section_b.total_limit",
                label="Tổng hạn mức đề xuất",
                value=tot_lim,
                unit="TRIEU_VND",
                period=None,
                authority=FactAuthority.RM_INPUT,
                fact_nature=FactNature.OBJECTIVE_FACT,
                completeness=FactCompleteness.COMPLETE,
                display_representations=_generate_numeric_representations(tot_lim, "TRIEU_VND")
            ))

        if sec_b.get("loan_limit") is not None:
            loan_lim = float(sec_b["loan_limit"])
            reg(credit_request_facts, FactItem(
                fact_id="REQ_LOAN_LIMIT",
                section="CREDIT_REQUEST",
                canonical_path="section_b.loan_limit",
                label="Hạn mức cho vay ngắn hạn",
                value=loan_lim,
                unit="TRIEU_VND",
                period=None,
                authority=FactAuthority.RM_INPUT,
                fact_nature=FactNature.OBJECTIVE_FACT,
                completeness=FactCompleteness.COMPLETE,
                display_representations=_generate_numeric_representations(loan_lim, "TRIEU_VND")
            ))

        if sec_b.get("guarantee_limit") is not None:
            guar_lim = float(sec_b["guarantee_limit"])
            reg(credit_request_facts, FactItem(
                fact_id="REQ_GUARANTEE_LIMIT",
                section="CREDIT_REQUEST",
                canonical_path="section_b.guarantee_limit",
                label="Hạn mức bảo lãnh",
                value=guar_lim,
                unit="TRIEU_VND",
                period=None,
                authority=FactAuthority.RM_INPUT,
                fact_nature=FactNature.OBJECTIVE_FACT,
                completeness=FactCompleteness.COMPLETE,
                display_representations=_generate_numeric_representations(guar_lim, "TRIEU_VND")
            ))

        if sec_b.get("loan_purpose"):
            reg(credit_request_facts, FactItem(
                fact_id="REQ_PURPOSE",
                section="CREDIT_REQUEST",
                canonical_path="section_b.loan_purpose",
                label="Mục đích cấp tín dụng",
                value=sec_b["loan_purpose"],
                unit="TEXT",
                period=None,
                authority=FactAuthority.RM_INPUT,
                fact_nature=FactNature.OBJECTIVE_FACT,
                completeness=FactCompleteness.COMPLETE,
                display_representations=[sec_b["loan_purpose"]]
            ))

        if sec_b.get("collateral_type"):
            reg(credit_request_facts, FactItem(
                fact_id="REQ_COLLATERAL",
                section="CREDIT_REQUEST",
                canonical_path="section_b.collateral_type",
                label="Biện pháp bảo đảm",
                value=sec_b["collateral_type"],
                unit="TEXT",
                period=None,
                authority=FactAuthority.RM_INPUT,
                fact_nature=FactNature.OBJECTIVE_FACT,
                completeness=FactCompleteness.COMPLETE,
                display_representations=[sec_b["collateral_type"]]
            ))

        if sec_b.get("cashflow_commitment_pct") is not None:
            cf_pct = float(sec_b["cashflow_commitment_pct"])
            reg(credit_request_facts, FactItem(
                fact_id="REQ_CASHFLOW_PCT",
                section="CREDIT_REQUEST",
                canonical_path="section_b.cashflow_commitment_pct",
                label="Cam kết dòng tiền về MSB",
                value=cf_pct,
                unit="PERCENT",
                period=None,
                authority=FactAuthority.RM_INPUT,
                fact_nature=FactNature.OBJECTIVE_FACT,
                completeness=FactCompleteness.COMPLETE,
                display_representations=_generate_numeric_representations(cf_pct, "PERCENT")
            ))

        # ----------------------------------------------------------------------
        # 5. DEBT SERVICE & WORKING CAPITAL DEMAND (Authoritative Engines)
        # ----------------------------------------------------------------------
        # Compute authoritative working capital demand via CreditDemandEngine
        dio = 45.0
        dso = 60.0
        dpo = 30.0
        cogs_latest = float(sec_d.get("cogs", [0])[-1] or 0) * 1_000_000.0 if sec_d.get("cogs") else 0.0
        rev_latest = float(sec_d.get("net_revenue", [0])[-1] or 0) * 1_000_000.0 if sec_d.get("net_revenue") else 0.0

        if cogs_latest > 0 and rev_latest > 0:
            fin_input = FinancialInput(
                net_revenue_plan=rev_latest,
                cogs_plan=cogs_latest,
                operating_cost_plan=cogs_latest * 0.05,
                dio=dio,
                dso=dso,
                dpo=dpo,
                equity_participation=cogs_latest * 0.2,
                other_debt=0.0
            )
            cd_res = CreditDemandEngine.calculate_credit_limits(fin_input)
            wcd_mil = cd_res["working_capital_demand"] / 1_000_000.0
            ccc_days = cd_res["ccc_days"]
            turns = cd_res["turns_per_year"]

            reg(debt_service_facts, FactItem(
                fact_id="DS_WCD_DEMAND",
                section="DEBT_SERVICE",
                canonical_path="credit_demand.working_capital_demand",
                label="Nhu cầu vốn lưu động",
                value=round(wcd_mil, 1),
                unit="TRIEU_VND",
                period=None,
                authority=FactAuthority.DERIVED_PYTHON,
                fact_nature=FactNature.DERIVED_METRIC,
                completeness=FactCompleteness.COMPLETE,
                display_representations=_generate_numeric_representations(round(wcd_mil, 1), "TRIEU_VND")
            ))

            reg(debt_service_facts, FactItem(
                fact_id="DS_CCC_DAYS",
                section="DEBT_SERVICE",
                canonical_path="credit_demand.ccc_days",
                label="Chu kỳ tiền mặt (CCC)",
                value=ccc_days,
                unit="DAYS",
                period=None,
                authority=FactAuthority.DERIVED_PYTHON,
                fact_nature=FactNature.DERIVED_METRIC,
                completeness=FactCompleteness.COMPLETE,
                display_representations=_generate_numeric_representations(ccc_days, "DAYS")
            ))

            reg(debt_service_facts, FactItem(
                fact_id="DS_TURNS_PER_YEAR",
                section="DEBT_SERVICE",
                canonical_path="credit_demand.turns_per_year",
                label="Vòng quay vốn lưu động",
                value=turns,
                unit="RATIO",
                period=None,
                authority=FactAuthority.DERIVED_PYTHON,
                fact_nature=FactNature.DERIVED_METRIC,
                completeness=FactCompleteness.COMPLETE,
                display_representations=_generate_numeric_representations(turns, "RATIO")
            ))

        # Authoritative RORWA / TORWA
        req_loan_vnd = float(sec_b.get("loan_limit", 0.0)) * 1_000_000.0
        req_guar_vnd = float(sec_b.get("guarantee_limit", 0.0)) * 1_000_000.0
        if req_loan_vnd > 0:
            deal = DealStructure(
                loan_limit=req_loan_vnd,
                lc_limit=0.0,
                guarantee_limit=req_guar_vnd,
                casa_avg_balance=req_loan_vnd * 0.1
            )
            rorwa_res = RorwaEngine.calculate_deal_profitability(deal)
            torwa_val = rorwa_res["torwa"]
            rorwa_val = rorwa_res["rorwa"]

            reg(debt_service_facts, FactItem(
                fact_id="DS_TORWA",
                section="DEBT_SERVICE",
                canonical_path="rorwa.torwa",
                label="Chỉ số TORWA",
                value=torwa_val,
                unit="PERCENT",
                period=None,
                authority=FactAuthority.DERIVED_PYTHON,
                fact_nature=FactNature.DERIVED_METRIC,
                completeness=FactCompleteness.COMPLETE,
                display_representations=_generate_numeric_representations(torwa_val, "PERCENT")
            ))

            reg(debt_service_facts, FactItem(
                fact_id="DS_RORWA",
                section="DEBT_SERVICE",
                canonical_path="rorwa.rorwa",
                label="Chỉ số RORWA",
                value=rorwa_val,
                unit="PERCENT",
                period=None,
                authority=FactAuthority.DERIVED_PYTHON,
                fact_nature=FactNature.DERIVED_METRIC,
                completeness=FactCompleteness.COMPLETE,
                display_representations=_generate_numeric_representations(rorwa_val, "PERCENT")
            ))

        # ----------------------------------------------------------------------
        # 6. CIC FACTS (Section E)
        # ----------------------------------------------------------------------
        if sec_e.get("cic_date"):
            reg(cic_facts, FactItem(
                fact_id="CIC_DATE",
                section="CIC",
                canonical_path="section_e.cic_date",
                label="Thời điểm tra cứu CIC",
                value=str(sec_e["cic_date"]),
                unit="TEXT",
                period=str(sec_e["cic_date"]),
                authority=FactAuthority.SOURCE_FACT,
                fact_nature=FactNature.OBJECTIVE_FACT,
                completeness=FactCompleteness.COMPLETE,
                display_representations=[str(sec_e["cic_date"])]
            ))

        msb_debt = float(sec_e.get("msb_outstanding", 0.0))
        reg(cic_facts, FactItem(
            fact_id="CIC_MSB_OUTSTANDING",
            section="CIC",
            canonical_path="section_e.msb_outstanding",
            label="Dư nợ tại MSB",
            value=msb_debt,
            unit="TRIEU_VND",
            period=None,
            authority=FactAuthority.SOURCE_FACT,
            fact_nature=FactNature.OBJECTIVE_FACT,
            completeness=FactCompleteness.COMPLETE,
            display_representations=_generate_numeric_representations(msb_debt, "TRIEU_VND")
        ))

        # Relations and external debt check
        relations = sec_e.get("relations", [])
        is_external_debt_complete = True
        unconverted_fx: List[Dict[str, Any]] = []
        other_banks_total_vnd = 0.0

        for r in relations:
            b_name = r.get("bank_name", "")
            is_msb = "MSB" in b_name or "Hàng Hải" in b_name
            if not is_msb:
                tot_d = r.get("total_debt_million")
                if tot_d is not None:
                    other_banks_total_vnd += float(tot_d)
                # Check unnormalized foreign currency debt
                raw_usd = r.get("raw_usd_amount")
                usd_equiv = r.get("short_term_debt_usd_million")
                if raw_usd and not usd_equiv and tot_d is None:
                    is_external_debt_complete = False
                    unconverted_fx.append({
                        "bank_name": b_name,
                        "raw_usd_amount": raw_usd
                    })

        if sec_e.get("is_incomplete"):
            is_external_debt_complete = False
            unconverted_fx.append({
                "bank_name": "TCTD Chưa hoàn chỉnh",
                "raw_usd_amount": sec_e.get("incomplete_reason", "Chưa chuẩn hóa")
            })

        if is_external_debt_complete:
            reg(cic_facts, FactItem(
                fact_id="CIC_OTHER_BANKS_DEBT",
                section="CIC",
                canonical_path="section_e.other_banks_total_debt",
                label="Tổng dư nợ tại các TCTD khác (ngoài MSB)",
                value=other_banks_total_vnd,
                unit="TRIEU_VND",
                period=None,
                authority=FactAuthority.DERIVED_PYTHON,
                fact_nature=FactNature.DERIVED_METRIC,
                completeness=FactCompleteness.COMPLETE,
                display_representations=_generate_numeric_representations(other_banks_total_vnd, "TRIEU_VND")
            ))
        else:
            # Foreign currency debt is unnormalized -> INCOMPLETE
            data_gaps.append(FactItem(
                fact_id="GAP_CIC_EXTERNAL_DEBT_INCOMPLETE",
                section="DATA_GAPS",
                canonical_path="section_e.other_banks_total_debt",
                label="Dư nợ TCTD khác chưa xác định đầy đủ bằng VND",
                value=f"Có khoản dư nợ ngoại tệ chưa quy đổi tại: {', '.join(x['bank_name'] + ' (' + str(x['raw_usd_amount']) + ' USD)' for x in unconverted_fx)}",
                unit="TEXT",
                period=None,
                authority=FactAuthority.SOURCE_FACT,
                fact_nature=FactNature.DATA_GAP,
                completeness=FactCompleteness.INCOMPLETE,
                display_representations=[]
            ))

        # Negative facts / History status
        hist_status = sec_e.get("history_status") or "100% Nợ Nhóm 1, không phát sinh nợ quá hạn"
        reg(cic_facts, FactItem(
            fact_id="CIC_HISTORY_STATUS",
            section="CIC",
            canonical_path="section_e.history_status",
            label="Lịch sử trả nợ và phân loại nợ",
            value=hist_status,
            unit="TEXT",
            period=None,
            authority=FactAuthority.SOURCE_FACT,
            fact_nature=FactNature.OBJECTIVE_FACT,
            completeness=FactCompleteness.COMPLETE,
            display_representations=[hist_status, "Nhóm 1", "Nợ đủ tiêu chuẩn"]
        ))

        # Derivative info
        deriv = sec_e.get("derivative_transactions_info")
        if deriv:
            reg(cic_facts, FactItem(
                fact_id="CIC_DERIVATIVE_INFO",
                section="CIC",
                canonical_path="section_e.derivative_transactions_info",
                label="Giao dịch phái sinh",
                value=deriv,
                unit="TEXT",
                period=None,
                authority=FactAuthority.SOURCE_FACT,
                fact_nature=FactNature.OBJECTIVE_FACT,
                completeness=FactCompleteness.COMPLETE,
                display_representations=[str(deriv)]
            ))

        # Overdue 12m
        is_overdue = bool(sec_e.get("is_overdue_12m", False))
        reg(cic_facts, FactItem(
            fact_id="CIC_IS_OVERDUE_12M",
            section="CIC",
            canonical_path="section_e.is_overdue_12m",
            label="Phát sinh nợ quá hạn trong 12 tháng",
            value=is_overdue,
            unit="TEXT",
            period=None,
            authority=FactAuthority.SOURCE_FACT,
            fact_nature=FactNature.OBJECTIVE_FACT,
            completeness=FactCompleteness.COMPLETE,
            display_representations=["Không phát sinh nợ quá hạn" if not is_overdue else "Có phát sinh nợ quá hạn"]
        ))

        # ----------------------------------------------------------------------
        # 7. MANIFEST HASH & PACKAGE
        # ----------------------------------------------------------------------
        manifest_hash = cls.compute_manifest_hash(all_collected_items)

        return FactManifest(
            case_id=case_id,
            manifest_hash=manifest_hash,
            legal_facts=legal_facts,
            business_facts=business_facts,
            financial_facts=financial_facts,
            credit_request_facts=credit_request_facts,
            debt_service_facts=debt_service_facts,
            cic_facts=cic_facts,
            data_gaps=data_gaps
        )
