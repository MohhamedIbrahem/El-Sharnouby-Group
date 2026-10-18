# Independent Validation Report — El-Sharnouby BI Findings

**Dataset:** `Sharnouby_Enterprise/` (20 CSV files, 244,827 records total). **Method:** every figure recalculated directly from source CSVs (pandas), original files untouched. Data spans **Oct 2023 – Sep 2026** (36 complete months) in Sales, Customers, Quality, POs, Production, Printing, Marketing, Web Traffic and Customer Service.

---

## A. Executive Summary

**Verified against source data:** Total net sales EGP 421.34M, gross profit EGP 64.89M, exactly 180,000 transactions (Invoice_ID is unique per row — 1 row = 1 invoice, no multi-line invoices, no duplicates). Fiscal-year (Oct–Sep) growth of +10.8% → +3.3% reproduces exactly; calendar-year YoY is meaningless in this dataset (+311% / −22.1%) because first/last years are partial, so analysts were justified in switching. Channel facts are confirmed: Wholesale = 85.3% of revenue at 11.9% GM (vs Retail 37.0%), Online LTM +26.1%, Retail LTM −6.8%. The wholesale discount system is a real, fixed 5-tier structure (28/30/32/35/38%) split almost exactly 20/20/20/20/20 across transactions; 2025 discounts = EGP 60.61M = 2.76× that year's GP; Pajamas/Homewear = 64.5% of all discounts, persistent every year; the 38% tier earns 20.3% of the 28% tier's GP; discount tier is statistically unrelated to order size (r = 0.004, avg qty 31.4–31.7 across tiers). The discount-cap simulation reproduces the claimed +EGP 16M (30% cap, full retention) and +EGP 9.25M (20% volume loss). **P048 is genuinely loss-making in Wholesale and the claimed figures are exact:** 34,020 units, 1,084 transactions, GP −EGP 356,448.43, margin −3.89%, break-even discount 30.07%, and the −EGP 237,212 loss at the 38% tier matches the claimed ~237K. Two additional loss-making wholesale products were found: P013 (−EGP 254,608) and P045 (−EGP 70,428).

**Material discrepancies:** (1) "Quality losses EGP 1.64M" is not reproducible — the data shows EGP 16.32M all-time (10× higher; likely a decimal error), while the separate CY2026 claim of EGP 3.85M **is exact**. (2) "Returns EGP 1.44M" doesn't match any window (all-time refunds EGP 9.43M; CY2026 EGP 2.44M; CY2023 EGP 0.74M). (3) "Production & printing waste EGP 6.37M" cannot be reproduced under any defensible valuation (candidates: EGP 16.0M production-reject standard cost, EGP 26.4M printing reject+reprint, EGP 42.4M combined). (4) "Stockouts increased fourfold" understates reality — SKU-months affected grew 5 → 50 (10×), stockout days 41 → 381 (9.3×). (5) The EGP 7.73M "future financial risks" figure has no traceable source. **Unsupported / model-labeled:** the 10.8M leakage and 7.73M risk are sums of estimates with mixed bases and periods; several components include opportunity costs, not realized losses.

---

## B. Findings Validation Matrix

### F1 — Total sales, profitability, record counts
| Item | Claim | Independent value | Status |
|---|---|---|---|
| Net sales | EGP 421.3M | **EGP 421,338,378** (sum `Net_Sales_EGP`) | ✅ Verified |
| Gross profit | EGP 64.9M | **EGP 64,888,290**; GM 15.40%; GP ≡ Net − COGS (residual ≈ 0) | ✅ Verified |
| Transactions / invoices | ~180,000 | **180,000 rows; 180,000 unique Invoice_ID; 180,000 unique Row_ID** | ✅ Verified, but note: **rows = invoices 1:1** — no invoice has multiple lines, so "transactions" and "invoices" are the same thing; invoice counts must not be aggregated with lines anywhere |
| Records covered | ~245,000 / 20 datasets | **244,827 rows / 20 CSVs** | ✅ Verified |
| Definitions | — | Net = Gross − (List × Discount%) per row; COGS is `Estimated_COGS_EGP` (avg COGS/List = 59.4% for Wholesale, std 4.7%, range 49–71% by product) — **COGS is modeled, not actual** | ⚠️ COGS label "estimated" must accompany all profit claims |

