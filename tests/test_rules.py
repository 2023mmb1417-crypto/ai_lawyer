"""Unit tests for the plain-code parts (no model, no network):  python -m pytest -q"""
from datetime import date

import pytest

from nyay import kb, render, rules, validate
from nyay.agent import Session
from nyay.schemas import Advice, Amount, CaseFile, Draft, Event, Option

TODAY = date(2026, 11, 11)   # a Wednesday


# ---------------------------------------------------------------- language
@pytest.mark.parametrize("text,lang", [
    ("My landlord is not returning my deposit of Rs 50,000.", "en"),
    ("मकान मालिक मेरा डिपॉजिट वापस नहीं कर रहा है।", "hi"),
    ("bhai mera landlord deposit wapas nahi kar raha, kya karu?", "hinglish"),
    ("நான் ஆன்லைன் கடையில் ஷூ ஆர்டர் செய்தேன்.", "ta"),
    ("আমার অ্যাকাউন্ট থেকে টাকা কেটে নেওয়া হয়েছে", "bn"),
    ("माझे पैसे परत हवे आहेत, ते परतावा देत नाहीत आहे", "mr"),
])
def test_detect_language(text, lang):
    assert rules.detect_language(text) == lang


def test_script_matches():
    assert rules.script_matches("आपका डिपॉजिट वापस मिलना चाहिए।", "hi")
    assert not rules.script_matches("You should get your deposit back.", "hi")
    assert rules.script_matches("Aapko deposit wapas milna chahiye.", "hinglish")


# ---------------------------------------------------------------- safety
@pytest.mark.parametrize("text,flag", [
    ("My husband beats me every night", "violence"),
    ("मैं आत्महत्या करने की सोच रहा हूँ", "self_harm"),
    ("Mere bhai ko police ne pakad liya", "custody"),
])
def test_triage_flags_emergencies(text, flag):
    assert flag in rules.triage(text)


def test_triage_quiet_on_normal_problem():
    assert rules.triage("Flipkart did not refund my Rs 999 order") == []


# ---------------------------------------------------------------- classifier
@pytest.mark.parametrize("text,issue", [
    ("Landlord kept my security deposit after I vacated", "deposit"),
    ("Amazon is not giving my refund for a damaged mixer", "consumer_refund"),
    ("Company has not paid my salary for 2 months", "salary"),
    ("The cheque my friend gave bounced, bank gave return memo", "cheque_bounce"),
    ("I received a legal notice from my landlord's lawyer", "notice_reply"),
    ("Someone took my OTP and money was debited, it was a scam", "cyber_fraud"),
    ("मुझे बैंक से नोटिस आया है", "notice_reply"),
    ("I want a divorce", "other"),
])
def test_classify(text, issue):
    assert rules.classify(text)[0] == issue


# ---------------------------------------------------------------- amounts
@pytest.mark.parametrize("text,value", [
    ("deposit was Rs 60,000", 60000), ("₹18,999 phone", 18999), ("Rs 2,00,000 loan", 200000),
    ("25k diya tha", 25000), ("1.5 lakh transfer", 150000), ("20,000 रुपये", 20000), ("2 लाख", 200000),
    ("5,000 ரூபாய்க்கு", 5000), ("2,500 रुपयांचा", 2500),
])
def test_extract_amounts(text, value):
    assert value in rules.extract_amounts(text)


def test_small_numbers_are_not_amounts():
    assert rules.extract_amounts("I waited 2 months and 15 days") == []


# ---------------------------------------------------------------- dates
@pytest.mark.parametrize("text,want", [
    ("moved out on 30 September 2026", date(2026, 9, 30)), ("on 15/03/2026", date(2026, 3, 15)),
    ("15 अगस्त 2026 को", date(2026, 8, 15)), ("2 months ago", date(2026, 9, 12)),
    ("3 din pehle", date(2026, 11, 8)), ("yesterday", date(2026, 11, 10)), ("on 5 Nov", date(2026, 11, 5)),
])
def test_extract_dates(text, want):
    assert want in rules.extract_dates(text, TODAY)


def test_date_without_year_is_never_in_future():
    assert rules.extract_dates("on 20 December", TODAY) == [date(2025, 12, 20)]


# ---------------------------------------------------------------- deadlines (hand-computed from the law notes)
def by(dl, law_id):
    return [d["by"] for d in dl if d["law_id"] == law_id]


def test_cheque_deadlines():
    dl = rules.deadlines("cheque_bounce", [{"type": "cheque_return_memo", "date": date(2026, 11, 1)}], TODAY)
    assert by(dl, "CHQ-2") == ["2026-12-01"]          # 30 days from memo
    assert by(dl, "CHQ-3") == ["2027-01-16"]          # +15 days to pay, then 1 month


def test_cheque_deadline_passed_is_negative():
    dl = rules.deadlines("cheque_bounce", [{"type": "cheque_return_memo", "date": date(2026, 9, 20)}], TODAY)
    assert dl[0]["days_left"] < 0


def test_fraud_working_days_skip_weekend():
    dl = rules.deadlines("cyber_fraud", [{"type": "fraud_transaction", "date": TODAY}], TODAY)
    assert by(dl, "CYB-2") == ["2026-11-16"]          # Wed -> Thu, Fri, Mon


def test_salary_two_working_days():
    dl = rules.deadlines("salary", [{"type": "last_working_day", "date": date(2026, 8, 31)}], TODAY)
    assert by(dl, "SAL-1") == ["2026-09-02"] and by(dl, "SAL-2") == ["2029-08-31"]


