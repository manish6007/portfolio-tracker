"""Snapshot export: JSON + PDF, with a privacy-safe mode for AI review.

Privacy-safe mode strips owner names, folio/account numbers, and bank/AMC
names while keeping every number that matters for portfolio analysis.
"""
import io
import json
from datetime import date

import analytics
from db import ASSET_CLASS_LABELS

CLAUDE_PROMPT = """You are an experienced fee-only financial planner reviewing
an Indian household's portfolio snapshot (all amounts in INR). Analyze it and
give an educational review (not personalized investment advice):

1. Asset allocation: actual vs the stated target; what drift matters and why.
2. Portfolio construction: concentration risks, fund overlap by category,
   too-many-schemes problems, debt-vs-equity balance for the apparent life stage.
3. Cashflow: is the savings rate healthy? Where could the monthly surplus go
   given the allocation gaps (asset-class level only, no specific products)?
4. Liabilities: does prepaying any loan beat investing, at the stated rates?
5. Tax efficiency: 80C/80CCD headroom, LTCG awareness (educational only).
5b. Insurance: is life and health cover adequate for the dependants and debt,
   and is any of it investment-linked cover that would be cheaper as term?
6. Emergency fund adequacy versus monthly committed outflows, and whether
   the `financial_independence` projection's assumptions are reasonable --
   returns, inflation, step-up, the expense multiple, and whether post-FI
   spending is realistically modelled.
7. Top 5 concrete action items, ordered by impact.

Before advising, read `data_quality`: it states how many months each average
rests on, whether income is net or gross, how committed money splits between
payroll deductions and chosen SIPs, and what the tracker itself believes is
inconsistent or missing. Where a figure is flagged as unknown, ask rather than
assume it. `committed_outflows` lists each commitment as actually billed, and
`bucket_split_pct` shows any fund counted across several asset classes.

Snapshot follows below.
"""


def _mask(s, keep=4):
    s = str(s or "")
    if len(s) <= keep:
        return "*" * len(s)
    return "*" * (len(s) - keep) + s[-keep:]