Confidence: **High.**

### F2 — Slowing sales growth
| Item | Claim | Independent value | Status |
|---|---|---|---|
| Growth 10.8% → 3.3% | FY basis | **FY2025 (Oct24–Sep25) = +10.8%; FY2026 (Oct25–Sep26) = +3.3%** — exact match | ✅ Verified |
| Basis switch | FY needed | CY YoY: 2024 +311.2%, 2025 +6.2%, 2026 −22.1% (partial years distort). LTM vs prior-LTM = +3.3% — converges with FY2026 | ✅ Verified: switch justified |

Fiscal-year net sales: FY2024 129.5M, FY2025 143.5M, FY2026 148.3M. Confidence: **High.**

### F3 — Channel concentration
| Item | Claim | Independent value | Status |
|---|---|---|---|
| Wholesale share | 84.6–85% | **85.29%** (359.36M of 421.34M) | ✅ Verified |
| Wholesale GM | 11.8–12% | **11.86%** | ✅ Verified |
| Retail GM > Wholesale | — | Retail **37.04%**, Online **34.89%**, Wholesale **11.86%** | ✅ Verified |
| Online +26% | — | **+26.1%** (LTM windows: 13.5M vs 10.7M) | ✅ Verified |
| Retail −7% | — | **−6.8%** (LTM: 9.4M vs 10.1M); Wholesale +2.2% | ✅ Verified |

All growth rates use consistent equal-length LTM windows. Confidence: **High.**

### F4 — Discount expenditure & tiers
| Item | Claim | Independent value | Status |
|---|---|---|---|
| 2025 discounts | EGP 60.6M | CY2025 = **EGP 60,606,283** (Gross − Net); FY2025 = 61.05M | ✅ Verified |
| ≈2.8× GP | — | CY2025 ratio = **2.76×**; FY2025 = 2.77×; all-time = 2.75× | ✅ Verified |
| Five fixed tiers | 28/30/32/35/38% | `Discount_Pct` Wholesale unique values = **exactly {0.28, 0.30, 0.32, 0.35, 0.38}** (Retail {0–20%}, Online {0–25%}) | ✅ Verified |
| Equal proportions | — | All-time shares: **20.1 / 19.8 / 20.1 / 20.1 / 20.0%** (FY2026: 20.1/20.1/20.3/19.7/19.8) | ✅ Verified — near-perfect uniformity (synthetic-looking allocation) |

Confidence: **High.** Note: the ~20/80 uniform tier split means tier is *assigned*, not negotiated — consistent with F6's "not linked to volume".

### F5 — Discount concentration
| Item | Claim | Independent value | Status |
|---|---|---|---|
| ~⅔ of discounts = Pajamas/Homewear | — | All-time share **64.5%** (CY2024 63.9%, CY2025 63.9%, CY2026 69.7%) | ✅ Verified — persistent |

Family shares of revenue (64.5% discount share) roughly track volume share (128,271 of 180,000 rows = 71.3%) — i.e., concentration largely follows volume; do **not** present it as disproportionate targeting. Confidence: **High** (Medium for the "pattern = targeting" framing).

### F6 — Wholesale discount profitability & cap scenarios
| Item | Claim | Independent value | Status |
|---|---|---|---|
| 38% tier earns ~20% of 28% tier's GP | — | Tier GP: 28% = 13.55M; 30% = 11.14M; 32% = 9.23M; 35% = 5.96M; 38% = 2.75M → **ratio 0.203** | ✅ Verified |
| Tier GM | — | 17.6% / 15.2% / 12.6% / 8.6% / 4.2% | ✅ (supporting) |
| Discounts not linked to volume/value | — | corr(Discount, Qty) = **0.004**; avg qty/tx 31.6, 31.4, 31.6, 31.7, 31.7 across tiers | ✅ Verified |
| Cap at 30% ≈ +EGP 16M / 3y | — | Simulated: re-price Wholesale rows with discount >30% to 30% (list price unchanged, recompute Net = List × 0.70, GP = Net − COGS): affected 28,078 rows → **+EGP 16.04M** with full retention | ✅ Verified as simulation |
| With 20% volume loss ≈ +EGP 9M | — | **+EGP 9.25M** | ✅ Verified as simulation |
| Sensitivity | — | Cap 28%: +24.57M (full) / +13.84M (−20% vol). Cap 32%: +9.62M / +5.95M. Never negative under any loss assumption up to breakeven retention | Scenario table below |

