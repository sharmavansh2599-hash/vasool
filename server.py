#!/usr/bin/env python3
"""Vasool AI - receivables & collections intelligence for Indian MSMEs.

Single-file build (data + services + store + server), stdlib only.
Run:  python3 server.py [port]    (default 8000, or $PORT)
Serves index.html from the same directory and a JSON API under /api/.
"""

import json
import os
import re
import sys
import uuid
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer



WORKSPACE = {
    "name": "Khandelwal Enterprises Pvt Ltd",
    "tagline": "Industrial packaging materials - Jaipur",
    "gstin": "08AAECK4821F1Z6",
    "owner": "Amit Khandelwal",
    "owner_email": "amit@khandelwalent.in",
    "currency": "INR",
    "sample_data": True,
}

# Customer behaviour profiles. avg_delay_days and reliability drive risk
# indicators, the collection queue and the cash-flow forecast, so nothing
# on screen is a fabricated number - it is all derived from these records.
CUSTOMERS = [
    dict(id="c1", name="Mahalaxmi Textiles", contact="Rakesh Agarwal",
         phone="+91 98290 41122", email="accounts@mahalaxmitextiles.in",
         city="Surat", since="2019", avg_delay_days=18, credit_limit=1200000,
         note="Largest account. Pays eventually, always late."),
    dict(id="c2", name="Shree Balaji Enterprises", contact="Pooja Sharma",
         phone="+91 94140 67788", email="pooja@balajient.in",
         city="Jaipur", since="2018", avg_delay_days=0, credit_limit=500000,
         note="Most reliable payer. NEFT same day, every time."),
    dict(id="c3", name="RK Auto Components", contact="Vikram Rathi",
         phone="+91 98110 33445", email="vikram@rkauto.in",
         city="Faridabad", since="2021", avg_delay_days=25, credit_limit=800000,
         note="Account deteriorating since August. One open rate dispute."),
    dict(id="c4", name="Vardhman Distributors", contact="Nitin Vardhman",
         phone="+91 98711 90876", email="nitin@vardhmandist.in",
         city="Delhi", since="2020", avg_delay_days=12, credit_limit=400000,
         note="Occasional delays, always responds to reminders."),
    dict(id="c5", name="Apex Plastics", contact="Mehul Desai",
         phone="+91 98980 12233", email="mehul@apexplastics.in",
         city="Ahmedabad", since="2026", avg_delay_days=None, credit_limit=300000,
         note="New customer, first order this month. No payment history yet."),
    dict(id="c6", name="Krishna Agro Traders", contact="Santosh Patidar",
         phone="+91 97550 44321", email="santosh@krishnaagro.in",
         city="Indore", since="2022", avg_delay_days=21, credit_limit=500000,
         note="Pays in instalments without being asked. Needs watching."),
    dict(id="c7", name="Sunrise Pharmaceuticals", contact="Anita Thakur",
         phone="+91 98160 78899", email="anita@sunrisepharma.in",
         city="Baddi", since="2019", avg_delay_days=1, credit_limit=1500000,
         note="Blue-chip account. RTGS on due date."),
    dict(id="c8", name="Om Sai Packaging", contact="Deepak Chavan",
         phone="+91 98670 55678", email="deepak@omssaipack.in",
         city="Noida", since="2023", avg_delay_days=20, credit_limit=400000,
         note="Repeated delays. Last promise-to-pay date was missed."),
    dict(id="c9", name="Ganga Metals", contact="Alok Srivastava",
         phone="+91 98390 21144", email="alok@gangametals.in",
         city="Kanpur", since="2020", avg_delay_days=4, credit_limit=600000,
         note="Normally prompt. Current invoice under quality dispute."),
    dict(id="c10", name="Bluebird Retail Chain", contact="Farhan Qureshi",
         phone="+91 98280 93355", email="farhan@bluebirdretail.in",
         city="Jaipur", since="2024", avg_delay_days=2, credit_limit=400000,
         note="Good payer, small but growing account."),
]

# Invoices. issued = days before today; terms = credit days; paid entries are
# (amount, days_before_today, mode). balance/status are derived, never stored.
def _inv(seq, cust, amount, issued, terms, paid=(), dispute=None):
    return dict(seq=seq, customer=cust, amount=amount, issued=issued,
                terms=terms, paid=list(paid), dispute=dispute)

INVOICES = [
    # --- open / overdue -------------------------------------------------
    _inv(141, "c1", 480000, 78, 45),
    _inv(162, "c1", 240000, 55, 30, paid=[(100000, 10, "UPI")]),
    _inv(178, "c1", 315000, 28, 30),
    _inv(132, "c3", 195000, 95, 30),
    _inv(107, "c3", 560000, 126, 30, dispute="d1"),
    _inv(168, "c4", 145000, 33, 30),
    _inv(186, "c4", 96000, 10, 15),
    _inv(149, "c6", 275000, 62, 30, paid=[(50000, 20, "NEFT"), (40000, 5, "UPI")]),
    _inv(181, "c6", 88000, 18, 30),
    _inv(136, "c8", 162000, 70, 15),
    _inv(170, "c8", 74000, 30, 15),
    _inv(158, "c9", 330000, 48, 30, dispute="d2"),
    _inv(190, "c5", 120000, 6, 30),
    _inv(183, "c2", 220000, 15, 30),
    _inv(192, "c7", 410000, 4, 21),
    _inv(188, "c10", 150000, 8, 30),
    # --- collected this month ------------------------------------------
    _inv(172, "c7", 640000, 25, 21, paid=[(640000, 1, "RTGS")]),
    _inv(155, "c2", 185000, 40, 30, paid=[(185000, 7, "NEFT")]),
    _inv(165, "c10", 115000, 36, 30, paid=[(115000, 5, "UPI")]),
    # --- history feeding the monthly trend ------------------------------
    _inv(55,  "c10", 85000, 215, 30, paid=[(85000, 183, "UPI")]),
    _inv(60,  "c2", 190000, 200, 30, paid=[(190000, 168, "NEFT")]),
    _inv(64,  "c4", 110000, 196, 30, paid=[(110000, 154, "NEFT")]),
    _inv(71,  "c7", 450000, 185, 21, paid=[(450000, 162, "RTGS")]),
    _inv(80,  "c9", 240000, 165, 30, paid=[(240000, 133, "NEFT")]),
    _inv(84,  "c1", 330000, 175, 45, paid=[(330000, 118, "RTGS")]),
    _inv(98,  "c1", 360000, 130, 30, paid=[(360000, 82, "RTGS")]),
    _inv(103, "c3", 220000, 112, 30, paid=[(220000, 57, "NEFT")]),
    _inv(99,  "c2", 210000, 128, 30, paid=[(210000, 99, "NEFT")]),
    _inv(101, "c9", 290000, 122, 30, paid=[(290000, 91, "NEFT")]),
    _inv(105, "c7", 520000, 118, 21, paid=[(520000, 96, "RTGS")]),
    _inv(110, "c6", 180000, 108, 30, paid=[(100000, 70, "NEFT"), (80000, 55, "UPI")]),
    _inv(112, "c4", 132000, 101, 30, paid=[(132000, 71, "NEFT")]),
    _inv(115, "c8", 140000, 96, 15, paid=[(140000, 61, "UPI")]),
    _inv(118, "c1", 410000, 92, 45, paid=[(410000, 29, "RTGS")]),
    _inv(120, "c2", 240000, 88, 30, paid=[(240000, 58, "NEFT")]),
    _inv(123, "c7", 480000, 84, 21, paid=[(480000, 62, "RTGS")]),
    _inv(126, "c9", 260000, 76, 30, paid=[(260000, 44, "NEFT")]),
    _inv(128, "c10", 95000, 72, 30, paid=[(95000, 40, "UPI")]),
    _inv(133, "c2", 175000, 66, 30, paid=[(175000, 35, "NEFT")]),
    _inv(137, "c7", 550000, 60, 21, paid=[(550000, 38, "RTGS")]),
    _inv(139, "c4", 128000, 52, 30, paid=[(128000, 11, "NEFT")]),
    _inv(143, "c9", 305000, 44, 30, paid=[(305000, 15, "NEFT")]),
    _inv(146, "c2", 260000, 38, 30, paid=[(260000, 9, "NEFT")]),
]

