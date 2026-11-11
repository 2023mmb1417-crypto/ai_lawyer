"""The conversation: one Session per person.

  message ─► triage (code) ─► language (code) ─► understand (LLM → CaseFile) ─► verify facts (code)
          ─► missing details? (code) ── yes ─► ask follow-up questions (LLM phrases them) ─► wait for reply
                                      └─ no ──► retrieve law notes (RAG) ─► deadlines (code)
                                                ─► advise (LLM → Advice) ─► check (code) ─► repair (LLM, once)
                                                ─► render (code adds deadlines, helplines, legal aid, disclaimer)
  /draft    ─► draft (LLM → Draft) ─► check (code) ─► repair (LLM, once) ─► letter with [PLACEHOLDERS]
  /practice ─► the model plays the other side; 'END' gives coaching
  judge     ─► a different model scores each answer (batch runs)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from . import kb, prompts, render, rules, validate
from .llm import LLM
from .schemas import Advice, CaseFile, Draft, FollowUp, JudgeScore


def script_note(lang: str) -> str:
    return {"hinglish": " (Hindi words written in English letters, like the person wrote)",
            "hi": " (Devanagari script)", "mr": " (Devanagari script)"}.get(lang, " (in that language's own script)" if lang != "en" else "")


def with_safety_notes(entries: list[dict], flags: list[str]) -> list[dict]:
    """Emergency notes go first when triage fired; free legal aid is always available to cite."""
    extra = []
    if flags:
        extra = ["GEN-4", "GEN-1"] + (["GEN-5"] if "violence" in flags else [])
    out, seen = [], set()
    for e in [kb.laws()[i] for i in extra] + entries + [kb.laws()["GEN-1"]]:
        if e["id"] not in seen:
            out.append(e)
            seen.add(e["id"])
    return out


@dataclass
class Session:
    lawyer: LLM | None = None              # None = rules-only mode
    judge: LLM | None = None
    drafter: LLM | None = None             # letters; defaults to the lawyer model
    today: date = field(default_factory=date.today)
    messages: list[str] = field(default_factory=list)
    lang: str = "en"
    flags: list[str] = field(default_factory=list)
    case: CaseFile | None = None
    asked_followup: bool = False
    log: list[str] = field(default_factory=list)
    allowed_ids: list[str] = field(default_factory=list)
    deadlines: list[dict] = field(default_factory=list)
    advice: Advice | None = None
    answer: str = ""
    practice: list[tuple[str, str]] = field(default_factory=list)

    @property
    def story(self) -> str:
        return "\n".join(self.messages)

    # ------------------------------------------------------------------ main turn
    def send(self, message: str) -> dict:
        self.messages.append(message.strip())
        if len(self.messages) == 1 or len(message) > 40:
            self.lang = rules.detect_language(self.story)
        self.flags = sorted(set(self.flags) | set(rules.triage(message)))
        rule_issue, _ = rules.classify(self.story)
        if self.lawyer is None:
            return self._rules_turn(rule_issue)

        system = prompts.UNDERSTAND.format(today=self.today.isoformat(), rule_issue=rule_issue)
        case, _ = self.lawyer.structured(CaseFile, system, self.story)
        case, vlog = validate.verify_case(case, self.story, self.today)
        self.case, self.log = case, self.log + vlog
        if case.issue == "other" and rule_issue != "other" and not self.flags:
            self.log.append(f"model said 'other', rules said '{rule_issue}': kept model")
        events = {e.type for e in case.timeline if e.date or e.date_text}
        missing = rules.missing_fields(case.issue, bool(case.amounts), case.other_side, events)
        if missing and not self.asked_followup and not self.flags and case.issue != "other":
            self.asked_followup = True
            qs = [q for _, q in missing]
            fu, _ = self.lawyer.structured(FollowUp, prompts.FOLLOWUP.format(language=rules.LANG_NAMES.get(self.lang, "English"),
                                                                             script_note=script_note(self.lang)), "\n".join(qs))
            text = "\n".join(fu.questions)
            if not rules.script_matches(text, self.lang):
                self.log.append("follow-up questions came back in the wrong script; used code questions")
                text = "\n".join(rules.HINDI_Q.get(q, q) if self.lang in ("hi", "mr") else q for q in qs)
            self.answer = render.emergency_banner(self.flags, self.lang) + text
            return self._result("followup", missing=[m for m, _ in missing])
        return self._advise()

    def _advise(self) -> dict:
        case = self.case
        entries = with_safety_notes(kb.retrieve(case.issue, case.summary), self.flags)
        self.allowed_ids = [e["id"] for e in entries]
        events = [{"type": e.type, "date": date.fromisoformat(e.date)} for e in case.timeline if e.date]
        self.deadlines = rules.deadlines(case.issue, events, self.today)
        dl_txt = "\n".join(f"- {d['what']}: by {d['by']} ({d['days_left']} days from today) [{d['law_id']}]" for d in self.deadlines) or "none"
        system = prompts.ADVISE.format(language=rules.LANG_NAMES.get(self.lang, "English"), script_note=script_note(self.lang),
                                       laws=kb.render(entries), deadlines=dl_txt)
        user = f"Person's own words:\n{self.story}\n\nCase file:\n{case.model_dump_json(indent=1)}"
        adv, _ = self.lawyer.structured(Advice, system, user)
        errs = validate.check_advice(adv, self.allowed_ids, self.lang)
        repaired = False
        if errs:
            self.log.append("advice check failed: " + " | ".join(errs))
            adv2, _ = self.lawyer.structured(Advice, system, user + "\n\nYour previous answer broke these rules, fix them:\n- "
                                             + "\n- ".join(errs) + f"\n\nPrevious answer:\n{adv.model_dump_json()}")
            errs2 = validate.check_advice(adv2, self.allowed_ids, self.lang)
            repaired = True
            if len(errs2) <= len(errs):
                adv, errs = adv2, errs2
            self.log.append("after repair: " + (" | ".join(errs) if errs else "all checks pass"))
        self.log += validate.fix_advice(adv, self.allowed_ids)
        self.advice = adv
        self.answer = render.advice_text(case.issue, adv, self.deadlines, self.flags, self.lang)
        return self._result("advice", errors=errs, repaired=repaired)

    def _rules_turn(self, issue: str) -> dict:
        dates = rules.extract_dates(self.story, self.today)
        amounts = rules.extract_amounts(self.story)
        ev_type = {"deposit": "moved_out", "cheque_bounce": "cheque_return_memo", "notice_reply": "notice_received",
                   "salary": "salary_due", "cyber_fraud": "fraud_transaction", "consumer_refund": "problem"}.get(issue)
        # rules cannot tell which date is which, so use the latest date for the key event
        events = [{"type": ev_type, "date": max(dates)}] if dates and ev_type else []
        missing = [(f, q) for f, q in rules.missing_fields(issue, bool(amounts), "?", {e["type"] for e in events})]
        if missing and not self.asked_followup and not self.flags:
            self.asked_followup = True
            self.case = CaseFile(issue=issue, summary=self.story[:300])
            qs = [rules.HINDI_Q.get(q, q) if self.lang in ("hi", "mr") else q for _, q in missing]
            self.answer = "To help you properly I need a few details:\n" + "\n".join(qs) if self.lang not in ("hi", "mr") \
                else "आपकी सही मदद के लिए कुछ जानकारी चाहिए:\n" + "\n".join(qs)
            return self._result("followup", missing=[m for m, _ in missing])
        self.case = CaseFile(issue=issue, summary=self.story[:300], amounts=[
            {"value": a, "quote": "", "what": "amount mentioned"} for a in amounts],
            timeline=[{"date": e["date"].isoformat(), "type": e["type"], "what": "key date (rules guess)"} for e in events])
        entries = with_safety_notes(kb.retrieve(issue, self.story), self.flags)
        self.allowed_ids = [e["id"] for e in entries]
        self.deadlines = rules.deadlines(issue, events, self.today)
        self.answer = render.rules_advice(issue, entries, self.deadlines, self.flags, self.lang)
        return self._result("advice", errors=[], repaired=False)

    # ------------------------------------------------------------------ documents
    def draft(self) -> dict:
        case = self.case
        if case is None or case.issue not in render.DOC_FOR_ISSUE:
            return {"ok": False, "text": "", "errors": ["no document for this kind of problem"], "repaired": False}
        amount = max((a.value for a in case.amounts), default=None)
        if self.lawyer is None:
            d = render.rules_draft(case.issue, amount)
            return {"ok": True, "draft": d.model_dump(), "text": render.draft_text(d), "errors": [], "repaired": False}
        doc_type = render.DOC_FOR_ISSUE[case.issue]
        rule_key = "cheque_notice" if case.issue == "cheque_bounce" else doc_type
        ids = render.LAWS_FOR_TEMPLATE[case.issue] + [i for i in self.allowed_ids if i not in render.LAWS_FOR_TEMPLATE[case.issue]][:3]
        entries = [kb.laws()[i] for i in ids]
        system = prompts.DRAFT.format(doc_type=doc_type, law_ids=ids, doc_rule=prompts.DOC_RULES[rule_key], laws=kb.render(entries))
        user = f"Case file:\n{case.model_dump_json(indent=1)}\n\nPerson's own words:\n{self.story}"
        writer = self.drafter or self.lawyer
        d, _ = writer.structured(Draft, system, user)
        d.doc_type = doc_type
        exp = render.EXPECTED_DAYS[doc_type]
        errs = validate.check_draft(d, case, self.story, ids, exp)
        repaired = False
        if errs:
            self.log.append("draft check failed: " + " | ".join(errs))
            d2, _ = self.lawyer.structured(Draft, system, user + "\n\nYour previous draft broke these rules, fix them:\n- "
                                           + "\n- ".join(errs) + f"\n\nPrevious draft:\n{d.model_dump_json()}")
            d2.doc_type = doc_type
            errs2 = validate.check_draft(d2, case, self.story, ids, exp)
            repaired = True
            if len(errs2) <= len(errs):
                d, errs = d2, errs2
        d.law_ids = [i for i in d.law_ids if i in ids]
        return {"ok": not errs, "draft": d.model_dump(), "text": render.draft_text(d), "errors": errs, "repaired": repaired}

    # ------------------------------------------------------------------ practice: the model plays the other side
    def practise(self, message: str) -> str:
        if self.lawyer is None:
            return "Practice mode needs a model (it is off in rules-only mode)."
        role = {"landlord": "the landlord", "company": "the company's customer-care manager", "employer": "the employer / HR manager",
                "bank": "the bank's branch manager", "individual": "the person who owes the money"}.get(
            self.case.other_side_type if self.case else "unknown", "the other party")
        if self.case and self.case.other_side:
            role += f" ({self.case.other_side})"
        system = prompts.OPPONENT.format(role=role, summary=self.case.summary if self.case else self.story,
                                         language=rules.LANG_NAMES.get(self.lang, "English"))
        self.practice.append(("user", message))
        reply = self.lawyer.text(system, self.practice)
        self.practice.append(("assistant", reply))
        return reply

    # ------------------------------------------------------------------ second-model check
    def grade(self) -> dict | None:
        if self.judge is None or not self.answer or self.advice is None:
            return None
        entries = kb.render([kb.laws()[i] for i in self.allowed_ids])
        s, spec = self.judge.structured(JudgeScore, prompts.JUDGE,
                                        f"PERSON'S MESSAGE:\n{self.story}\n\nLAW NOTES:\n{entries}\n\nBOT ANSWER:\n{self.answer}")
        return s.model_dump() | {"judge": spec}

    def _result(self, kind: str, **kw) -> dict:
        return {"kind": kind, "lang": self.lang, "flags": self.flags, "issue": self.case.issue if self.case else None,
                "case": self.case.model_dump() if self.case else None, "deadlines": self.deadlines,
                "law_ids": self.advice.law_ids if (self.advice and kind == "advice") else self.allowed_ids if kind == "advice" else [],
                "answer": self.answer, "log": list(self.log), **kw}