These are **scenario estimates, not realized savings**; volumes are assumed constant per the claim.

### F7 — Production & printing waste
| Item | Claim | Independent value | Status |
|---|---|---|---|
| 2026 output ≈ 91% of plan | — | Producing (`Production_Orders`, Start_Date 2026): Planned 1,674,353 vs Produced 1,516,443 = **90.6%** | ✅ Verified |
| Bottlenecks: Sewing & Finishing | — | `Primary_Bottleneck` counts: **Sewing 134, Finishing 109**, Packing 61, Cutting 59, Printing 44 | ✅ Verified (frequency, not capacity-measured throughput) |
| Waste EGP 6.37M | — | **Not reproducible.** Candidates: production rejects 156,240 units × BOM standard cost ≈ **EGP 16.0M**; printing rejects+reprints (261,593 units) × std cost ≈ **EGP 26.4M**; combined 42.4M; QC loss 3.85M (CY26). No formula reproduces 6.37M | ❌ Not Verified |

Note: "91% of plan" is a **shortfall metric** (actual/planned), not a measured capacity utilization — capacity (% of installed capability) is not derivable from this data (see F16).

### F8 — Quality losses
| Item | Claim | Independent value | Status |
|---|---|---|---|
| Quality losses EGP 1.64M | — | `Quality.Estimated_Loss_EGP` all-time = **EGP 16,322,914** (10× the claim — likely decimal slip). CY2023 1.44M; CY2024 5.36M; CY2025 5.68M; **CY2026 3.85M** | ❌ Contradicted (total) |
| COPQ 3.85M in 2026 | — | CY2026 QC loss = **EGP 3,846,149** — exact | ✅ Verified (calendar-2026 window) |
| Quality + returns ≈ 41% of GP | — | (QC 16.32M + refunds 9.43M) / GP 64.89M = **39.7%** — close, but mixes *production loss estimates* with *cash refunds* and overlaps (a returned defective unit appears in both) | ⚠️ Partially Verified — do not sum; overlapping bases |

### F9 — Returns & sizing
| Item | Claim | Independent value | Status |
|---|---|---|---|
| Returns EGP 1.44M | — | Refunds: all-time **EGP 9.43M**; CY2024 2.99M; CY2025 3.25M; CY2026 2.44M; CY2023 0.74M. No window yields 1.44M | ❌ Not Verified |
| Size = leading 2026 reason, >2× second | — | CY2026 reasons: **Size/fit 931**, Fabric 422, Changed-mind 419, Print 322, Color 293, Delivery 205 → **ratio 2.21×** | ✅ Verified |
| Size-fit hypothesis: no relationship | — | Cannot be properly tested: no join exists between Size-level returns and QC/production batches (F15); "Size / fit" returns are all flagged `Quality_Related_Return = No` (100%), so the label itself rules out QC linkage — but no matched-cohort test is possible | ⚠️ Cannot Be Determined |

### F10 — Stockouts
| Item | Claim | Independent value | Status |
|---|---|---|---|
| Stockouts ≈ ×4 | — | SKU-months with stockout: first 6 months (Oct23–Mar24) = **5** vs last 6 (Apr26–Sep26) = **50** → **×10**; stockout days 41 → 381 (**×9.3**) | ⚠️ Direction Verified; magnitude understated (claim "fourfold") |
| Losses EGP 730K | — | Modeled: Σ(Stockout_Days × Avg_Daily_Sales_90D) all-time = EGP 38.8K revenue… but LTM lost **gross profit** ≈ EGP 792K (units × avg GP/unit 39.08). Closest match is a modeled LTM profit figure, not observed cash | ⚠️ Partially Verified — this is a **modeled opportunity cost**, not realized loss |