def test_consumer_two_years_and_leap_safe():
    dl = rules.deadlines("consumer_refund", [{"type": "purchase", "date": date(2024, 2, 29)}], TODAY)
    assert by(dl, "CON-3") == ["2026-02-28"]


# ---------------------------------------------------------------- knowledge base
def test_kb_ids_unique_and_complete():
    ids = list(kb.laws())
    assert len(ids) == len(set(ids)) >= 25
    for e in kb.laws().values():
        assert e["plain"] and e["law"] and e["source"].startswith("http") and e["issues"]


def test_every_template_and_deadline_cites_real_notes():
    for ids in render.LAWS_FOR_TEMPLATE.values():
        assert all(i in kb.laws() for i in ids)


def test_retrieve_stays_on_issue():
    got = [e["id"] for e in kb.retrieve("cheque_bounce", "cheque returned unpaid")]
    assert got[0].startswith("CHQ") and "CON-1" not in got


# ---------------------------------------------------------------- validators
def make_advice(**kw):
    base = dict(where_you_stand="The law is on your side.", first_step_today="Send a notice.",
                options=[Option(title="Notice", steps="Send it.", cost_time="Rs 50", law_ids=["DEP-3"])],
                proof_to_collect=["agreement"], law_ids=["DEP-3"])
    return Advice(**(base | kw))


def test_advice_unknown_citation_is_caught():
    adv = make_advice(law_ids=["DEP-3", "XYZ-9"])
    assert any("not given" in e for e in validate.check_advice(adv, ["DEP-3"], "en"))


def test_advice_invented_section_is_caught():
    adv = make_advice(where_you_stand="Under Section 420 you will get it back.")
    assert any("420" in e for e in validate.check_advice(adv, ["DEP-3"], "en"))


def test_advice_rupee_amount_is_not_a_section():
    adv = make_advice(where_you_stand="Your deposit of Rs. 25,000 must be returned.")
    assert validate.check_advice(adv, ["DEP-3"], "en") == []


def test_advice_promise_is_caught():
    adv = make_advice(where_you_stand="You will definitely win this case.")
    assert any("promises" in e for e in validate.check_advice(adv, ["DEP-3"], "en"))


def test_advice_wrong_language_is_caught():
    adv = make_advice()
    assert any("script" in e for e in validate.check_advice(adv, ["DEP-3"], "hi"))


def test_verify_case_drops_invented_amount_and_future_date():
    text = "My deposit was Rs 40,000 and I left in October."
    case = CaseFile(issue="deposit", summary="x", amounts=[Amount(value=40000, quote="Rs 40,000", what="deposit"),
                                                           Amount(value=55000, quote="", what="made up")],
                    timeline=[Event(date="2027-01-01", type="moved_out", what="left")])
    case, log = validate.verify_case(case, text, TODAY)
    assert [a.value for a in case.amounts] == [40000] and case.timeline[0].date is None and len(log) == 2


def test_verify_case_keeps_derived_salary_total():
    text = "2 mahine ki salary nahi di, 18000 per month"
    case = CaseFile(issue="salary", summary="x", amounts=[Amount(value=36000, quote="", what="total")])
    assert validate.verify_case(case, text, TODAY)[0].amounts


def test_draft_checks():
    case = CaseFile(issue="deposit", summary="x", amounts=[Amount(value=30000, quote="Rs 30,000", what="deposit")])
    good = Draft(doc_type="legal_notice", subject="Refund", body=["Refund Rs 30,000 within 15 days."], demand_amount=30000,
                 reply_days=15, law_ids=["DEP-1"])
    assert validate.check_draft(good, case, "deposit Rs 30,000", ["DEP-1"], 15) == []
    bad = Draft(doc_type="legal_notice", subject="Refund", body=["Mr. Ramesh Gupta must pay Rs 45,000 under Section 406."],
                demand_amount=45000, reply_days=7, law_ids=["DEP-1"])
    errs = " ".join(validate.check_draft(bad, case, "deposit Rs 30,000", ["DEP-1"], 15))
    assert "45,000" in errs and "reply_days" in errs and "406" in errs and "Ramesh" in errs


# ---------------------------------------------------------------- rules-only session end to end
def test_rules_only_session_cheque():
    s = Session(today=TODAY)
    r = s.send("My friend's cheque of Rs 50,000 bounced. Bank return memo came on 1 November 2026.")
    assert r["kind"] == "advice" and r["issue"] == "cheque_bounce"
    assert "2026-12-01" in r["answer"] and "15100" in r["answer"]
    d = s.draft()
    assert "50,000" in d["text"] and "[YOUR NAME]" in d["text"]


def test_rules_only_asks_followup_then_answers():
    s = Session(today=TODAY)
    assert s.send("My landlord is not returning my deposit")["kind"] == "followup"
    r = s.send("It was Rs 30,000 and I moved out on 1 October 2026")
    assert r["kind"] == "advice" and "2029-10-01" in r["answer"]


def test_emergency_banner_first():
    s = Session(today=TODAY)
    r = s.send("My husband beats me and threatened to kill me")
    assert r["answer"].startswith("!!") and "181" in r["answer"]


def test_indian_digits():
    assert 10000 in rules.extract_amounts("১০,০০০ টাকা")
    assert rules.amount_in_text(10000, "আমার অ্যাকাউন্ট থেকে ১০,০০০ টাকা কেটে নেওয়া হয়েছে")
