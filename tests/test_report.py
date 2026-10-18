"""
Unit tests for the BI Report feature (app/services/report.py).

Three layers:
1. GRACEFUL   — empty / minimal data must never crash the report.
2. FORMULAS   — hand-computed oracle values for the documented `_calc_*`
                helpers on a tiny synthetic fixture (exact arithmetic).
3. REAL-DATA  — oracle values validated against the source CSVs
                (validation_report.md). These tests are skipped when the
                Sharnouby_Enterprise dataset folder is not present.

Run:  venv\\Scripts\\python -m unittest tests.test_report -v
"""
import json
import math
import re
import unittest
from pathlib import Path

import pandas as pd

from app.services.report import (
    SEVERITY_ORDER, VALID_SCOPES, VALID_SEVERITIES,
    AnalysisStatus, ReportContext, ReportFinding, EvidenceItem,
    build_report, build_markdown, get_report_context,
    _calc_cap_scenario, _calc_discount_system, _calc_loss_makers,
    _calc_fiscal_trend, _calc_stockouts, _first_ev,
)

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "Sharnouby_Enterprise"
HAS_REAL_DATA = DATA_DIR.exists() and any(DATA_DIR.glob("*.csv"))


def _sales_frame(rows: list[dict]) -> pd.DataFrame:
    """Minimal Sales_Transactions stand-in with every column `_calc_*` reads."""
    base = {
        "Invoice_ID": None, "Product_ID": None, "Channel": None,
        "Order_Date": None, "Quantity": None,
        "Discount_Pct": None, "Gross_Sales_EGP": None, "Net_Sales_EGP": None,
        "Gross_Profit_EGP": None, "Estimated_COGS_EGP": None,
        "Returned": "No", "Return_Reason": "", "Refund_Value_EGP": 0.0,
    }
    df = pd.DataFrame([{**base, **r} for r in rows])
    df["Order_Date"] = pd.to_datetime(df["Order_Date"])
    return df


class GracefulDegradationTests(unittest.TestCase):
    """Empty / minimal inputs must produce a usable report, never a crash."""

    def test_empty_data_builds_empty_report(self):
        ctx = build_report({})
        self.assertIsInstance(ctx, ReportContext)
        self.assertEqual(ctx.period_label, "")
        self.assertGreaterEqual(len(ctx.exec_summary), 1)  # fallback bullet
        self.assertIn("No analytical findings", ctx.exec_summary[0])
        self.assertIsInstance(ctx.executive_kpis, list)   # zero-value cards are allowed
        self.assertEqual(ctx.dataset_coverage, [])

    def test_empty_data_markdown_renders(self):
        md = build_markdown(build_report({}))
        self.assertIn("# El-Sharnouby Group", md)
        self.assertIn("## A. Executive Summary", md)
        self.assertIn("No analytical findings could be produced", md)
        self.assertIn("No datasets were visible to this report", md)

    def test_callers_receive_empty_dicts_not_errors(self):
        empty = pd.DataFrame()
        for fn in (_calc_discount_system, _calc_loss_makers, _calc_fiscal_trend):
            self.assertEqual(fn(empty), {})
        self.assertEqual(_calc_cap_scenario(empty, 0.30), {"cap": 0.30})
        self.assertEqual(_calc_stockouts(empty, empty), {})

    def test_minimal_synthetic_sales_finds_numbers(self):
        sales = _sales_frame([
            dict(Invoice_ID="A1", Product_ID="P01", Channel="Wholesale",
                 Order_Date="2025-06-15", Quantity=2, Discount_Pct=0.35,
                 Gross_Sales_EGP=1000, Net_Sales_EGP=650,
                 Gross_Profit_EGP=350, Estimated_COGS_EGP=300),
            dict(Invoice_ID="A2", Product_ID="P01", Channel="Wholesale",
                 Order_Date="2025-06-20", Quantity=1, Discount_Pct=0.35,
                 Gross_Sales_EGP=1000, Net_Sales_EGP=650,
                 Gross_Profit_EGP=350, Estimated_COGS_EGP=300),
            dict(Invoice_ID="A3", Product_ID="P02", Channel="Wholesale",
                 Order_Date="2025-07-01", Quantity=5, Discount_Pct=0.35,
                 Gross_Sales_EGP=200, Net_Sales_EGP=130,
                 Gross_Profit_EGP=-130, Estimated_COGS_EGP=260),
            dict(Invoice_ID="A4", Product_ID="P03", Channel="Retail",
                 Order_Date="2025-06-18", Quantity=1, Discount_Pct=0.10,
                 Gross_Sales_EGP=100, Net_Sales_EGP=90,
                 Gross_Profit_EGP=40, Estimated_COGS_EGP=50),
        ])
        ctx = build_report({"Sales_Transactions": sales})
        self.assertTrue(ctx.exec_summary)
        md = build_markdown(ctx)
        self.assertIn("EGP 110", md)   # F02 modeled cap gain on this fixture
        self.assertIn("P02", md)       # F03 loss-maker on this fixture