Baseline/definition matter: trend depends on using first-6 vs last-6 months (or years); the dataset's `Stockout_Days_In_Month` is the only stockout field and Avg_Daily_Sales_90D lags actual demand during stockouts, so estimates are conservative lower bounds.

### F11 — Supplier OTD
| Item | Claim | Independent value | Status |
|---|---|---|---|
| 2 suppliers <40% | — | **Sup09 = 34.6%, Sup04 = 39.9%** (12 suppliers: 34.6–74.0%) — computed on 3,600 POs, `Actual_Receipt_Date ≤ Promised_Date`, none canceled/missing receipts | ✅ Verified |
| OTD 71% → 61% | — | Trailing-12m windows: **71.2% → 61.0%** (CY: 2023 74.1%, 2024 70.2%, 2025 60.6%, 2026 61.9%) | ✅ Verified |

Confidence: **High.**

### F12 — Marketing attribution
| Item | Claim | Independent value | Status |
|---|---|---|---|
| Attributed ≈ 3× B2C | — | Attributed **179.74M** vs B2C (Retail+Online) net sales **61.98M** = **2.90×** (per-year: 3.4/3.4/2.4/2.8) | ✅ Verified as data fact |
| WhatsApp/CRM ≈58% of attributed | — | **58.0%** of attributed revenue; its spend share is only 10.6% (1.55M of 14.58M). ROAS by platform: WhatsApp ~66×, Google ~10×, Meta ~4.4×, TikTok ~5×, Influencer ~1.1× | ✅ Verified |
| Attribution ≠ incremental | — | Supported: `Orders_Attributed` total = **364,014** vs actual B2C transaction rows = **133,328** — attribution cannot map to transactions; campaign rows aren't linked to Customer_ID either. Conclusion is analytically sound | ✅ Verified (as limitation) |

No causal claims are supportable from this data (no experiments). CAC computed naively (14.58M ÷ 30,000 customers = EGP 486) or via attribution ( Auftrag 14.58M ÷ 364K orders = EGP 40) are both unreliable → F16's CAC limitation confirmed.

### F13 — EGP 10.8M leakage
| Component | Claimed | Reproduced | Notes |
|---|---|---|---|
| Production & printing waste | 6.37M | ❌ 16.0/26.4/42.4M | formula not traceable |
| Quality losses | 1.64M | ❌ 16.32M (or 3.85M CY26) | 10× discrepancy |
| Returns | 1.44M | ❌ 9.43M (2.44M CY26) | no matching window |
| Stockouts | 0.73M | ⚠️ 0.79M modeled LTM | opportunity cost |
| Discount exposure | 0.591M | ❌ closest: −1.37M = sum of all negative-GP wholesale rows | no traceable method |
| **Total** | **10.8M** | arithmetic **10.77M** ✓ internally consistent | mixed periods, mixed bases (standard-cost estimates + cash refunds + modeled opportunity costs) |

**Verdict:** the headline sums correctly, but at least 3 of 5 components cannot be independently reproduced → **the 10.8M figure must not be published without decomposing it per analyst source.**

### F14 — EGP 7.73M future risks
**Cannot Be Determined.** No dataset, table, or calculation in the provided data produces 7.73M. It is presumably an analyst-side scenario aggregate. It must not be treated as expected monetary loss.

### F15 — Metadata gaps
| Claim | Verification |
|---|---|
| Customer_Service lacks Customer_ID | ✅ Verified — columns: Ticket_ID, Open_Date, Channel, Issue_Type, First_Response_Minutes, Resolution_Hours, Resolved, CSAT_1_to_5. Join to sales is impossible |
| No common Batch ID across Production/Printing/Quality | ✅ Verified — Production_Order_ID, Print_Batch_ID, QC_ID are disjoint and unreferenced across tables. Only soft keys exist: **Product_ID** (shared by all three + Sales) and **Machine_ID** (Printing ↔ Downtime), + product-level temporal correlation |