DISPUTES = [
    dict(id="d1", invoice_seq=107, customer="c3",
         reason="Rate mismatch - customer claims quoted rate was lower",
         opened_days_ago=38, status="open",
         next_action="Share signed purchase order copy and reconcile PO rate vs invoice rate",
         docs=["Purchase order PO-RK-2214 (PDF)", "WhatsApp rate confirmation screenshot"],
         note="Customer withheld full payment of Rs 5.6L over a Rs 42,000 rate difference."),
    dict(id="d2", invoice_seq=158, customer="c9",
         reason="Quality claim - 2 of 40 cartons damaged in transit",
         opened_days_ago=6, status="open",
         next_action="Arrange pickup of damaged cartons and issue credit note for Rs 16,500",
         docs=["Delivery challan DC-0918", "Customer photos of damaged cartons"],
         note="Otherwise prompt payer. Offered credit note; awaiting confirmation."),
    dict(id="d3", invoice_seq=115, customer="c8",
         reason="Short delivery claim - 3 cartons",
         opened_days_ago=68, status="resolved",
         resolved_days_ago=55,
         next_action=None,
         docs=["Weighbridge slip", "Credit note CN-0042"],
         note="Resolved with credit note CN-0042 for Rs 8,400. Payment received after resolution."),
]

# Logged customer communication. (customer, invoice_seq|None, channel,
# direction, days_ago, summary). promise date on f8 drives the forecast.
COMMS = [
    ("c1", 141, "call", "out", 3, "Spoke to Rakesh. Says payment will clear by end of week."),
    ("c1", 162, "whatsapp", "out", 10, "Reminder for balance Rs 1.4L. Seen, no reply."),
    ("c1", 141, "email", "out", 12, "Statement of account shared for April-October."),
    ("c3", 107, "call", "out", 6, "Vikram reiterated rate claim. Asked for PO copy, not shared yet."),
    ("c3", 132, "whatsapp", "out", 4, "Reminder sent for INV/2526/0132. No response."),
    ("c3", None, "email", "in", 2, "Accounts team says payments on hold until dispute resolved."),
    ("c4", 168, "call", "out", 1, "Nitin apologised; UPI transfer promised by tomorrow evening."),
    ("c6", 149, "whatsapp", "in", 5, "Sent Rs 40,000 and said balance within two weeks."),
    ("c8", 136, "call", "out", 12, "Deepak promised payment in 7 days. Promise date missed."),
    ("c8", 136, "whatsapp", "out", 5, "Follow-up after missed promise. Read, no reply."),
    ("c9", 158, "email", "in", 6, "Raised quality dispute with photos of damaged cartons."),
    ("c9", 158, "call", "out", 3, "Offered credit note of Rs 16,500. Alok to confirm by Friday."),
    ("c10", 165, "whatsapp", "in", 5, "Paid and shared UPI screenshot."),
    ("c7", 172, "email", "in", 1, "RTGS advice received for Rs 6.4L."),
]

# Follow-up tasks. due = days from today (negative = overdue task).
FOLLOWUPS = [
    dict(id="f1", customer="c4", invoice_seq=168, kind="call", due=0,
         title="Call Nitin - confirm UPI transfer for INV/2526/0168",
         detail="He promised payment by tomorrow evening on yesterday's call."),
    dict(id="f2", customer="c1", invoice_seq=141, kind="call", due=0,
         title="Call Rakesh - week-end commitment on INV/2526/0141",
         detail="Rs 4.8L overdue 33 days. He said payment clears by end of week."),
    dict(id="f3", customer="c9", invoice_seq=158, kind="email", due=0,
         title="Email credit note draft to Alok",
         detail="Credit note of Rs 16,500 for damaged cartons; confirmation due Friday."),
    dict(id="f4", customer="c8", invoice_seq=136, kind="whatsapp", due=-2,
         title="Escalate Om Sai - missed promise on INV/2526/0136",
         detail="Promise-to-pay date passed 7 days ago. Two messages read, no reply."),
    dict(id="f5", customer="c3", invoice_seq=132, kind="call", due=1,
         title="Call RK Auto accounts - separate undisputed amount",
         detail="Ask them to release INV/2526/0132 (Rs 1.95L, undisputed) while rate dispute continues."),
    dict(id="f6", customer="c1", invoice_seq=178, kind="whatsapp", due=2,
         title="Pre-due reminder to Mahalaxmi for INV/2526/0178",
         detail="Rs 3.15L falls due in 2 days. Their average delay is 18 days - remind before due date."),
    dict(id="f7", customer="c6", invoice_seq=149, kind="call", due=3,
         title="Check Krishna Agro balance plan for INV/2526/0149",
         detail="Rs 1.85L balance after two instalments. He said 'within two weeks' 5 days ago."),
    dict(id="f8", customer="c8", invoice_seq=170, kind="email", due=4,
         title="Statement + firm reminder to Om Sai",
         detail="Send statement covering both open invoices with a clear due date."),
    dict(id="f9", customer="c3", invoice_seq=107, kind="email", due=5,
         title="Send PO reconciliation to Vikram",
         detail="Attach PO-RK-2214 showing agreed rate; propose splitting undisputed amount."),
]

SETTINGS = {
    "workspace_name": WORKSPACE["name"],
    "reminder_cadence_days": [3, 7, 14],
    "auto_remind_before_due": True,
    "default_terms_days": 30,
    "weekly_summary_email": True,
}


