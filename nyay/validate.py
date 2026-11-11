"""Code checks on everything the model returns. An answer that breaks a rule goes back to the model once with the
exact errors; whatever is still wrong is fixed by code where possible (drop the bad citation / the invented amount)
or flagged."""
from __future__ import annotations

import re
from datetime import date

from . import kb, rules
from .schemas import Advice, CaseFile, Draft

BANNED = ["guarantee", "guaranteed", "100%", "definitely win", "surely win", "will win", "sure to win", "pakka jeet",
          "zaroor jeet", "जरूर जीत", "पक्का जीत", "ignore the summons", "ignore the court", "no need to reply to the summons",
          "take the law into", "threaten them"]
SECTION_RE = re.compile(r"(?<![A-Za-z])(?:section|sec\.?|s\.|धारा|dhara)\s*(\d+[A-Z]?)", re.I)   # not 'Rs. 25,000'


def verify_case(case: CaseFile, user_text: str, today: date) -> tuple[CaseFile, list[str]]:
    """Drop amounts and dates the person never said. Returns the cleaned case and a log."""
    log = []
    said = rules.numbers_in_text(user_text)
    keep = []
    for a in case.amounts:
        ok = rules.amount_in_text(a.value, user_text)
        derived = any(abs(a.value - k * v) < 1 for v in said for k in range(2, 13)) or (len(said) > 1 and abs(a.value - sum(said)) < 1)
        if ok or derived:
            keep.append(a)
        else:
            log.append(f"removed amount Rs {a.value:,.0f} ({a.what}): not in the person's words")
    case.amounts = keep
    for e in case.timeline:
        if e.date:
            try:
                d = date.fromisoformat(e.date)
            except ValueError:
                log.append(f"bad date '{e.date}' removed")
                e.date = None
                continue
            if d > today:
                log.append(f"future date {e.date} for '{e.what}' removed")
                e.date = None
    return case, log


def allowed_sections(ids: list[str]) -> set[str]:
    secs = set()
    for i in ids:
        e = kb.laws().get(i)
        if e:
            secs.update(m.upper() for m in re.findall(r"s\.(\d+[A-Z]?)", e["law"]))
            for a, b in re.findall(r"s\.(\d+)-(\d+)", e["law"]):          # 's.19-21' allows 19, 20, 21
                secs.update(str(n) for n in range(int(a), int(b) + 1))
            secs.update(m.upper() for m in re.findall(r"Order\s+([IVXL]+)", e["law"]))
    return secs


def check_advice(adv: Advice, allowed_ids: list[str], lang: str) -> list[str]:
    errs = []
    used = set(adv.law_ids) | {i for o in adv.options for i in o.law_ids}
    bad = sorted(i for i in used if i not in allowed_ids)
    if bad:
        errs.append(f"cites law ids that were not given: {bad}. Use only {allowed_ids}.")
    if not adv.options:
        errs.append("no options given")
    text = " ".join([adv.where_you_stand, adv.first_step_today] + [o.title + " " + o.steps + " " + o.cost_time for o in adv.options])
    secs = allowed_sections([i for i in used if i in allowed_ids])
    invented = sorted({s.upper() for s in SECTION_RE.findall(text)} - secs)
    if invented:
        errs.append(f"mentions section numbers not in the cited notes: {invented}. Remove them or cite the right note.")
    low = text.lower()
    hits = [b for b in BANNED if b in low]
    if hits:
        errs.append(f"makes promises or risky statements: {hits}")
    if not rules.script_matches(adv.where_you_stand + " " + adv.first_step_today, lang):
        errs.append(f"not written in {rules.LANG_NAMES.get(lang, lang)} script; rewrite every text field in it")
    return errs


def fix_advice(adv: Advice, allowed_ids: list[str]) -> list[str]:
    """Last resort after the repair round: drop citations we cannot stand behind."""
    log = []
    for o in adv.options:
        bad = [i for i in o.law_ids if i not in allowed_ids]
        if bad:
            o.law_ids = [i for i in o.law_ids if i in allowed_ids]
            log.append(f"dropped unknown citations {bad} from option '{o.title}'")
    adv.law_ids = sorted({i for i in adv.law_ids if i in allowed_ids} | {i for o in adv.options for i in o.law_ids})
    return log


NAME_RE = re.compile(r"\b(?:Mr|Mrs|Ms|Shri|Smt|Sri|Dr)\.?\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)")


def check_draft(d: Draft, case: CaseFile, user_text: str, allowed_ids: list[str], expected_days: int | None) -> list[str]:
    errs = []
    body = "\n".join(d.body)
    verified = [a.value for a in case.amounts]
    if d.demand_amount is not None and verified and not any(abs(d.demand_amount - v) < 1 for v in verified):
        errs.append(f"demand_amount {d.demand_amount:,.0f} is not an amount in the case file {verified}")
    for v in rules.extract_amounts(body):
        if verified and not any(abs(v - x) < 1 for x in verified) and not rules.amount_in_text(v, user_text):
            errs.append(f"the letter mentions Rs {v:,.0f}, which is not in the case file")
    if expected_days is not None and d.reply_days != expected_days:
        errs.append(f"reply_days must be {expected_days}, got {d.reply_days}")
    bad = [i for i in d.law_ids if i not in allowed_ids]
    if bad:
        errs.append(f"cites law ids that were not given: {bad}")
    invented = sorted({s.upper() for s in SECTION_RE.findall(body)} - allowed_sections([i for i in d.law_ids if i in allowed_ids]))
    if invented:
        errs.append(f"mentions sections not in the cited notes: {invented}")
    for name in NAME_RE.findall(body):
        if name.split()[0].lower() not in user_text.lower():
            errs.append(f"invented a name '{name}'; use a placeholder like [OTHER PARTY NAME]")
    if "[YOUR NAME]" not in body and "[YOUR NAME]" not in d.subject:
        pass  # code adds the signature block with [YOUR NAME]
    hits = [b for b in BANNED if b in body.lower()]
    if hits:
        errs.append(f"risky wording: {hits}")
    return errs