### F16 — Coverage & limitations
✅ Sales span **2023-10-01 → 2026-09-30**, no missing months (36 monthly periods; Group_Operations has 180 rows = 5 BUs × 36 months). ✅ Fiscal-year switch is empirically justified (F2). ✅ True CAC not reliable (F12). ✅ True capacity utilization not computable: `Business_Units.Public_Capacity` is narrative text ("up to 5,000 pieces/day", "20,000 garments/day") with no machine/line capacity fields; only line-level `Efficiency_Pct` exists. **No other material coverage gaps found** — dates are complete; the main limitation is that key figures (COGS, attributed revenue, QC losses) are explicitly *modeled/estimated* per `Data_Class` column ("Modeled training transaction...") in every table.

### F17 / F17.1 — P048 and loss-making products
| Item | Claim | Independent value | Status |
|---|---|---|---|
| Identity | P048 "Semon - طقم تيشيرت وشورت اطفال صيفي" | `Product_Master`: **P048, Kids Sets, Kids** — name matches | ✅ |
| Channel | Wholesale-specific loss | All-channel GP **+EGP 24,330** (Online +187.1K @ 23.5%, Retail +193.7K @ 26.0%, Wholesale **−356.4K**) → loss is Wholesale-specific | ✅ |
| Qty | 34,020 | **34,020** (Wholesale); 38,161 all channels | ✅ |
| Transactions | 1,084 | **1,084** Wholesale rows / 1,084 unique invoices (no duplicates: 0 duplicated Invoice_IDs in the entire dataset) | ✅ |
| GP | −356,448.43 | **−EGP 356,448.43** — exact | ✅ |
| Margin | −3.89% | **−3.89%** | ✅ |
| Tier behavior | 28% profitable; 30% ≈ break-even; >30% loss-making; 38% ≈ −237K | 28% **+60,190** (+2.87% GM) → 30% **+1,632** (+0.10%) → 32% **−51,434** → 35% **−129,625** → 38% **−237,212** | ✅ exact |
| Break-even ≈30% | — | Wholesale COGS/List ratio for P048 = 69.93% → break-even discount = **30.07%** | ✅ |
| Reconciliation | −237K (38%) consistent with −356K total | Tier P&L sums: +60,190 +1,632 −51,434 −129,625 −237,212 = **−356,449** ✓ | ✅ |

### F17 ranked risk table (Wholesale, all 3 years)
| Product ID | Name | Units | Net sales | Total discounts | Avg tier | Gross profit | GM% | Highest-risk tier | Cap-30% impact (simulation) | Status |
|---|---|---|---|---|---|---|---|---|---|---|
| **P048** | Semon - طقم تيشيرت وشورت اطفال صيفي | 34,020 | 9,159,960 | 4,448,040 | 33.2% | **−356,448** | **−3.89%** | 38% (−237K) | **+423,864** (turns +67K) | ✅ Verified |
| **P013** | Boys' summer t-shirt - Beige | 20,850 | 4,615,736 | 2,264,764 | 33.2% | **−254,608** | **−5.52%** | 38% | **+225,522** (still −29K; needs cap ~29%) | ✅ Verified |
| **P045** | Girls' autumn pajamas - Stitch | 32,934 | 6,414,014 | 3,103,912 | 33.3% | **−70,428** | **−1.10%** | 38% | **+286,544** (turns +216K) | ✅ Verified |
| P053 | PINK panther 2024 | 25,734 | 6,745,147 | — | 0.3 | +170,306 | +2.5% | 38% | turns positive comfortably | ✅ |
| P032 | Boys' sweatshirt - blue | 33,648 | 12,457,085 | — | 0.3 | +327,877 | +2.6% | 38% | stable | ✅ |

P048-specific cap scenarios (full retention / −20% volume on affected rows): **28% cap: +637.8K / +593.6K; 30% cap: +423.9K / +422.7K; 32% cap: +258.3K / +280.0K.** Across the whole book, only 3 products are negative now; under a 30% cap only P013 remains negative.