def generate(today=None):
    """Return the raw workspace dataset with dates resolved to ISO strings."""
    today = today or date.today()

    def d(days_ago):
        return (today - timedelta(days=days_ago)).isoformat()

    customers = [dict(c) for c in CUSTOMERS]
    invoices = []
    for spec in INVOICES:
        issue_date = today - timedelta(days=spec["issued"])
        due_date = issue_date + timedelta(days=spec["terms"])
        inv = dict(
            id="inv-%04d" % spec["seq"],
            number="INV/2526/%04d" % spec["seq"],
            customer_id=spec["customer"],
            amount=spec["amount"],
            issue_date=issue_date.isoformat(),
            due_date=due_date.isoformat(),
            terms_days=spec["terms"],
            dispute_id=spec.get("dispute"),
            payments=[
                dict(amount=amt, date=d(ago), mode=mode)
                for amt, ago, mode in spec["paid"]
            ],
        )
        invoices.append(inv)

    comms = [dict(customer_id=c, invoice_id=("inv-%04d" % s) if s else None,
                  channel=ch, direction=dr, date=d(ago), summary=su)
             for c, s, ch, dr, ago, su in COMMS]

    followups = []
    for f0 in FOLLOWUPS:
        f = dict(f0)
        due = f.pop("due")
        followups.append(dict(f, due_date=(today + timedelta(days=due)).isoformat(),
                              status="pending", channel_done=None, completed_date=None,
                              customer_response=None))

    disputes = []
    for x0 in DISPUTES:
        x = dict(x0)
        opened = x.pop("opened_days_ago")
        resolved = x.pop("resolved_days_ago", None)
        disputes.append(dict(x, opened_date=d(opened),
                             resolved_date=d(resolved) if resolved is not None else None))

    return dict(workspace=dict(WORKSPACE), customers=customers,
                invoices=invoices, comms=comms, followups=followups,
                disputes=disputes, settings=dict(SETTINGS),
                generated_on=today.isoformat())




def _parse(iso):
    return datetime.strptime(iso, "%Y-%m-%d").date()


def _month_key(d):
    return "%04d-%02d" % (d.year, d.month)


