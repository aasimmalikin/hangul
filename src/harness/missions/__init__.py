"""Missions: jobs Hangul carries through on its own over days.

A mission is a fixed list of steps (a template, never improvised by a model)
that the scheduler moves forward each tick. A step either finishes, waits for
time to pass, or waits for the owner, who is asked once, on WhatsApp
and on their devices, and can decide on the /missions page too.

Templates:
  slow_day        tomorrow looks slow -> make the offer post -> the owner's
                  go-ahead -> ask how the day went -> measure it against the
                  forecast -> learn which ideas work for this business
  monthly_report  on the 1st: what last month's missions earned, in rupees

Earned autonomy: after ``TRUST_AFTER`` go-aheads in a row for one business,
Hangul offers to stop asking; the owner can take that back at any time, and
a rejection resets the count.
"""

from harness.billing import entitlements


def allowed(user_id: str) -> bool:
    """Missions are Plus and up (``GATED_TOOLS["missions"]``): Plus gets one slow day a week (its
    weekly idea, ``sales_plus_ideas_week``), Pro every slow day. Every plan when billing is off."""
    if not entitlements.billing_enabled():
        return True
    from harness.billing.plans import get_plan, plan_allows_tool
    from harness.db import billing as billing_db
    return plan_allows_tool(get_plan(billing_db.get_account(user_id).plan), "missions")