def build_snapshot(holdings, loans, cashflow, drift, sugg, targets,
                   privacy_safe=True, as_of=None, recurring=None,
                   warnings=None, income_basis="", fi=None,
                   insurance=None, policies=None):
    """Assemble the full export dict from pre-computed pieces.

    Everything a reviewer would otherwise have to assume is stated: how the
    committed money splits between payroll and chosen SIPs, the actual
    recurring outflows rather than one aggregate, loan rates, how many months
    of data each average rests on, and what the app itself thinks is
    inconsistent about the data.
    """
    as_of = as_of or date.today()
    recurring = recurring or []
    warnings = warnings or []
    agg = analytics.aggregate(holdings, as_of)
    total_liab = sum(loan["principal_outstanding"] for loan in loans)

    hold_rows = []
    owner_alias = {}
    for h in holdings:
        owner = h.get("owner") or "Unassigned"
        if privacy_safe:
            owner_alias.setdefault(owner, "Member %d" % (len(owner_alias) + 1))
        hold_rows.append({
            "owner": owner_alias.get(owner, owner),
            "asset_class": ASSET_CLASS_LABELS.get(h["asset_class"], h["asset_class"]),
            "name": ("(hidden)" if privacy_safe and h["asset_class"] in
                     ("savings", "fd", "epf", "ppf", "nps") else h.get("name", "")),
            "identifier": _mask(h.get("identifier")) if privacy_safe else h.get("identifier", ""),
            "bucket": analytics.holding_bucket(h),
            "bucket_split_pct": ({k: round(v * 100, 1) for k, v in
                                  analytics.holding_splits(h).items()}
                                 if analytics.has_split(h) else None),
            "invested": round(analytics.holding_cost(h), 2),
            "current_value": round(analytics.holding_value(h, as_of), 2),
            "unrealised": round(analytics.holding_value(h, as_of)
                                - analytics.holding_cost(h), 2),
            "term": analytics.holding_term(h, as_of)[0],
            "rate_pct": h.get("rate") or None,
        })

    loan_rows = [{
        "name": ("%s loan" % loan.get("kind", "other")) if privacy_safe else loan.get("name", ""),
        "kind": loan.get("kind"),
        "outstanding": round(loan["principal_outstanding"], 2),
        "annual_rate_pct": loan.get("annual_rate"),
        "emi": loan.get("emi"),
        "tenure_months_remaining": loan.get("tenure_months_remaining"),
    } for loan in loans]

    return {
        "as_of": as_of.isoformat(),
        "currency": "INR",
        "privacy_safe": privacy_safe,
        "summary": {
            "total_assets": round(agg["total"], 2),
            "total_liabilities": round(total_liab, 2),
            "net_worth": round(agg["total"] - total_liab, 2),
            "by_asset_class": {ASSET_CLASS_LABELS.get(k, k): round(v, 2)
                               for k, v in agg["by_class"].items()},
            "by_owner": ({owner_alias.get(k, k): round(v, 2)
                          for k, v in agg["by_owner"].items()}),
            "by_bucket": {k: round(v, 2) for k, v in agg["by_bucket"].items()},
        },
        "target_allocation_pct": targets,
        "allocation_drift": [{k: (round(v, 2) if isinstance(v, float) else v)
                              for k, v in d.items()} for d in drift],
        "holdings": hold_rows,
        "liabilities": loan_rows,
        "monthly_cashflow": {k: round(v, 2) for k, v in cashflow.items()},
        "committed_outflows": [{
            "name": r.get("name"),
            "kind": r.get("kind"),
            "treated_as": ("investment" if r.get("counts_as_investment")
                           else "expense"),
            "payroll_deduction": r.get("kind") in analytics.PAYROLL_KINDS,
            "amount_per_payment": round(r.get("amount") or 0, 2),
            "frequency": r.get("frequency"),
            "amount_monthly": round(r.get("amount_monthly") or 0, 2),
            "amount_annual": round(analytics.to_annual(
                r.get("amount") or 0, r.get("frequency")), 2),
            "next_due": r.get("next_due"),
        } for r in recurring],
        "unrealised": analytics.unrealised_positions(holdings, as_of)["totals"],
        "financial_independence": fi,
        "insurance": (dict(insurance or {}, policies_detail=[{
            "kind": p.get("kind"),
            "name": ("%s policy" % p.get("kind")) if privacy_safe else p.get("name"),
            "insurer": "(hidden)" if privacy_safe else p.get("insurer"),
            "policy_number": (_mask(p.get("policy_number")) if privacy_safe
                              else p.get("policy_number")),
            "covered": p.get("covered"),
            "sum_assured": p.get("sum_assured"),
            "annual_premium": p.get("annual_premium"),
            "has_nominee": bool((p.get("nominee") or "").strip()),
        } for p in (policies or [])]) if insurance else None),
        "data_quality": {
            "income_basis": (analytics.income_basis_label(income_basis)
                             or "unspecified (ask before assuming net "
                                "or gross)"),
            "income_months_logged": cashflow.get("income_months"),
            "expense_months_logged": cashflow.get("expense_months"),
            "expenses_include_recurring": True,
            "expense_split": {
                "logged_entries_monthly": round(
                    cashflow.get("expense_entries_m", 0), 2),
                "recurring_costs_monthly": round(
                    cashflow.get("recurring_expense_m", 0), 2)},
            "investment_split": {
                "chosen_sips_monthly": round(cashflow.get("sip_m", 0), 2),
                "payroll_deductions_monthly": round(
                    cashflow.get("payroll_invest_m", 0), 2)},
            "long_term_rule": "simplified: %d months for listed equity and "
                              "equity-oriented funds, %d months otherwise; "
                              "confirm specifics with a CA"
                              % (analytics.LONG_TERM_MONTHS_EQUITY,
                                 analytics.LONG_TERM_MONTHS_OTHER),
            "warnings": warnings,
        },
        "suggestions": sugg,
    }


def to_json(snapshot):
    return json.dumps(snapshot, indent=2)