class FormulaOracleTests(unittest.TestCase):
    """Hand-computed exact arithmetic on the documented formulas (fixture above)."""

    @classmethod
    def setUpClass(cls):
        cls.sales = _sales_frame([
            dict(Invoice_ID="A1", Product_ID="P01", Channel="Wholesale",
                 Order_Date="2025-06-15", Quantity=2, Discount_Pct=0.35,
                 Gross_Sales_EGP=1000, Net_Sales_EGP=650,
                 Gross_Profit_EGP=350, Estimated_COGS_EGP=300),
            dict(Invoice_ID="A2", Product_ID="P01", Channel="Wholesale",
                 Order_Date="2025-06-20", Quantity=1, Discount_Pct=0.35,
                 Gross_Sales_EGP=1000, Net_Sales_EGP=650,
                 Gross_Profit_EGP=350, Estimated_COGS_EGP=300),
            dict(Invoice_ID="A3", Product_ID="P02", Channel="Wholesale",
                 Order_Date="2025-07-01", Quantity=5, Discount_Pct=0.35,
                 Gross_Sales_EGP=200, Net_Sales_EGP=130,
                 Gross_Profit_EGP=-130, Estimated_COGS_EGP=260),
            dict(Invoice_ID="A4", Product_ID="P03", Channel="Retail",
                 Order_Date="2025-06-18", Quantity=1, Discount_Pct=0.10,
                 Gross_Sales_EGP=100, Net_Sales_EGP=90,
                 Gross_Profit_EGP=40, Estimated_COGS_EGP=50),
        ])

    def test_cap_scenario_arithmetic(self):
        """delta_full = Σ(Gross×(1−cap) − COGS) − ΣGP_affected, etc."""
        out = _calc_cap_scenario(self.sales, cap=0.30, volume_loss=0.2)
        # new_gp per affected row: 1000×0.7−300 = 400 (twice), 200×0.7−260 = −120
        self.assertEqual(out["affected_rows"], 3)
        self.assertAlmostEqual(out["delta_full"], 400 + 400 - 120 - (350 + 350 - 130))
        self.assertAlmostEqual(out["delta_volume"], 0.8 * 680 - 570)
        self.assertAlmostEqual(out["breakeven_volume_loss"], 1 - 570 / 680)

    def test_break_even_uses_gross_not_net(self):
        out = _calc_loss_makers(self.sales)
        self.assertEqual(out["products_evaluated"], 2)   # wholesale products only (P01, P02)
        worst = out["worst"]
        self.assertEqual(worst["id"], "P02")
        self.assertAlmostEqual(worst["gp"], -130)
        self.assertAlmostEqual(worst["gm"], -130 / 130)
        # d* = 1 − ΣCOGS/ΣGross = 1 − 260/200 (negative: product can't break even)
        self.assertAlmostEqual(worst["breakeven"], 1 - 260 / 200)

    def test_discount_system_windows(self):
        out = _calc_discount_system(self.sales)
        self.assertAlmostEqual(out["cy2025_discounts_all"], 350 + 350 + 70 + 10)
        self.assertAlmostEqual(out["cy2025_gp_all"], 350 + 350 - 130 + 40)
        self.assertAlmostEqual(out["cy2025_discounts"], 770)          # wholesale only
        self.assertAlmostEqual(out["cy2025_gp"], 570)
        self.assertAlmostEqual(out["cy2025_ratio"], 770 / 570)
        tiers = out["tiers"]
        self.assertEqual(list(tiers.index), [0.35])
        self.assertAlmostEqual(float(tiers["share"].iloc[0]), 1.0)
        # constant discount → correlation undefined → must be omitted, never NaN
        self.assertNotIn("corr_tier_qty", out)

    def test_fiscal_year_windows_ignore_partial_years(self):
        """FY = Oct–Sep labeled by ending year; growth only between full 12-month pairs."""
        rows = []
        # FY2024: Oct 2023 – Sep 2024, 100/month → 1,200
        for d in pd.date_range("2023-10-01", "2024-09-01", freq="MS"):
            rows.append((d, 100.0))
        # FY2025: Oct 2024 – Sep 2025, 110/month → 1,320
        for d in pd.date_range("2024-10-01", "2025-09-01", freq="MS"):
            rows.append((d, 110.0))
        # partial edges
        rows.append((pd.Timestamp("2022-11-01"), 500.0))   # FY2022: 1 month
        rows.append((pd.Timestamp("2025-10-01"), 90.0))    # FY2026: 1 month
        sales = _sales_frame([
            dict(Invoice_ID=f"X{i}", Product_ID="P1", Channel="Wholesale",
                 Order_Date=d, Quantity=1, Discount_Pct=0.0,
                 Gross_Sales_EGP=v, Net_Sales_EGP=v,
                 Gross_Profit_EGP=0, Estimated_COGS_EGP=0)
            for i, (d, v) in enumerate(rows)
        ])
        out = _calc_fiscal_trend(sales)
        self.assertEqual(set(out["fy_growth"]), {"2025"})
        self.assertAlmostEqual(out["fy_growth"]["2025"], 1320 / 1200 - 1)

    def test_stockouts_requires_twelve_months(self):
        inv = pd.DataFrame({
            "Snapshot_Month": pd.to_datetime(pd.date_range("2024-01-01", periods=6, freq="MS")),
            "Stockout_Days_In_Month": [1, 2, 0, 3, 0, 4],
        })
        self.assertEqual(_calc_stockouts(inv, self.sales), {})


