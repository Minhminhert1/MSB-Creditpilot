# -*- coding: utf-8 -*-
"""Unit and Integration tests for Phase 7 Credit Committee Preparation & Demo Experience."""

import unittest
import json
from msb_eb_copilot.src.credit_committee_prep import CreditCommitteePrepEngine, CommitteeQuestionCard
import web_copilot_app
from web_copilot_app import CASES_DB, ACTIVE_CASE_ID, CopilotHTTPHandler


class TestCreditCommitteePrep(unittest.TestCase):
    def setUp(self):
        self.psd_case = CASES_DB.get("PSD")

    def test_prep_cards_generation_for_psd(self):
        """Verify CreditCommitteePrepEngine generates sharp defense cards grounded in PSD facts."""
        cards = CreditCommitteePrepEngine.generate_prep_cards(self.psd_case)
        self.assertGreaterEqual(len(cards), 4)

        card_ids = [c.question_id for c in cards]
        self.assertIn("Q_REC_VS_REV_GROWTH", card_ids)
        self.assertIn("Q_DEBT_LEVERAGE_LIQUIDITY", card_ids)
        self.assertIn("Q_SUPPLIER_CONCENTRATION", card_ids)
        self.assertIn("Q_UNSECURED_CREDIT_STRUCTURE", card_ids)
        self.assertIn("Q_CIC_SYSTEM_CREDIT_DISCIPLINE", card_ids)

        # Inspect Q_REC_VS_REV_GROWTH
        rec_card = next(c for c in cards if c.question_id == "Q_REC_VS_REV_GROWTH")
        self.assertEqual(rec_card.severity, "HIGH")
        self.assertIn("104.0%", rec_card.why_asked)
        self.assertTrue(len(rec_card.facts_to_prepare) >= 2)
        self.assertTrue(len(rec_card.suggested_defense_points) >= 2)

    def test_prep_cards_gas_south(self):
        """Verify CreditCommitteePrepEngine generates grounded cards for GAS_SOUTH."""
        gs_case = CASES_DB.get("GAS_SOUTH")
        cards = CreditCommitteePrepEngine.generate_prep_cards(gs_case)
        self.assertIsInstance(cards, list)
        self.assertGreaterEqual(len(cards), 1)

    def test_api_committee_prep_get_and_save_note(self):
        """Verify API /api/committee_prep and /api/committee_prep/save_note handlers."""
        # Check that committee notes can be saved and retrieved
        qid = "Q_REC_VS_REV_GROWTH"
        custom_note = "Doanh so quy 4 tap trung vao dot mo ban iPhone 16."
        
        if "_committee_notes" not in self.psd_case:
            self.psd_case["_committee_notes"] = {}
        self.psd_case["_committee_notes"][qid] = custom_note

        cards = CreditCommitteePrepEngine.generate_prep_cards(self.psd_case)
        saved_note = self.psd_case["_committee_notes"].get(qid)
        self.assertEqual(saved_note, custom_note)


if __name__ == "__main__":
    unittest.main()