def to_ai_package(snapshot):
    """Prompt + JSON in one text block, ready to paste into Claude."""
    return CLAUDE_PROMPT + "\n```json\n" + to_json(snapshot) + "\n```\n"


def to_pdf(snapshot):
    """Render the snapshot to a PDF; returns bytes."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer,
                                    Table, TableStyle)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm,
                            rightMargin=15 * mm, topMargin=15 * mm)
    styles = getSampleStyleSheet()
    story = [Paragraph("Household Portfolio Snapshot", styles["Title"]),
             Paragraph("As of %s — amounts in INR%s" % (
                 snapshot["as_of"],
                 " (privacy-safe: identifiers masked)"
                 if snapshot["privacy_safe"] else ""), styles["Normal"]),
             Spacer(1, 6 * mm)]

    def fmt(x):
        return "{:,.0f}".format(x) if isinstance(x, (int, float)) else str(x)

    def table(title, header, rows, widths=None):
        story.append(Paragraph(title, styles["Heading2"]))
        data = [header] + rows
        t = Table(data, colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.white, colors.HexColor("#f4f6f7")]),
            ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ]))
        story.append(t)
        story.append(Spacer(1, 5 * mm))

    s = snapshot["summary"]
    table("Summary", ["Metric", "Amount"],
          [["Total assets", fmt(s["total_assets"])],
           ["Total liabilities", fmt(s["total_liabilities"])],
           ["Net worth", fmt(s["net_worth"])]])
    table("By asset class", ["Asset class", "Value"],
          [[k, fmt(v)] for k, v in sorted(s["by_asset_class"].items(),
                                          key=lambda kv: -kv[1])])
    table("By owner", ["Owner", "Value"],
          [[k, fmt(v)] for k, v in s["by_owner"].items()])
    table("Allocation vs target", ["Bucket", "Actual %", "Target %", "Drift %"],
          [[d["bucket"], "%.1f" % d["actual_pct"], "%.1f" % d["target_pct"],
            "%+.1f" % d["drift_pct"]] for d in snapshot["allocation_drift"]])
    if snapshot["holdings"]:
        table("Holdings", ["Owner", "Class", "Name", "Invested", "Current"],
              [[h["owner"], h["asset_class"],
                Paragraph(str(h["name"])[:60], styles["BodyText"]),
                fmt(h["invested"]), fmt(h["current_value"])]
               for h in snapshot["holdings"]],
              widths=[22 * mm, 28 * mm, 70 * mm, 28 * mm, 28 * mm])
    if snapshot["liabilities"]:
        table("Liabilities", ["Loan", "Outstanding", "Rate %", "EMI", "Months left"],
              [[loan["name"], fmt(loan["outstanding"]),
                fmt(loan["annual_rate_pct"]), fmt(loan["emi"]),
                fmt(loan["tenure_months_remaining"])]
               for loan in snapshot["liabilities"]])
    cf = snapshot["monthly_cashflow"]
    if cf:
        table("Monthly cashflow (avg)", ["Item", "Amount"],
              [["Income", fmt(cf.get("income_m", 0))],
               ["Expenses", fmt(cf.get("expense_m", 0))],
               ["EMIs", fmt(cf.get("emi_m", 0))],
               ["Committed investments (SIPs)", fmt(cf.get("committed_invest_m", 0))],
               ["Other committed", fmt(cf.get("other_committed_m", 0))],
               ["Investible surplus", fmt(cf.get("surplus_m", 0))],
               ["Savings rate %", "%.1f" % cf.get("savings_rate_pct", 0)]])
    if snapshot["suggestions"]:
        story.append(Paragraph("Suggestions", styles["Heading2"]))
        for sg in snapshot["suggestions"]:
            story.append(Paragraph("<b>%s</b>: %s" % (sg["title"], sg["detail"]),
                                   styles["BodyText"]))
        story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(
        "Generated by Portfolio Tracker. Educational information only — "
        "not investment advice.", styles["Italic"]))
    doc.build(story)
    return buf.getvalue()