@unittest.skipUnless(HAS_REAL_DATA, "real dataset (Sharnouby_Enterprise/) not present")
class RealDataOracleTests(unittest.TestCase):
    """Figures independently validated against the source CSVs (validation_report.md)."""

    @classmethod
    def setUpClass(cls):
        from app.core.data_loader import load_all_data
        cls.data = load_all_data(DATA_DIR)
        cls.ctx = build_report(cls.data)
        cls.md = build_markdown(cls.ctx)
        cls.f = {x.id: x for x in cls.ctx.findings}

    def test_period_and_coverage(self):
        self.assertIn("36 complete months", self.ctx.period_label)
        self.assertEqual(len(self.ctx.dataset_coverage), 20)
        names = {d["table"] for d in self.ctx.dataset_coverage}
        self.assertIn("Sales_Transactions", names)
        self.assertEqual(sum(d["rows"] for d in self.ctx.dataset_coverage if d["table"] == "Sales_Transactions"), 180000)

    def test_all_sixteen_findings_present_and_well_formed(self):
        ids = [f"F{i:02d}" for i in range(1, 17)]
        for fid in ids:
            self.assertIn(fid, self.f, f"{fid} missing — finding builders must all fire on full data")
            f = self.f[fid]
            self.assertIn(f.severity, VALID_SEVERITIES)
            self.assertIn(f.scope, VALID_SCOPES)
            self.assertTrue(f.evidence, f"{fid} has no evidence rows")
            self.assertTrue(f.finding and f.interpretation and f.impact and f.action)
            self.assertTrue(f.source, f"{fid} has no traceable source")

    def test_findings_sorted_by_severity(self):
        order = [SEVERITY_ORDER[f.severity] for f in self.ctx.findings]
        self.assertEqual(order, sorted(order))

    def test_f01_discount_oracle(self):
        ev = self.f["F01"].evidence
        self.assertEqual(ev[0].value, "EGP 60,606,283")
        self.assertEqual(ev[1].value, "2.76×")
        self.assertIn("28%, 30%, 32%, 35%, 38%", ev[4].value)
        self.assertIn("20.", ev[5].value)                     # ~20% per tier
        self.assertIn("r = 0.004", ev[6].value)
        self.assertIn("0.20×", ev[7].value)                   # tier GP top/bottom ratio

    def test_f02_cap_scenario_oracle(self):
        ev = self.f["F02"].evidence
        self.assertEqual(ev[0].value, "EGP 16,044,166")       # cap 30%, full retention
        self.assertEqual(ev[1].value, "EGP 9,247,527")        # cap 30%, −20% volume
        self.assertIn("28,078", ev[2].value)                  # affected rows
        self.assertEqual(ev[3].value, "EGP 24,565,203")       # cap 28%, full retention
        self.assertEqual(ev[4].value, "EGP 13,836,126")       # cap 28%, −20% volume

    def test_f03_loss_makers_oracle(self):
        ev = self.f["F03"].evidence
        self.assertIn("59", ev[0].value)                      # products evaluated
        self.assertIn("3", ev[1].value)                       # loss-makers count
        self.assertEqual(ev[2].value, "EGP -356,448")         # P048 cumulative GP
        self.assertEqual(ev[3].value, "-3.9%")                # P048 GM
        self.assertEqual(ev[4].value, "30.1%")                # break-even discount
        self.assertIn("P013", self.md)
        self.assertIn("P045", self.md)

    def test_f04_growth_oracle(self):
        ev = self.f["F04"].evidence
        self.assertEqual(ev[0].value, "10.8%")                # FY2025 growth
        self.assertEqual(ev[1].value, "3.3%")                 # FY2026 growth

    def test_f05_channel_oracle(self):
        ev = self.f["F05"].evidence
        self.assertEqual(ev[0].value, "26.1%")                # online LTM growth
        self.assertEqual(ev[1].value, "-6.8%")                # retail LTM growth
        self.assertEqual(ev[2].value, "85.3%")                # wholesale share
        self.assertEqual(ev[3].value, "11.9%")                # wholesale GM

    def test_f06_quality_oracle(self):
        self.assertEqual(self.f["F06"].evidence[0].value, "EGP 16,322,914")
        self.assertEqual(self.f["F06"].evidence[1].value, "EGP 3,846,149")

    def test_f07_returns_oracle(self):
        ev = self.f["F07"].evidence
        self.assertEqual(ev[0].value, "EGP 9,427,006")
        self.assertEqual(ev[1].value, "EGP 2,441,200")
        joined = " | ".join(e.value for e in ev)
        self.assertIn("Size / fit", joined)
        self.assertIn("931 invoices", joined)

    def test_f08_stockouts_oracle(self):
        ev = self.f["F08"].evidence
        self.assertEqual(ev[0].value, "5")
        self.assertEqual(ev[1].value, "50")
        self.assertEqual(ev[2].value, "×10.0")
        self.assertEqual(ev[3].value, "41 → 381")

    def test_f09_suppliers_oracle(self):
        ev = self.f["F09"].evidence
        self.assertEqual(ev[0].value, "61.3%")                # most recent 12 months
        self.assertEqual(ev[1].value, "71.3%")                # initial 12 months
        weak = " | ".join(f"{e.label}: {e.value}" for e in ev[3:])
        self.assertIn("SUP09", weak)
        self.assertIn("34.6%", weak)
        self.assertIn("SUP04", weak)

    def test_f10_production_oracle(self):
        ev = self.f["F10"].evidence
        self.assertEqual(ev[0].value, "1,674,353")
        self.assertEqual(ev[1].value, "1,516,xx".replace("xx", "443"))
        self.assertEqual(ev[2].value, "90.6%")

    def test_f11_marketing_oracle(self):
        ev = self.f["F11"].evidence
        self.assertEqual(ev[0].value, "EGP 179,741,957")
        self.assertEqual(ev[2].value, "2.90×")
        self.assertEqual(ev[3].value, "364,014")
        self.assertEqual(ev[4].value, "133,328")

    def test_f12_value_chain_oracle(self):
        ev = self.f["F12"].evidence
        self.assertRegex(ev[0].value, r"30\.\d+M EGP")
        self.assertRegex(ev[1].value, r"7\.\d+")

    def test_f13_anomaly_oracle(self):
        self.assertIn("9 of 59 (15%)", self.f["F13"].evidence[0].value)

    def test_f14_segments_oracle(self):
        self.assertEqual(self.f["F14"].evidence[0].value, "25,634")

    def test_f15_forecast_oracle(self):
        ev = self.f["F15"].evidence
        self.assertIn("13 weekly steps", ev[0].value)
        self.assertEqual(self.f["F15"].scope, "prediction")
        self.assertIn("PREDICTION", ev[5].value)

    def test_f16_service_oracle(self):
        ev = self.f["F16"].evidence
        self.assertEqual(ev[0].value, "6,500")
        self.assertEqual(ev[1].value, "95.1%")

    def test_no_fabricated_numeric_leakage(self):
        """No NaN/'None'-as-value tokens in the exported Markdown."""
        clean = self.md.replace("'None' excluded", "")
        self.assertNotIn("NaN", clean)
        self.assertNotIn(" nan ", clean)
        self.assertFalse(re.search(r"\bnan\b", clean))
        self.assertNotIn("None", clean)
        self.assertNotIn("None\n", clean)

    def test_markdown_sections_and_links(self):
        for header in ("## A. Executive Summary", "## B. Key Findings and Evidence",
                       "## C. Financial and Sales Analysis", "## D. Operational Analysis",
                       "## E. AI and Advanced Analytics Findings",
                       "## F. Business Risks and Opportunities",
                       "## G. Recommended Actions", "## H. Data Coverage and Limitations"):
            self.assertIn(header, self.md)
        for fid in [f"F{i:02d}" for i in range(1, 17)]:
            self.assertIn(f"### {fid} —", self.md)

    def test_markdown_is_deterministic(self):
        self.assertEqual(self.md, build_markdown(self.ctx))

    def test_json_export_serializes(self):
        payload = self.ctx.to_dict()
        text = json.dumps(payload, ensure_ascii=False)
        loaded = json.loads(text)
        self.assertEqual(loaded["period"]["label"], self.ctx.period_label)
        self.assertEqual(len(loaded["findings"]), len(self.ctx.findings))
        self.assertIn("limitations", loaded)

    def test_risks_and_recommendations_reference_real_findings(self):
        known = set(self.f)
        for r in self.ctx.risks:
            self.assertIn(r.priority, {"High", "Medium", "Low"})
            self.assertTrue(r.evidence)
            self.assertTrue(set(r.linked_findings) <= known, f"risk links {r.linked_findings}")
        for o in self.ctx.opportunities:
            self.assertTrue(set(o.linked_findings) <= known)
        for rec in self.ctx.recommendations:
            self.assertTrue(set(rec.references) <= known, f"{rec.id} references {rec.references}")
            self.assertTrue(rec.metric_to_monitor and rec.evaluation)

    def test_analyses_status_documents_impossibilities(self):
        impossible = {a.name for a in self.ctx.analyses_status if a.status == "not possible"}
        self.assertIn("Causal lift of marketing channels", impossible)
        self.assertIn("Capacity utilization", impossible)
        self.assertIn("Forecast accuracy (holdout back-test)", impossible)

    def test_limitations_state_the_modeling_assumptions(self):
        text = " ".join(l["statement"] for l in self.ctx.limitations)
        self.assertIn("counterfactual", text)
        self.assertIn("Estimated_COGS_EGP", text)
        self.assertIn("never crude-summed" if False else "never summed", text)
        self.assertIn("not capacity utilization", text)

    def test_dataset_coverage_reports_all_tables(self):
        self.assertEqual(len(self.ctx.dataset_coverage), 20)
        sales_row = next(d for d in self.ctx.dataset_coverage if d["table"] == "Sales_Transactions")
        self.assertEqual(sales_row["rows"], 180000)
        self.assertIn("2023", sales_row["coverage"])

    def test_exec_summary_bullets_are_data_driven(self):
        self.assertGreaterEqual(len(self.ctx.exec_summary), 8)
        text = " ".join(self.ctx.exec_summary)
        self.assertIn("EGP 60,606,283", text)     # F01 headline
        self.assertIn("EGP 16,044,166", text)     # F02 headline
        self.assertIn("×10.0", text)              # F08 escalation
        self.assertIn("71.3% to 61.3%", text)     # F09 direction (fell from → to)


class StructureTests(unittest.TestCase):
    """Report-entry caching and object contracts (no dataset needed)."""

    def test_get_report_context_caches_on_same_data_object(self):
        data = {}  # any object works; keying is by identity+shape
        ctx1 = get_report_context(data)
        ctx2 = get_report_context(data)
        self.assertIs(ctx1, ctx2)

    def test_dataclasses_roundtrip(self):
        item = EvidenceItem("label", "value", "source")
        f = ReportFinding("F99", "t", "low", "actual", "c", "text", [item], "i", "imp", "a", "s")
        self.assertEqual(f.to_dict()["evidence"][0]["value"], "value")
        s = AnalysisStatus("x", "executed", "d")
        self.assertEqual(s.to_dict(), {"name": "x", "status": "executed", "detail": "d"})

    def test_first_ev_is_index_safe(self):
        f = ReportFinding("F98", "t", "low", "actual", "c", "text", [], "i", "imp", "a", "s")
        self.assertEqual(_first_ev(f, 3), "n/a")


if __name__ == "__main__":
    unittest.main()
