"""Turns the validated objects into what the person reads. Fixed parts (helplines, deadlines, legal aid,
disclaimer, law names) are always written by code, so they are never missing or wrong."""
from __future__ import annotations

from . import kb, rules
from .schemas import ISSUE_NAMES, Advice, Draft

FIXED = {
    "en": {"stand": "Where you stand", "options": "Your options", "today": "Do this today", "proof": "Proof to keep ready",
           "deadlines": "Deadlines (calculated from your dates)", "law": "Law", "days_left": "days left",
           "passed": "PASSED", "aid": "Free legal help: District Legal Services Authority at your district court, or call 15100 (NALSA). "
           "You may qualify for a free lawyer.",
           "disclaimer": "I am an AI legal helper, not a lawyer. This is general legal information for India, not legal advice. "
           "For a court case, talk to a lawyer or the free legal aid office.",
           "emergency": "Your safety comes first. Please call", "out": "This problem is outside what I can help with well. "
           "Please contact the free legal aid office (call 15100) or a lawyer."},
    "hi": {"stand": "आपकी स्थिति", "options": "आपके विकल्प", "today": "आज यह करें", "proof": "ये सबूत तैयार रखें",
           "deadlines": "समय-सीमा (आपकी बताई तारीखों से गिनी गई)", "law": "कानून", "days_left": "दिन बाकी",
           "passed": "निकल चुकी", "aid": "मुफ्त कानूनी मदद: अपने ज़िला न्यायालय में ज़िला विधिक सेवा प्राधिकरण (DLSA) से मिलें, या 15100 (NALSA) पर कॉल करें। "
           "आपको मुफ्त वकील मिल सकता है।",
           "disclaimer": "मैं एक AI कानूनी सहायक हूँ, वकील नहीं। यह भारत के कानून की सामान्य जानकारी है, कानूनी सलाह नहीं। "
           "कोर्ट केस के लिए किसी वकील या मुफ्त कानूनी सहायता कार्यालय से बात करें।",
           "emergency": "आपकी सुरक्षा सबसे पहले है। कृपया अभी कॉल करें", "out": "यह समस्या मेरे दायरे से बाहर है। "
           "कृपया मुफ्त कानूनी सहायता (15100) या किसी वकील से संपर्क करें।"},
}
FIXED["hinglish"] = FIXED["en"] | {
    "aid": "Free legal help: apne district court mein DLSA (District Legal Services Authority) se milein, ya 15100 (NALSA) par call karein. Aapko free vakeel mil sakta hai.",
    "disclaimer": "Main ek AI legal helper hoon, vakeel nahi. Yeh India ke kanoon ki general jaankari hai, legal advice nahi. Court case ke liye vakeel ya free legal aid office se baat karein.",
    "emergency": "Aapki safety sabse pehle hai. Abhi call karein"}


def fixed(lang: str) -> dict:
    return FIXED.get(lang, FIXED["hi"] if lang == "mr" else FIXED["en"])


def emergency_banner(flags: list[str], lang: str) -> str:
    if not flags:
        return ""
    f = fixed(lang)
    return "!! " + f["emergency"] + ": " + "; ".join(rules.HELPLINES[x] for x in flags) + " !!\n"


def deadlines_block(dl: list[dict], lang: str) -> str:
    if not dl:
        return ""
    f = fixed(lang)
    rows = []
    for d in dl:
        left = f"{d['days_left']} {f['days_left']}" if d["days_left"] >= 0 else f["passed"]
        rows.append(f"  - {d['what']}: by {d['by']} ({left}; rule: {d['rule']}, [{d['law_id']}])")
    return f"\n{f['deadlines']}:\n" + "\n".join(rows) + "\n"


def law_line(ids: list[str]) -> str:
    return "; ".join(f"[{i}] {kb.laws()[i]['law']}" for i in ids if i in kb.laws())


