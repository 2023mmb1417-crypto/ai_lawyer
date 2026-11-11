"""Pydantic shapes for everything the model returns. If a reply does not fit, it is rejected and asked again."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Issue = Literal["deposit", "consumer_refund", "salary", "cheque_bounce", "notice_reply", "cyber_fraud", "other"]
EventType = Literal["agreement", "payment", "moved_out", "purchase", "problem", "complaint_made", "cheque_return_memo",
                    "notice_received", "last_working_day", "salary_due", "fraud_transaction", "other"]

ISSUE_NAMES = {
    "deposit": "Security deposit not returned",
    "consumer_refund": "Refund / defective product or service",
    "salary": "Unpaid salary",
    "cheque_bounce": "Cheque bounced",
    "notice_reply": "Received a legal notice",
    "cyber_fraud": "Online / UPI fraud",
    "other": "Outside what this tool covers",
}


class Event(BaseModel):
    date: str | None = Field(None, description="ISO date YYYY-MM-DD if it can be worked out from the story, else null")
    date_text: str = Field("", description="the exact words the person used for the date, copied from their message")
    type: EventType = "other"
    what: str = Field(description="one short line, in English")


class Amount(BaseModel):
    value: float = Field(description="amount in rupees as a number")
    quote: str = Field(description="the exact words from the person's message that state this amount")
    what: str = Field(description="e.g. 'security deposit', 'order value', 'unpaid salary for March'")


class CaseFile(BaseModel):
    issue: Issue
    summary: str = Field(description="2-3 sentence neutral summary of what happened, in English")
    other_side: str = Field("", description="who the person has a problem with (name/company as the person said it), or ''")
    other_side_type: Literal["landlord", "company", "employer", "individual", "bank", "government", "unknown"] = "unknown"
    timeline: list[Event] = []
    amounts: list[Amount] = []
    evidence_have: list[str] = Field([], description="proof the person says they have")
    goal: str = Field("", description="what the person wants, e.g. 'get the Rs 40,000 deposit back'")
    city_or_state: str = ""


class Option(BaseModel):
    title: str = Field(description="short name of the route, in the person's language")
    steps: str = Field(description="what to do, 1-3 plain sentences in the person's language")
    cost_time: str = Field(description="rough cost and time, plain words, in the person's language")
    law_ids: list[str] = Field(description="ids of the LAW entries this option relies on, e.g. ['CON-2']")


class Advice(BaseModel):
    where_you_stand: str = Field(description="3-5 plain sentences in the person's language: is the law on their side and why")
    options: list[Option] = Field(description="2-4 options, cheapest/fastest first")
    first_step_today: str = Field(description="one concrete thing to do today, in the person's language")
    proof_to_collect: list[str] = Field(description="2-5 items, in the person's language")
    law_ids: list[str] = Field(description="every LAW id used anywhere in this answer")


class Draft(BaseModel):
    doc_type: Literal["legal_notice", "consumer_complaint_letter", "bank_fraud_complaint", "reply_to_notice", "wage_claim_letter"]
    subject: str
    body: list[str] = Field(description="the paragraphs of the letter, in formal English. Use [YOUR NAME], [YOUR ADDRESS], "
                                        "[OTHER PARTY ADDRESS], [DATE] etc. for anything the person has not told you")
    demand_amount: float | None = Field(None, description="the amount demanded, in rupees, or null")
    reply_days: int | None = Field(None, description="days given to comply, or null")
    law_ids: list[str]


class FollowUp(BaseModel):
    questions: list[str] = Field(description="the questions, rewritten naturally in the person's language")


class JudgeScore(BaseModel):
    correct: int = Field(ge=1, le=10, description="legally correct, consistent with the LAW notes given")
    plain: int = Field(ge=1, le=10, description="an ordinary person with no legal knowledge can follow it")
    actionable: int = Field(ge=1, le=10, description="clear next steps they can actually do this week")
    safe: int = Field(ge=1, le=10, description="no false promises, no risky advice, says when to get a real lawyer")
    language_ok: bool = Field(description="written in the same language/script the person used")
    problem: str = Field(description="the single biggest weakness, one line")