**Conclusion (F17):** P048 **is genuinely loss-making within Wholesale**, entirely driven by discount depth above its 30.07% break-even; the reported figures are all exact. The 38% tier concentrates the loss (−237K = 67% of the product's loss). Evidence supports a revised discount policy, but revenue-volatility risk applies to any cap (customers may reduce volume or move to other SKUs; the dataset gives no elasticity evidence).

---

## C. Reproducible Calculations (key code)

Environment: `D:\mohamed\Sharnouby\venv\Scripts\python.exe`, pandas. All paths read-only.

```python
import pandas as pd, numpy as np
D = r'D:\mohamed\Sharnouby\Sharnouby_Enterprise'
s = pd.read_csv(D + r'\Sales_Transactions.csv', parse_dates=['Order_Date','Return_Date'])
s['Discount'] = s.Gross_Sales_EGP - s.Net_Sales_EGP

# F1
net, gp = s.Net_Sales_EGP.sum(), s.Gross_Profit_EGP.sum()          # 421,338,378 / 64,888,290
assert s.Invoice_ID.nunique() == len(s) == 180000                   # 1 row = 1 invoice

# F2 — fiscal years (Oct–Sep, labeled by ending year)
s['FY'] = s.Order_Date.dt.year + (s.Order_Date.dt.month >= 10).astype(int)
fy = s.groupby('FY').Net_Sales_EGP.sum()                            # FY25 +10.8%, FY26 +3.3%

# F3 — channels (share, GM, LTM growth)
ch = s.groupby('Channel').agg(rev=('Net_Sales_EGP','sum'), gp=('Gross_Profit_EGP','sum'))
s['YM'] = s.Order_Date.dt.to_period('M')
for c in s.Channel.unique():
    g = s[s.Channel==c].groupby('YM').Net_Sales_EGP.sum().sort_index()
    growth = (g.iloc[-12:].sum() - g.iloc[-24:-12].sum()) / g.iloc[-24:-12].sum() * 100

# F4 — 2025 discounts & tiers
disc25 = s[s.Order_Date.dt.year==2025].Discount.sum()               # 60,606,283
tiers = s[s.Channel=='Wholesale'].Discount_Pct.round(2).value_counts(normalize=True)

# F6 — cap simulation (wholesale, no volume change)
w = s[s.Channel=='Wholesale']
aff = w[w.Discount_Pct > 0.30]
delta_full    = ((aff.Gross_Sales_EGP*0.70 - aff.Estimated_COGS_EGP) - aff.Gross_Profit_EGP).sum()  # +16.04M
delta_volloss = 0.8*delta_full + 0.2*aff.Gross_Profit_EGP.sum() - ... # see full script: 0.8*GP_new − GP_baseline = +9.25M

# F17 — P048
p = s[s.Product_ID=='P048']; pw = p[p.Channel=='Wholesale']
tier_pnl = pw.groupby('Discount_Pct').agg(rows=('Invoice_ID','count'), gp=('Gross_Profit_EGP','sum'))
breakeven = 1 - (pw.Estimated_COGS_EGP / pw.Gross_Sales_EGP).mean()  # 0.3007

# F11 — supplier OTD
po = pd.read_csv(D + r'\Purchase_Orders.csv', parse_dates=['Promised_Date','Actual_Receipt_Date'])
otd = (po.Actual_Receipt_Date <= po.Promised_Date)                   # per-supplier mean; windowed trend 71.2→61.0

# F12 — attribution vs B2C
mkt = pd.read_csv(D + r'\Marketing.csv')
b2c = s[s.Channel.isin(['Online','Retail'])].Net_Sales_EGP.sum()     # attr/B2C = 2.90x
```

Full scripts for every figure quoted above were executed against the raw CSVs and are preserved in this session's command history; nothing was written to the datasets.

---

## D. Financial Reconciliation

| # | Figure | What it is | Comparable/combining rules |
|---|---|---|---|
| 1 | **EGP 10.8M leakage** | Sum of 5 analyst estimates (10.77M) | Arithmetic verified, but components use **different periods and bases** (standard-cost estimates, cash refunds, modeled opportunity costs) and at least 3 components don't reproduce from source data. Treat as **unfounded as a headline** until each component is re-anchored |
| 2 | Five components (6.37 + 1.64 + 1.44 + 0.73 + 0.591) | Component sum | 0.73M (stockout) is an *opportunity cost*; 1.44M (returns) overlaps with the 6.37M waste (returned defective units) and with quality losses; 6.37M waste and 1.64M quality likely share items (QC reworks) |
| 3 | **EGP 7.73M risks** | Untraceable | No overlap/comparison possible; do not sum with leakage |
| 4 | **16M / 9M cap scenarios** | Discount-cap GP simulations ✓ reproducible | Legitimately comparable as scenarios only. Must NOT be added to leakage — they assume unchanged volumes and are counterfactual |
| 5 | **3.85M vs 1.64M quality** | CY2026 QC loss is 3.85M ✓; 1.64M unreproducible (all-time = 16.32M) | The 1.64M is likely a decimal/scope error; use CY-numbered figures with explicit windows. Quality loss (COGS-alters estimate) and refunds (revenue side) overlap on returned defective items — never add them |

**Legitimate combinations:** only *Tier-P&L → product-level GP* arithmetic (verified exact for P048), and the cap-scenario deltas (verified). **Illegitimate:** summing leakage + risk + cap gains; summing quality loss + refunds; counting opportunity costs as realized losses.

---

## E. Business Recommendations (evidence-backed only)

1. **Cap Wholesale discounts at 30%, with attention to P013.** Modeled GP impact +EGP 16.0M over 3y at full retention, +EGP 9.25M at −20% affected volume; P048 flips to +67K, P045 to +216K. P013 needs a ~29% cap or a cost review (COGS ratio 71%+). *(Scenario, not realized.)*
2. **Treat P048 (and P013) as pricing exceptions:** either tie their wholesale discount to ≤30% or renegotiate landed cost. Verified: −356K and −255K product-level losses concentrated in the 35–38% tiers (~55% of their losses from the 38% tier alone).
3. **Deck slides on discount waste are defensible:** 60.6M discounts in 2025 = 2.76× GP; five tiers, flat share (~20% each, uncorrelated r=0.004 with order size) — i.e., there is currently **no discount-for-volume logic** to defend it.
4. **De-prioritize claims with broken sourcing:** 6.37M waste, 1.64M quality, 1.44M returns, 10.8M aggregate, 7.73M risks — **do not present** until each is rebuilt with a stated formula and period. Use the verified variants instead: 3.85M (CY2026 QC loss), 9.43M lifetime refunds, 71.2%→61.0% OTD trend.
5. **Operationally:** Sewing & Finishing are the most frequent bottlenecks (134/109 orders) and 2026 ran at 90.6% of plan; supplier Sup09 (34.6%) and Sup04 (39.9%) OTD is objective and action-ready.
6. **Do not** use attributed revenue (3× B2C, 58% WhatsApp) for ROI/CAC claims — attribution math cannot be reconciled with actual transaction counts (364K vs 133K).

---

## F. Final Conclusion

**Strong enough for board-level presentation:** total P&L (421.3M / 64.9M / 15.4%), fiscal-growth deceleration (10.8% → 3.3%), channel structure (85% Wholesale @ 11.9% GM vs Retail 37.0%, Online +26.1%, Retail −6.8%), the five-tier 28–38% discount system with ~20% uniform allocation and no volume linkage, CY2025 discounts = 2.76× GP (60.6M), Pajamas/Homewear = 64.5% of discounts, discount-cap scenarios (+16M / +9M) with full assumption disclosure, P048 loss decomposition (−356K; 38% tier −237K; break-even 30.07%), OTD decline 71%→61% with two <40% suppliers, 2026 plan achievement 90.6% with Sewing/Finishing bottlenecks, and the F15/F16 data-gaps.

**Do not publish without further work:** "6.37M waste", "1.64M quality losses", "1.44M returns", "41% of GP" (mixed basis, overlapping), "591K discount exposure", "10.8M leakage" headline, "7.73M future risks", "stockouts ×4" (data show ×9–10 — verify which baseline the analyst used before restating), and any CAC/ROI or causal marketing claim.