def advice_text(issue: str, adv: Advice, dl: list[dict], flags: list[str], lang: str) -> str:
    f = fixed(lang)
    out = [emergency_banner(flags, lang), f"== {ISSUE_NAMES[issue]} ==", f"\n{f['stand']}:\n{adv.where_you_stand}",
           f"\n{f['options']}:"]
    for n, o in enumerate(adv.options, 1):
        out.append(f"  {n}. {o.title}: {o.steps} ({o.cost_time})\n     {f['law']}: {law_line(o.law_ids)}")
    out.append(deadlines_block(dl, lang))
    out.append(f"{f['today']}: {adv.first_step_today}")
    out.append(f"\n{f['proof']}:\n" + "\n".join(f"  - {p}" for p in adv.proof_to_collect))
    out.append(f"\n{f['aid']}\n{f['disclaimer']}")
    return "\n".join(x for x in out if x)


def rules_advice(issue: str, entries: list[dict], dl: list[dict], flags: list[str], lang: str) -> str:
    """No-model answer: the matching law notes in plain English, plus code deadlines and fixed lines."""
    f = fixed(lang)
    out = [emergency_banner(flags, lang), f"== {ISSUE_NAMES[issue]} ==",
           "(Rules-only mode: no AI model was used, so this is in English and not tailored to your story.)"]
    if issue == "other":
        out.append(f["out"])
    for e in entries[:5]:
        out.append(f"\n* {e['title']} [{e['id']}: {e['law']}]\n  {e['plain']}")
    out.append(deadlines_block(dl, lang))
    out.append(f"\n{f['aid']}\n{f['disclaimer']}")
    return "\n".join(x for x in out if x)


DOC_TITLES = {"legal_notice": "LEGAL NOTICE", "consumer_complaint_letter": "COMPLAINT / REFUND DEMAND",
              "bank_fraud_complaint": "COMPLAINT OF UNAUTHORISED ELECTRONIC TRANSACTION",
              "reply_to_notice": "REPLY TO LEGAL NOTICE", "wage_claim_letter": "DEMAND FOR UNPAID WAGES"}


def draft_text(d: Draft) -> str:
    head = (f"{DOC_TITLES[d.doc_type]}\n\nDate: [DATE]\nFrom: [YOUR NAME], [YOUR ADDRESS], [YOUR PHONE]\n"
            f"To: [OTHER PARTY NAME], [OTHER PARTY ADDRESS]\nSent by: Speed Post / Registered Post AD and email\n\n"
            f"Subject: {d.subject}\n\n")
    body = "\n\n".join(d.body)
    refs = law_line(d.law_ids)
    tail = (f"\n\nLaw relied on: {refs}\n\nYours faithfully,\n\n[YOUR NAME]\n[SIGNATURE]\n\n"
            "Enclosures: copies of [LIST YOUR PROOF]. Keep the postal receipt and tracking printout.\n"
            "-- Drafted by an AI legal helper. Read every line, fill the [BRACKETS], and have it checked "
            "by a lawyer or the free legal aid office (15100) before sending. --")
    return head + body + tail