class VasoolService:
    def __init__(self, ds, today=None):
        self.ds = ds
        self.today = today or date.today()
        self.customers = {c["id"]: c for c in ds["customers"]}
        self.invoices = {i["id"]: i for i in ds["invoices"]}
        self.disputes = {d["id"]: d for d in ds["disputes"]}
        self._derive()

    # ------------------------------------------------------------------
    # derivation
    # ------------------------------------------------------------------
    def _derive(self):
        for inv in self.invoices.values():
            paid = sum(p["amount"] for p in inv["payments"])
            inv["amount_paid"] = paid
            inv["balance"] = inv["amount"] - paid
            due = _parse(inv["due_date"])
            inv["days_overdue"] = max(0, (self.today - due).days) if inv["balance"] > 0 else 0
            inv["days_to_due"] = (due - self.today).days
            disp = self.disputes.get(inv.get("dispute_id") or "", {})
            if inv["balance"] <= 0:
                inv["status"] = "paid"
            elif disp.get("status") == "open":
                inv["status"] = "disputed"
            elif inv["days_overdue"] > 0:
                inv["status"] = "overdue"
            elif paid > 0:
                inv["status"] = "partial"
            else:
                inv["status"] = "due"
            od = inv["days_overdue"]
            inv["bucket"] = ("0-30" if od <= 30 else "31-60" if od <= 60 else
                             "61-90" if od <= 90 else "90+") if od else None
            if inv["status"] == "paid" and inv["payments"]:
                last = max(_parse(p["date"]) for p in inv["payments"])
                inv["paid_late_days"] = max(0, (last - due).days)

        for c in self.customers.values():
            cinvs = [i for i in self.invoices.values() if i["customer_id"] == c["id"]]
            c["open_invoices"] = [i for i in cinvs if i["balance"] > 0]
            c["outstanding"] = sum(i["balance"] for i in c["open_invoices"])
            c["overdue_amount"] = sum(i["balance"] for i in c["open_invoices"] if i["days_overdue"] > 0)
            paid_invs = [i for i in cinvs if i["status"] == "paid"]
            lates = [i["paid_late_days"] for i in paid_invs]
            c["avg_delay_measured"] = round(sum(lates) / len(lates), 1) if lates else None
            late_count = sum(1 for x in lates if x > 5)
            c["late_payment_share"] = (late_count / len(lates)) if lates else None
            c["has_open_dispute"] = any(
                self.disputes.get(i.get("dispute_id") or "", {}).get("status") == "open"
                for i in c["open_invoices"])
            c["risk"] = self._risk(c)
            c["promise"] = self._promise(c)

    def _promise(self, c):
        """Latest promise-to-pay from comms, and whether it was kept."""
        for cm in sorted(self.ds["comms"], key=lambda x: x["date"], reverse=True):
            if cm["customer_id"] == c["id"] and "promised" in cm["summary"].lower():
                return {"date": cm["date"], "summary": cm["summary"]}
        return None

    def _risk(self, c):
        if c["outstanding"] <= 0:
            return {"level": "clear", "reasons": ["No outstanding balance"]}
        reasons, score = [], 0
        if c["has_open_dispute"]:
            score += 2; reasons.append("Open dispute")
        max_od = max((i["days_overdue"] for i in c["open_invoices"]), default=0)
        if max_od > 90: score += 3; reasons.append("Invoice overdue 90+ days")
        elif max_od > 60: score += 2; reasons.append("Invoice overdue 60+ days")
        elif max_od > 30: score += 1; reasons.append("Invoice overdue 30+ days")
        if (c["avg_delay_measured"] or 0) > 10:
            score += 1; reasons.append("Habitual late payer (avg %dd late)" % c["avg_delay_measured"])
        if c["late_payment_share"] is not None and c["late_payment_share"] > 0.5:
            score += 1; reasons.append("Majority of past payments were late")
        if c["outstanding"] > (c.get("credit_limit") or 10**12):
            score += 1; reasons.append("Above credit limit")
        level = "high" if score >= 4 else "medium" if score >= 2 else "low"
        return {"level": level, "reasons": reasons or ["Pays on time"]}

    def customer_delay(self, c):
        return c["avg_delay_measured"] if c["avg_delay_measured"] is not None else (c["avg_delay_days"] or 0)

    # ------------------------------------------------------------------
    # overview
    # ------------------------------------------------------------------
    def kpis(self):
        open_invs = [i for i in self.invoices.values() if i["balance"] > 0]
        mk = _month_key(self.today)
        collected_month = sum(p["amount"] for i in self.invoices.values()
                              for p in i["payments"] if _month_key(_parse(p["date"])) == mk)
        fc = self.forecast(7)
        return {
            "total_outstanding": sum(i["balance"] for i in open_invs),
            "overdue_amount": sum(i["balance"] for i in open_invs if i["days_overdue"] > 0),
            "collected_this_month": collected_month,
            "expected_7d": fc["scenarios"]["base"]["total"],
            "open_invoice_count": len(open_invs),
            "overdue_invoice_count": sum(1 for i in open_invs if i["days_overdue"] > 0),
        }

    def ageing(self):
        buckets = {"0-30": 0, "31-60": 0, "61-90": 0, "90+": 0}
        counts = {"0-30": 0, "31-60": 0, "61-90": 0, "90+": 0}
        for i in self.invoices.values():
            if i["balance"] > 0 and i["days_overdue"] > 0:
                buckets[i["bucket"]] += i["balance"]
                counts[i["bucket"]] += 1
        not_due = sum(i["balance"] for i in self.invoices.values()
                      if i["balance"] > 0 and i["days_overdue"] == 0)
        return {"buckets": buckets, "counts": counts, "not_due": not_due}

    def monthly_trend(self, months=8):
        series = []
        for m in range(months - 1, -1, -1):
            d0 = date(self.today.year, self.today.month, 1)
            month = (d0 - timedelta(days=30 * m)).replace(day=1)
            key = _month_key(month)
            collected = sum(p["amount"] for i in self.invoices.values()
                            for p in i["payments"] if _month_key(_parse(p["date"])) == key)
            expected = sum(i["amount"] for i in self.invoices.values()
                           if _month_key(_parse(i["due_date"])) == key)
            series.append({"month": key, "collected": collected, "expected": expected})
        return series

    def risk_lists(self):
        cs = sorted(self.customers.values(), key=lambda c: -c["outstanding"])
        top_outstanding = [self._cust_row(c) for c in cs if c["outstanding"] > 0][:5]
        repeat_late = [self._cust_row(c) for c in self.customers.values()
                       if c["late_payment_share"] is not None and c["late_payment_share"] > 0.5
                       and c["outstanding"] > 0]
        repeat_late.sort(key=lambda r: -r["outstanding"])
        with_overdue = [self._cust_row(c) for c in cs if c["overdue_amount"] > 0]
        return {"top_outstanding": top_outstanding, "repeat_late": repeat_late[:5],
                "with_overdue": with_overdue[:5]}

    def _cust_row(self, c):
        return {"id": c["id"], "name": c["name"], "city": c["city"],
                "outstanding": c["outstanding"], "overdue_amount": c["overdue_amount"],
                "avg_delay": c["avg_delay_measured"], "risk": c["risk"]["level"],
                "risk_reasons": c["risk"]["reasons"]}

    def action_centre(self):
        t = self.today
        fu_today = [f for f in self.ds["followups"]
                    if f["status"] == "pending" and _parse(f["due_date"]) <= t]
        recent_payments = []
        for i in self.invoices.values():
            for p in i["payments"]:
                if (t - _parse(p["date"])).days <= 7:
                    recent_payments.append({"invoice_id": i["id"], "number": i["number"],
                                            "customer_id": i["customer_id"],
                                            "customer": self.customers[i["customer_id"]]["name"],
                                            "amount": p["amount"], "date": p["date"], "mode": p["mode"]})
        recent_payments.sort(key=lambda x: x["date"], reverse=True)
        newly_overdue = [{"invoice_id": i["id"], "number": i["number"],
                          "customer_id": i["customer_id"],
                          "customer": self.customers[i["customer_id"]]["name"],
                          "balance": i["balance"], "days_overdue": i["days_overdue"]}
                         for i in self.invoices.values()
                         if 0 < i["days_overdue"] <= 7]
        pending_disputes = [{"id": d["id"], "invoice_id": "inv-%04d" % d["invoice_seq"],
                             "customer_id": d["customer"],
                             "customer": self.customers[d["customer"]]["name"],
                             "reason": d["reason"],
                             "days_open": (t - _parse(d["opened_date"])).days}
                            for d in self.ds["disputes"] if d["status"] == "open"]
        return {"followups_due": [self._fu_row(f) for f in
                                  sorted(fu_today, key=lambda f: f["due_date"])],
                "recent_payments": recent_payments[:6],
                "newly_overdue": sorted(newly_overdue, key=lambda x: -x["balance"]),
                "pending_disputes": pending_disputes}

    # ------------------------------------------------------------------
    # insights
    # ------------------------------------------------------------------
    def insights(self):
        out = []
        high = [c for c in self.customers.values()
                if c["risk"]["level"] == "high" and c["outstanding"] > 0]
        if high:
            amt = sum(c["outstanding"] for c in high)
            repeat = [c for c in high if (c["late_payment_share"] or 0) > 0.5]
            disputed = [c for c in high if c["has_open_dispute"]]
            text = "%s across %d customer%s needs attention." % (
                _indian(amt), len(high), "s" if len(high) > 1 else "")
            bits = []
            if repeat:
                bits.append("%d %s a history of delayed payments" %
                            (len(repeat), "have" if len(repeat) > 1 else "has"))
            if disputed:
                bits.append("%d invoice%s under an unresolved dispute" %
                            (sum(len([i for i in c["open_invoices"]
                                      if self.disputes.get(i.get("dispute_id") or "", {}).get("status") == "open"])
                                     for c in disputed),
                             " is" if len(disputed) == 1 else "s are"))
            if bits:
                text += " " + "; ".join(bits) + "."
            out.append({"kind": "risk", "title": "Concentration of collection risk", "text": text,
                        "action": "Open the collection queue",
                        "link": "#/collections",
                        "records": [{"type": "customer", "id": c["id"], "label": c["name"]} for c in high]})

        promises = []
        for c in self.customers.values():
            p = c.get("promise")
            if p and c["outstanding"] > 0:
                pd = _parse(p["date"])
                if (self.today - pd).days >= 7 and "missed" in p["summary"].lower():
                    promises.append(c)
        for c in promises:
            out.append({"kind": "promise", "title": "Broken promise-to-pay",
                        "text": "%s missed its committed payment date. Rs %s is still open. "
                                "Habitual delays (avg %dd late) make silent waiting costly here." % (
                                    c["name"], _indian(c["outstanding"]), self.customer_delay(c)),
                        "action": "Open customer profile",
                        "link": "#/customers/%s" % c["id"],
                        "records": [{"type": "customer", "id": c["id"], "label": c["name"]}]})

        fc = self.forecast(30)
        kpis = self.kpis()
        if fc["scenarios"]["delayed"]["total"] < fc["scenarios"]["base"]["total"]:
            gap = fc["scenarios"]["base"]["total"] - fc["scenarios"]["delayed"]["total"]
            out.append({"kind": "cashflow", "title": "Delay risk in the 30-day pipeline",
                        "text": "If every payer slips to their usual delay pattern, collections over the "
                                "next 30 days drop by %s versus the base case. Pre-due reminders on the "
                                "two largest invoices protect most of it." % _indian(gap),
                        "action": "View cash flow forecast",
                        "link": "#/cashflow", "records": []})

        od90 = [i for i in self.invoices.values() if i["days_overdue"] > 90 and i["balance"] > 0]
        if od90:
            amt = sum(i["balance"] for i in od90)
            out.append({"kind": "ageing", "title": "90+ day exposure",
                        "text": "%s sits in invoices overdue more than 90 days, where recovery odds fall "
                                "sharply. %s" % (_indian(amt),
                                "Part of it is blocked by an open dispute - resolving the dispute unlocks it."
                                if any(i["status"] == "disputed" for i in od90) else ""),
                        "action": "Review 90+ invoices",
                        "link": "#/invoices?bucket=90%2B",
                        "records": [{"type": "invoice", "id": i["id"], "label": i["number"]} for i in od90]})

        mk = self.kpis()["collected_this_month"]
        exp = sum(i["amount"] for i in self.invoices.values()
                  if _month_key(_parse(i["due_date"])) == _month_key(self.today))
        if exp:
            pct = round(100 * mk / exp)
            out.append({"kind": "pace", "title": "This month vs plan",
                        "text": "Collections this month are %s against %s that fell due (%d%%). "
                                "The gap is concentrated in the overdue list, not in new billing." % (
                                    _indian(mk), _indian(exp), pct),
                        "action": "Open ageing report", "link": "#/reports", "records": []})
        return out

    # ------------------------------------------------------------------
    # collection queue
    # ------------------------------------------------------------------
    def collection_queue(self):
        queue = []
        for c in self.customers.values():
            if c["outstanding"] <= 0:
                continue
            invs = sorted(c["open_invoices"], key=lambda i: -i["days_overdue"])
            oldest = invs[0]
            score, reasons = 0, []
            if oldest["days_overdue"] > 0:
                score += min(oldest["days_overdue"], 100)
                reasons.append("%d days overdue on %s" % (oldest["days_overdue"], oldest["number"]))
            else:
                reasons.append("Not yet overdue - %s due in %dd" % (oldest["number"], oldest["days_to_due"]))
            score += c["outstanding"] / 20000.0
            delay = self.customer_delay(c)
            if delay > 10:
                score += 15; reasons.append("Pays %d days late on average" % delay)
            if c["has_open_dispute"]:
                score += 10; reasons.append("Open dispute blocking payment")
            p = c.get("promise")
            if p and "missed" in p["summary"].lower():
                score += 20; reasons.append("Missed a promise-to-pay date")
            if not reasons:
                reasons.append("Routine follow-up")
            if c["has_open_dispute"]:
                action = "Resolve the dispute first - it is blocking the largest invoice"
            elif p and "missed" in p["summary"].lower():
                action = "Escalate: call the owner, set a firm date and confirm in writing"
            elif oldest["days_overdue"] > 30:
                action = "Call today and ask for a dated commitment, then send a statement"
            elif oldest["days_overdue"] > 0:
                action = "Send a WhatsApp reminder with the invoice and UPI details"
            else:
                action = "Send a pre-due reminder before %s" % _fmt(oldest["due_date"])
            queue.append({"customer_id": c["id"], "customer": c["name"], "city": c["city"],
                          "outstanding": c["outstanding"], "days_overdue": oldest["days_overdue"],
                          "avg_delay": c["avg_delay_measured"], "risk": c["risk"]["level"],
                          "reasons": reasons, "recommended_action": action,
                          "top_invoice_id": oldest["id"], "top_invoice": oldest["number"],
                          "score": round(score, 1)})
        queue.sort(key=lambda q: -q["score"])
        return queue

    # ------------------------------------------------------------------
    # follow-ups
    # ------------------------------------------------------------------
    def _fu_row(self, f):
        c = self.customers[f["customer"]]
        inv = self.invoices.get("inv-%04d" % f["invoice_seq"]) if f.get("invoice_seq") else None
        return {**f, "customer_name": c["name"],
                "invoice_number": inv["number"] if inv else None,
                "invoice_id": inv["id"] if inv else None,
                "invoice_balance": inv["balance"] if inv else None,
                "days_overdue": inv["days_overdue"] if inv else None,
                "overdue_task": f["status"] == "pending" and _parse(f["due_date"]) < self.today}

    def followups(self):
        rows = [self._fu_row(f) for f in self.ds["followups"]]
        pending = [r for r in rows if r["status"] == "pending"]
        done = [r for r in rows if r["status"] != "pending"]
        pending.sort(key=lambda r: r["due_date"])
        done.sort(key=lambda r: r.get("completed_date") or r["due_date"], reverse=True)
        comms = sorted(self.ds["comms"], key=lambda x: x["date"], reverse=True)
        return {"pending": pending, "done": done, "comms": comms}

    def draft(self, fu_id, channel):
        f = next((x for x in self.ds["followups"] if x["id"] == fu_id), None)
        if not f:
            return None
        c = self.customers[f["customer"]]
        inv = self.invoices.get("inv-%04d" % f["invoice_seq"]) if f.get("invoice_seq") else None
        first = c["contact"].split()[0]
        amt = _indian(inv["balance"]) if inv else _indian(c["outstanding"])
        od = inv["days_overdue"] if inv else 0
        num = inv["number"] if inv else "the open invoices"
        due = _fmt(inv["due_date"]) if inv else ""
        if channel == "whatsapp":
            if od > 30:
                body = ("Namaste {n} ji, this is Amit from Khandelwal Enterprises. {inv} for Rs {a} "
                        "is now {d} days past its due date ({due}). We value our association, but this "
                        "delay is hurting our working capital. Please share a firm payment date today, "
                        "or clear it on the UPI ID already shared. Happy to get on a call if anything "
                        "is pending from our side.").format(n=first, inv=num, a=amt, d=od, due=due)
            elif od > 0:
                body = ("Namaste {n} ji, gentle reminder from Khandelwal Enterprises - {inv} for "
                        "Rs {a} was due on {due} and is still open. If it has already been paid, "
                        "please share the UTR so we can reconcile. Otherwise requesting payment "
                        "this week. Thank you.").format(n=first, inv=num, a=amt, due=due)
            else:
                body = ("Namaste {n} ji, a quick note from Khandelwal Enterprises - {inv} for Rs {a} "
                        "falls due on {due}. Sharing it early so it stays on your payment list. "
                        "Thank you as always.").format(n=first, inv=num, a=amt, due=due)
        else:
            subj = ("Payment reminder - %s - Rs %s" % (num, amt)) if od <= 30 else \
                   ("Overdue %d days - %s - Rs %s - action requested" % (od, num, amt))
            body = ("Dear {n},\n\nThis is a reminder from Khandelwal Enterprises regarding {inv} "
                    "for Rs {a}, due on {due}.{extra}\n\nInvoice details:\n"
                    "  Invoice: {inv}\n  Amount due: Rs {a}\n  Due date: {due}\n\n"
                    "If payment is already made, please share the transaction reference so we can "
                    "reconcile our records. If there is any issue holding this up, reply to this "
                    "email and we will resolve it together.\n\nRegards,\nAmit Khandelwal\n"
                    "Khandelwal Enterprises Pvt Ltd, Jaipur").format(
                        n=c["contact"], inv=num, a=amt, due=due,
                        extra=(" It is now %d days overdue, and we request your urgent attention."
                               % od) if od > 0 else "")
        return {"channel": channel, "subject": subj if channel == "email" else None,
                "body": body, "grounding": {"invoice": num, "balance": amt,
                "days_overdue": od, "customer": c["name"]}}

    # ------------------------------------------------------------------
    # cash flow forecast
    # ------------------------------------------------------------------
    def _expected_date(self, inv):
        c = self.customers[inv["customer_id"]]
        due = _parse(inv["due_date"])
        for cm in sorted(self.ds["comms"], key=lambda x: x["date"], reverse=True):
            if cm["customer_id"] == c["id"] and "promised" in cm["summary"].lower():
                # a missed promise: expect roughly one more average-delay cycle
                return max(self.today, due) + timedelta(days=max(3, self.customer_delay(c) // 2))
        if due >= self.today:
            return due + timedelta(days=self.customer_delay(c))
        # already overdue: nearer the older it is not; assume one avg-delay window out
        return self.today + timedelta(days=max(3, self.customer_delay(c)))

    def forecast(self, horizon):
        def build(mult, adj):
            items, total = [], 0
            for inv in self.invoices.values():
                if inv["balance"] <= 0:
                    continue
                if self.disputes.get(inv.get("dispute_id") or "", {}).get("status") == "open":
                    continue  # disputes excluded until resolved
                exp = self._expected_date(inv) + timedelta(days=adj)
                if (exp - self.today).days <= horizon:
                    prob = self._probability(inv, mult)
                    amt = int(round(inv["balance"] * prob, -2))
                    items.append({"invoice_id": inv["id"], "number": inv["number"],
                                  "customer_id": inv["customer_id"],
                                  "customer": self.customers[inv["customer_id"]]["name"],
                                  "balance": inv["balance"], "expected_date": exp.isoformat(),
                                  "probability": prob, "expected_amount": amt})
                    total += amt
            items.sort(key=lambda x: x["expected_date"])
            return {"total": total, "items": items}
        weekly = self._weekly(horizon)
        return {"horizon": horizon,
                "scenarios": {"base": build(1.0, 0),
                              "delayed": build(0.85, 7),
                              "optimistic": build(1.0, -self._avg_delay_all())},
                "weekly": weekly,
                "assumptions": [
                    "Expected dates use each customer's measured average payment delay from their paid invoices.",
                    "Invoices under an open dispute are excluded until the dispute is resolved.",
                    "Missed promise-to-pay dates push the expectation out by roughly half the customer's usual delay.",
                    "Delayed scenario: every expected date slips a week and collection probability drops 15%.",
                    "Optimistic scenario: every customer pays on the invoice due date.",
                ]}

    def _avg_delay_all(self):
        ds = [self.customer_delay(c) for c in self.customers.values()]
        return int(sum(ds) / len(ds)) if ds else 0

    def _probability(self, inv, mult):
        c = self.customers[inv["customer_id"]]
        p = 0.9
        if c["late_payment_share"] is not None:
            p = 1 - 0.6 * c["late_payment_share"]
        if c["avg_delay_measured"] is None:
            p = 0.7  # new customer, unproven
        if inv["days_overdue"] > 90:
            p *= 0.6
        elif inv["days_overdue"] > 60:
            p *= 0.8
        return max(0.2, min(0.95, round(p * mult, 2)))

    def _weekly(self, horizon):
        weeks = []
        for w in range(0, max(1, horizon // 7)):
            start = self.today + timedelta(days=w * 7)
            end = start + timedelta(days=6)
            amt = 0
            for inv in self.invoices.values():
                if inv["balance"] <= 0:
                    continue
                if self.disputes.get(inv.get("dispute_id") or "", {}).get("status") == "open":
                    continue
                exp = self._expected_date(inv)
                if start <= exp <= end:
                    amt += int(round(inv["balance"] * self._probability(inv, 1.0), -2))
            weeks.append({"start": start.isoformat(), "end": end.isoformat(), "amount": amt})
        return weeks

    # ------------------------------------------------------------------
    # reports
    # ------------------------------------------------------------------
    def dso_series(self, months=8):
        out = []
        for m in range(months - 1, -1, -1):
            d0 = date(self.today.year, self.today.month, 1)
            month = (d0 - timedelta(days=30 * m)).replace(day=1)
            key = _month_key(month)
            sales = sum(i["amount"] for i in self.invoices.values()
                        if _month_key(_parse(i["issue_date"])) == key)
            recv = sum(i["balance"] for i in self.invoices.values()
                       if i["balance"] > 0 and _parse(i["issue_date"]) <=
                       (month + timedelta(days=40)).replace(day=1) - timedelta(days=1))
            dso = round(recv / sales * 30, 1) if sales else None
            out.append({"month": key, "dso": dso, "sales": sales, "receivables": recv})
        return out

    def customer_behaviour(self):
        rows = []
        for c in self.customers.values():
            rows.append({"id": c["id"], "name": c["name"], "city": c["city"],
                         "outstanding": c["outstanding"],
                         "avg_delay": c["avg_delay_measured"],
                         "late_share": c["late_payment_share"],
                         "open_invoices": len(c["open_invoices"]),
                         "risk": c["risk"]["level"],
                         "total_billed": sum(i["amount"] for i in self.invoices.values()
                                             if i["customer_id"] == c["id"])})
        rows.sort(key=lambda r: -r["total_billed"])
        return rows

    # ------------------------------------------------------------------
    # search / notifications / misc
    # ------------------------------------------------------------------
    def search(self, q):
        q = q.strip().lower()
        if len(q) < 2:
            return {"customers": [], "invoices": []}
        cs = [{"id": c["id"], "name": c["name"], "city": c["city"],
               "outstanding": c["outstanding"]}
              for c in self.customers.values()
              if q in c["name"].lower() or q in c["city"].lower() or q in c["contact"].lower()]
        invs = [{"id": i["id"], "number": i["number"],
                 "customer": self.customers[i["customer_id"]]["name"],
                 "customer_id": i["customer_id"], "balance": i["balance"],
                 "status": i["status"]}
                for i in self.invoices.values()
                if q in i["number"].lower() or q.replace(",", "") in str(i["amount"])]
        return {"customers": cs[:6], "invoices": invs[:6]}

    def notifications(self):
        n = []
        ac = self.action_centre()
        for p in ac["recent_payments"][:3]:
            n.append({"kind": "payment", "text": "%s paid Rs %s (%s)" % (
                p["customer"], _indian(p["amount"]), p["mode"]),
                "link": "#/invoices/%s" % p["invoice_id"], "date": p["date"]})
        for x in ac["newly_overdue"]:
            n.append({"kind": "overdue", "text": "%s (%s) just went overdue - Rs %s" % (
                x["number"], x["customer"], _indian(x["balance"])),
                "link": "#/invoices/%s" % x["invoice_id"],
                "date": (self.today - timedelta(days=x["days_overdue"])).isoformat()})
        for f in ac["followups_due"][:3]:
            n.append({"kind": "followup", "text": "Follow-up due: %s" % f["title"],
                      "link": "#/followups", "date": f["due_date"]})
        n.sort(key=lambda x: x["date"], reverse=True)
        return n[:8]

    def invoice_detail(self, inv_id):
        i = self.invoices.get(inv_id)
        if not i:
            return None
        c = self.customers[i["customer_id"]]
        comms = [cm for cm in self.ds["comms"]
                 if cm.get("invoice_id") == inv_id or
                 (cm["customer_id"] == i["customer_id"] and cm.get("invoice_id") is None)]
        fus = [self._fu_row(f) for f in self.ds["followups"]
               if f.get("invoice_seq") and "inv-%04d" % f["invoice_seq"] == inv_id]
        disp = self.disputes.get(i.get("dispute_id") or "")
        return {"invoice": i, "customer": self._cust_row(c),
                "customer_contact": {k: c[k] for k in ("contact", "phone", "email")},
                "comms": sorted(comms, key=lambda x: x["date"], reverse=True),
                "followups": fus, "dispute": disp}

    def customer_detail(self, cid):
        c = self.customers.get(cid)
        if not c:
            return None
        invs = sorted([i for i in self.invoices.values() if i["customer_id"] == cid],
                      key=lambda i: i["issue_date"], reverse=True)
        comms = sorted([cm for cm in self.ds["comms"] if cm["customer_id"] == cid],
                       key=lambda x: x["date"], reverse=True)
        payments = []
        for i in invs:
            for p in i["payments"]:
                payments.append({**p, "invoice": i["number"], "invoice_id": i["id"]})
        payments.sort(key=lambda p: p["date"], reverse=True)
        fus = [self._fu_row(f) for f in self.ds["followups"] if f["customer"] == cid]
        return {"customer": c, "invoices": invs, "comms": comms,
                "payments": payments, "followups": fus}


def _fmt(iso):
    d = _parse(iso)
    return "%02d/%02d/%04d" % (d.day, d.month, d.year)


def _indian(n):
    n = int(round(n))
    if n >= 10000000:
        v = n / 10000000.0
        return ("%g Cr" % round(v, 2))
    if n >= 100000:
        v = n / 100000.0
        return ("%g L" % round(v, 1))
    s = str(n)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:]); head = head[:-2]
        if head:
            parts.insert(0, head)
        return ",".join(parts) + "," + tail
    return s





def store_load(store_dir, today=None):
    ds = generate(today)
    events = _read_events(store_dir)
    for ev in events:
        apply_event(ds, ev)
    return ds


def apply_event(ds, ev):
    kind = ev.get("kind")
    if kind == "followup_complete":
        for f in ds["followups"]:
            if f["id"] == ev["id"]:
                f["status"] = "done"
                f["channel_done"] = ev.get("channel")
                f["completed_date"] = ev.get("date")
    elif kind == "followup_reschedule":
        for f in ds["followups"]:
            if f["id"] == ev["id"]:
                f["due_date"] = ev["due_date"]
    elif kind == "followup_response":
        for f in ds["followups"]:
            if f["id"] == ev["id"]:
                f["customer_response"] = ev.get("response")
    elif kind == "followup_create":
        ds["followups"].append(dict(
            id=ev["id"], customer=ev["customer"], invoice_seq=ev.get("invoice_seq"),
            kind=ev.get("channel", "call"), due_date=ev["due_date"], title=ev["title"],
            detail=ev.get("detail", ""), status="pending", channel_done=None,
            completed_date=None, customer_response=None))
    elif kind == "dispute_status":
        for d in ds["disputes"]:
            if d["id"] == ev["id"]:
                d["status"] = ev["status"]
                if ev["status"] == "resolved":
                    d["resolved_date"] = ev.get("date")
    elif kind == "settings":
        ds["settings"].update(ev.get("values", {}))
        ds["workspace"]["name"] = ds["settings"].get("workspace_name", ds["workspace"]["name"])


def store_record(store_dir, ev):
    os.makedirs(store_dir, exist_ok=True)
    events = _read_events(store_dir)
    ev.setdefault("date", date.today().isoformat())
    events.append(ev)
    path = os.path.join(store_dir, "events.json")
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(events, fh, indent=1)
    os.replace(tmp, path)


def _read_events(store_dir):
    path = os.path.join(store_dir, "events.json")
    if not os.path.exists(path):
        return []
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return []



BASE = os.path.dirname(os.path.abspath(__file__))
STATIC = BASE
STORE = os.path.join(BASE, "instance")


DATASET = store_load(STORE)
SVC = VasoolService(DATASET)


def reload_data():
    global DATASET, SVC
    DATASET = store_load(STORE)
    SVC = VasoolService(DATASET)


CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8", ".svg": "image/svg+xml",
    ".png": "image/png", ".ico": "image/x-icon", ".json": "application/json",
    ".woff2": "font/woff2", ".webmanifest": "application/manifest+json",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "VasoolAI/1.0"

    # ---------------- helpers ----------------
    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return {}

    def log_message(self, *a):
        pass

    # ---------------- routing ----------------
    def do_GET(self):
        path, _, qs = self.path.partition("?")
        params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
        if path.startswith("/api/"):
            return self._api_get(path, params)
        return self._static(path)

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path.startswith("/api/"):
            return self._api_post(path, self._body())
        self._json({"error": "not found"}, 404)

    # ---------------- static ----------------
    def _static(self, path):
        if path in ("/", ""):
            path = "/index.html"
        clean = os.path.normpath(path).lstrip("/")
        full = os.path.join(STATIC, clean)
        if not full.startswith(STATIC) or not os.path.isfile(full):
            # SPA fallback: unknown non-file paths load the app
            full = os.path.join(STATIC, "index.html")
        ext = os.path.splitext(full)[1]
        with open(full, "rb") as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPES.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ---------------- API GET ----------------
    def _api_get(self, path, params):
        s = SVC
        if path == "/api/bootstrap":
            return self._json({"workspace": DATASET["workspace"],
                               "settings": DATASET["settings"],
                               "today": s.today.isoformat(),
                               "version": "1.0.0",
                               "counts": {
                                   "open_invoices": s.kpis()["open_invoice_count"],
                                   "followups_due": len(s.action_centre()["followups_due"]),
                                   "open_disputes": len([d for d in DATASET["disputes"]
                                                         if d["status"] == "open"]),
                               }})
        if path == "/api/overview":
            return self._json({"kpis": s.kpis(), "ageing": s.ageing(),
                               "trend": s.monthly_trend(), "risk": s.risk_lists(),
                               "cashflow_preview": {str(h): s.forecast(h)["scenarios"]["base"]["total"]
                                                    for h in (7, 15, 30)},
                               "actions": s.action_centre(), "insights": s.insights(),
                               "sample_data": True})
        if path == "/api/invoices":
            invs = sorted(s.invoices.values(), key=lambda i: i["due_date"], reverse=True)
            return self._json({"invoices": [self._inv_row(i) for i in self._filter_invs(invs, params)]})
        m = re.fullmatch(r"/api/invoices/(inv-\d+)", path)
        if m:
            det = s.invoice_detail(m.group(1))
            return self._json(det) if det else self._json({"error": "not found"}, 404)
        if path == "/api/customers":
            rows = [s._cust_row(c) for c in s.customers.values()]
            for r, c in zip(rows, s.customers.values()):
                r.update(contact=c["contact"], phone=c["phone"], email=c["email"],
                         open_invoices=len(c["open_invoices"]),
                         total_billed=sum(i["amount"] for i in s.invoices.values()
                                          if i["customer_id"] == c["id"]))
            rows.sort(key=lambda r: -r["outstanding"])
            return self._json({"customers": rows})
        m = re.fullmatch(r"/api/customers/(c\d+)", path)
        if m:
            det = s.customer_detail(m.group(1))
            return self._json(det) if det else self._json({"error": "not found"}, 404)
        if path == "/api/collections":
            return self._json({"queue": s.collection_queue()})
        if path == "/api/followups":
            return self._json(s.followups())
        m = re.fullmatch(r"/api/followups/(f\d+)/draft", path)
        if m:
            d = s.draft(m.group(1), params.get("channel", "whatsapp"))
            return self._json(d) if d else self._json({"error": "not found"}, 404)
        if path == "/api/cashflow":
            h = int(params.get("horizon", "30"))
            if h not in (7, 15, 30):
                h = 30
            return self._json(s.forecast(h))
        if path == "/api/disputes":
            rows = []
            for d in DATASET["disputes"]:
                inv = s.invoices.get("inv-%04d" % d["invoice_seq"])
                rows.append({**d, "invoice_number": inv["number"] if inv else None,
                             "invoice_id": inv["id"] if inv else None,
                             "amount": inv["balance"] if inv else None,
                             "customer_name": s.customers[d["customer"]]["name"]})
            return self._json({"disputes": rows})
        if path == "/api/reports":
            return self._json({"ageing": s.ageing(), "trend": s.monthly_trend(),
                               "dso": s.dso_series(), "customers": s.customer_behaviour()})
        if path == "/api/search":
            return self._json(s.search(params.get("q", "")))
        if path == "/api/notifications":
            return self._json({"notifications": s.notifications()})
        return self._json({"error": "not found"}, 404)

    def _filter_invs(self, invs, params):
        q = (params.get("q") or "").strip().lower()
        status = params.get("status")
        bucket = params.get("bucket")
        cust = params.get("customer")
        out = []
        for i in invs:
            if status and i["status"] != status:
                continue
            if bucket and i.get("bucket") != bucket:
                continue
            if cust and i["customer_id"] != cust:
                continue
            if q:
                c = self._cust_name(i)
                if q not in i["number"].lower() and q not in c.lower():
                    continue
            out.append(i)
        return out

    def _cust_name(self, i):
        return SVC.customers[i["customer_id"]]["name"]

    def _inv_row(self, i):
        return {k: i[k] for k in ("id", "number", "amount", "amount_paid", "balance",
                                  "issue_date", "due_date", "status", "days_overdue",
                                  "days_to_due", "bucket", "customer_id")} | \
               {"customer": self._cust_name(i)}

    # ---------------- API POST ----------------
    def _api_post(self, path, body):
        m = re.fullmatch(r"/api/followups/(f[\w-]+)/complete", path)
        if m:
            store_record(STORE, {"kind": "followup_complete", "id": m.group(1),
                                 "channel": body.get("channel")})
            reload_data()
            return self._json({"ok": True})
        m = re.fullmatch(r"/api/followups/(f[\w-]+)/reschedule", path)
        if m:
            due = body.get("due_date", "")
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", due):
                return self._json({"error": "due_date must be YYYY-MM-DD"}, 400)
            store_record(STORE, {"kind": "followup_reschedule", "id": m.group(1), "due_date": due})
            reload_data()
            return self._json({"ok": True})
        m = re.fullmatch(r"/api/followups/(f[\w-]+)/response", path)
        if m:
            store_record(STORE, {"kind": "followup_response", "id": m.group(1),
                                 "response": (body.get("response") or "")[:500]})
            reload_data()
            return self._json({"ok": True})
        if path == "/api/followups":
            title = (body.get("title") or "").strip()[:140]
            cust = body.get("customer")
            if not title or cust not in SVC.customers:
                return self._json({"error": "title and valid customer required"}, 400)
            fid = "fu-" + uuid.uuid4().hex[:8]
            store_record(STORE, {"kind": "followup_create", "id": fid, "customer": cust,
                                 "invoice_seq": body.get("invoice_seq"),
                                 "channel": body.get("kind", "call"),
                                 "due_date": body.get("due_date") or SVC.today.isoformat(),
                                 "title": title, "detail": (body.get("detail") or "")[:300]})
            reload_data()
            return self._json({"ok": True, "id": fid})
        m = re.fullmatch(r"/api/disputes/(d\d+)/status", path)
        if m:
            if body.get("status") not in ("open", "resolved"):
                return self._json({"error": "status must be open or resolved"}, 400)
            store_record(STORE, {"kind": "dispute_status", "id": m.group(1),
                                 "status": body["status"]})
            reload_data()
            return self._json({"ok": True})
        if path == "/api/settings":
            allowed = {"workspace_name", "reminder_cadence_days", "auto_remind_before_due",
                       "default_terms_days", "weekly_summary_email"}
            vals = {k: v for k, v in body.items() if k in allowed}
            if "workspace_name" in vals:
                vals["workspace_name"] = str(vals["workspace_name"]).strip()[:80]
            store_record(STORE, {"kind": "settings", "values": vals})
            reload_data()
            return self._json({"ok": True})
        return self._json({"error": "not found"}, 404)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("PORT", "8000"))
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print("Vasool AI serving on http://0.0.0.0:%d" % port)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
