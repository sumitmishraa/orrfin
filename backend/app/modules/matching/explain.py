"""Plain-English explanation of a match result without AI (BUILD_PLAN §6 "explanation from rule results only").

Used when Claude is unavailable, and as the fallback if an AI explanation fails: an explanation
never blocks matching. Like the AI version, it reads only the rule results, never the document.
"""

from decimal import Decimal
from typing import Any

TEMPLATE_SOURCE = "template (no AI)"


def explain_from_rules(rule_results: list[dict[str, Any]], outcome: str, amount_at_risk: Decimal) -> str:
    failed = [r for r in rule_results if r["status"] == "fail"]
    warnings = [r for r in rule_results if r["status"] == "warn"]
    if outcome == "matched":
        text = "All checks passed: the invoice agrees with the purchase order and the goods receipt."
        if warnings:
            text += " Note: " + " ".join(w["message"] for w in warnings)
        return text
    lead = f"This invoice needs review: {len(failed)} check{'s' if len(failed) != 1 else ''} failed"
    lead += f", with ₹{amount_at_risk:,.2f} at risk." if amount_at_risk else "."
    return " ".join([lead] + [r["message"] for r in failed] + [w["message"] for w in warnings])