TEMPLATES = {  # rules-only drafts
    "deposit": ("legal_notice", "Demand for refund of security deposit of Rs {amt}", [
        "I was your tenant at [PROPERTY ADDRESS] under a rent agreement dated [AGREEMENT DATE], and I paid you a security deposit of Rs {amt}.",
        "I vacated the premises and handed over vacant possession and the keys on [DATE OF MOVING OUT]. All rent and bills up to that date were paid.",
        "Despite my requests on [DATES OF REQUESTS], you have not refunded the deposit, and you have not shown any lawful deduction.",
        "Withholding the deposit is a breach of our agreement, for which you are liable to refund it with compensation.",
        "I call upon you to refund Rs {amt} within 15 days of receiving this notice, failing which I will take legal action for recovery with interest and costs, at your risk."]),
    "consumer_refund": ("consumer_complaint_letter", "Refund of Rs {amt} for order/booking [ORDER ID]", [
        "I purchased [PRODUCT/SERVICE] from you on [DATE] under order/booking number [ORDER ID] and paid Rs {amt}.",
        "[DESCRIBE THE PROBLEM: not delivered / defective / cancelled / refund promised but not paid].",
        "I raised the issue with your customer care on [DATES] (ticket [TICKET NO.]) but it has not been resolved.",
        "This is a deficiency in service and an unfair trade practice under the Consumer Protection Act, 2019.",
        "Please refund Rs {amt} within 15 days. Otherwise I will register a grievance with the National Consumer Helpline (1915) and file a complaint before the District Consumer Commission, claiming the refund, compensation and costs."]),
    "salary": ("wage_claim_letter", "Payment of unpaid wages of Rs {amt}", [
        "I worked with your organisation as [DESIGNATION] from [JOINING DATE] to [LAST WORKING DAY / till date].",
        "My wages of Rs {amt} for [MONTHS] have not been paid, though they are long overdue.",
        "Under the Code on Wages, 2019, wages must be paid on time, and all dues must be paid within two working days of an employee leaving.",
        "Please pay Rs {amt} within 15 days of this letter. Otherwise I will file a claim before the Labour Department authority for the wages and compensation."]),
    "cheque_bounce": ("legal_notice", "Demand notice under Section 138 of the Negotiable Instruments Act, 1881", [
        "You issued me cheque no. [CHEQUE NO.] dated [CHEQUE DATE] for Rs {amt}, drawn on [BANK NAME], towards [REASON FOR PAYMENT].",
        "I presented the cheque, and it was returned unpaid with the remark '[REASON ON MEMO]' by return memo dated [MEMO DATE].",
        "I hereby demand payment of Rs {amt} within 15 days of receipt of this notice.",
        "If you fail to pay within 15 days, I will file a complaint against you under Section 138 read with Section 142 of the Negotiable Instruments Act, 1881, at your risk as to costs and consequences."]),
    "notice_reply": ("reply_to_notice", "Reply to your notice dated [NOTICE DATE]", [
        "I have received your notice dated [NOTICE DATE] sent on behalf of [SENDER NAME].",
        "The claims made in the notice are denied, except what is specifically admitted here.",
        "[STATE YOUR SIDE, POINT BY POINT, WITH DATES].",
        "Nothing in this reply is an admission of any liability. I reserve all my rights and remedies."]),
    "cyber_fraud": ("bank_fraud_complaint", "Unauthorised debit of Rs {amt} from account [ACCOUNT NO.]", [
        "On [DATE AND TIME], Rs {amt} was debited from my account no. [ACCOUNT NO.] in an unauthorised transaction (transaction ID [TXN ID]). I did not authorise it.",
        "I have reported the fraud to the cyber crime helpline 1930 / cybercrime.gov.in (acknowledgement no. [ACK NO.]).",
        "Under the RBI circular of 6 July 2017 on customer liability in unauthorised electronic transactions, I request you to block further debits, credit the amount, and give me a written acknowledgement of this complaint.",
        "Please reply within 10 days."]),
}
EXPECTED_DAYS = {"legal_notice": 15, "consumer_complaint_letter": 15, "wage_claim_letter": 15, "bank_fraud_complaint": 10,
                 "reply_to_notice": None}
DOC_FOR_ISSUE = {"deposit": "legal_notice", "consumer_refund": "consumer_complaint_letter", "salary": "wage_claim_letter",
                 "cheque_bounce": "legal_notice", "notice_reply": "reply_to_notice", "cyber_fraud": "bank_fraud_complaint"}
LAWS_FOR_TEMPLATE = {"deposit": ["DEP-1", "DEP-3"], "consumer_refund": ["CON-1", "CON-5"], "salary": ["SAL-1", "SAL-2"],
                     "cheque_bounce": ["CHQ-1", "CHQ-2", "CHQ-3"], "notice_reply": ["NOT-1", "NOT-3"], "cyber_fraud": ["CYB-1", "CYB-2"]}


def rules_draft(issue: str, amount: float | None) -> Draft | None:
    if issue not in TEMPLATES:
        return None
    doc_type, subject, paras = TEMPLATES[issue]
    amt = f"{amount:,.0f}" if amount else "[AMOUNT]"
    return Draft(doc_type=doc_type, subject=subject.format(amt=amt), body=[p.format(amt=amt) for p in paras],
                 demand_amount=amount if doc_type != "reply_to_notice" else None,
                 reply_days=EXPECTED_DAYS[doc_type], law_ids=LAWS_FOR_TEMPLATE[issue])
