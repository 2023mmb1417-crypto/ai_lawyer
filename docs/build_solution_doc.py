"""Builds docs/Solution_Doc.pdf (2 pages) from the run outputs, so every number in it comes from a real run.

    python docs/build_solution_doc.py outputs/gpt-oss-120b outputs/rules-only
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parent.parent
REPO = "https://github.com/2023mmb1417-crypto/ai_lawyer"
llm_dir = ROOT / (sys.argv[1] if len(sys.argv) > 1 else "outputs/gpt-oss-120b")
rules_dir = ROOT / (sys.argv[2] if len(sys.argv) > 2 else "outputs/rules-only")
run = json.loads((llm_dir / "results.json").read_text(encoding="utf-8"))
meta, results = run["meta"], run["results"]
ev = {r["run"]: r for r in json.loads((ROOT / "outputs" / "eval_results.json").read_text(encoding="utf-8"))}
E, R = ev[llm_dir.name]["summary"], ev[rules_dir.name]["summary"]
facts = json.loads((ROOT / "docs" / "facts.json").read_text(encoding="utf-8"))

ink, accent, muted = colors.HexColor("#1b2230"), colors.HexColor("#0f6b5c"), colors.HexColor("#5a6270")
H = ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=10.2, leading=12.4, textColor=accent, spaceBefore=4.5, spaceAfter=1.5)
B = ParagraphStyle("b", fontName="Helvetica", fontSize=8.2, leading=10.2, textColor=ink)
T = ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=15, leading=18, textColor=ink)
Sub = ParagraphStyle("sub", parent=B, textColor=muted)


def p(text, st=B):
    return Paragraph(text, st)


def link(url, text=None):
    return f'<link href="{url}" color="#0f6b5c"><u>{text or url.replace("https://", "")}</u></link>'


def bullets(items):
    return [Paragraph(f"&bull;&nbsp;{i}", ParagraphStyle("bl", parent=B, leftIndent=8, firstLineIndent=-6)) for i in items]


def table(rows, widths, size=7.3, head=True):
    data = [[Paragraph(str(c), ParagraphStyle("tc", parent=B, fontSize=size, leading=size + 1.7,
                                              fontName="Helvetica-Bold" if (head and i == 0) else "Helvetica"))
             for c in r] for i, r in enumerate(rows)]
    t = Table(data, colWidths=widths, repeatRows=1 if head else 0)
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, accent) if head else ("LINEBELOW", (0, 0), (-1, 0), 0, colors.white),
        ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#d5dbe0")),
        ("LEFTPADDING", (0, 0), (-1, -1), 2.5), ("RIGHTPADDING", (0, 0), (-1, -1), 2.5),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
    ]))
    return t


def rate(S, k):
    v = S.get(k)
    return f"{v['pass']}/{v['of']}" if v else "n/a"


W = 180 * mm
story = [p("Nyay Saathi: an AI lawyer for everyday problems in India", T),
         p("Kuku AI Generalist Assignment · Problem 2, Build an AI Lawyer", Sub), Spacer(1, 3),
         table([["Code + run steps", "Test cases (30)", "Raw outputs", "Unit tests (57, code parts)"],
                [link(REPO, "github.com/2023mmb1417-crypto/ai_lawyer"), link(REPO + "/blob/main/tests/cases.json", "tests/cases.json"),
                 link(REPO + "/tree/main/outputs", "outputs/ (every answer + letter)"),
                 link(REPO + "/blob/main/tests/test_rules.py", "tests/test_rules.py")]],
               [58 * mm, 30 * mm, 46 * mm, 46 * mm], size=7.6)]

story += [p("The problem, and why I picked it", H), p(facts["problem"])]
story += [p("Input and output", H),
          table([["Input", "Output"], [facts["input"], facts["output"]]], [W / 2, W / 2], size=7.6)]

story += [p("How it works, step by step", H),
          table([["Step", "Who", "What happens, in simple words"]] + facts["steps"], [36 * mm, 20 * mm, 124 * mm], size=7.4)]
story += [p("What it covers, and what it doesn't", H)] + bullets(facts["scope"])
story += [p("Assumptions", H)] + bullets(facts["assumptions"])

u = meta["usage"]
calls = sum(v["calls"] for v in u.values())
tok = sum(v["input_tokens"] + v["output_tokens"] for v in u.values())
models = ", ".join(f"{k.split('/')[-1]} {v['calls']}" for k, v in u.items())
story += [p("The AI I used, and what it costs", H),
          p(facts["ai"] + f" <b>Measured on the AI run ({meta['cases']} conversations):</b> {calls} model calls ({models}), "
                          f"{tok / 1000:.0f}K tokens, about {tok / meta['cases'] / 1000:.1f}K tokens per conversation; $0 on the free tier, "
                          f"{facts['paid_cost']}. " + facts["scale"])]

# ---------------------------------------------------------------- page 2
story += [p("One real answer (test case " + facts["example_id"] + ", verbatim, shortened)", H),
          table([[f"<b>Person:</b> {facts['example_in']}"], [facts["example_out"]]], [W], size=7.3, head=False)]

rows = [["Check (code, against the 30 hand-written test cases)", f"Rules only (no AI), {R['ran without error']['of']} cases", f"With AI (gpt-oss-120b), {meta['cases']} cases"]]
for k, label in [("issue correct", "Problem type identified"), ("language detected", "Person's language detected"),
                 ("safety flags correct", "Emergency caught (and not raised falsely)"),
                 ("amount found", "Amount found in the story"), ("key date found", "Key date found (e.g. bank memo date)"),
                 ("deadline correct", "Deadline matches the hand-worked date"),
                 ("asked follow-up when needed", "Asked for missing details only when needed"),
                 ("must-cite law used", "Cites the laws the case needs"), ("no unknown law cited", "No invented law in the final answer"),
                 ("answer in person's language", "Answer written in the person's language"),
                 ("passed checks first time", "Model answer passed all code checks first time"),
                 ("document passes checks", "Drafted letter passes all checks"),
                 ("no promises / risky wording", "No promises like 'you will surely win'")]:
    rows.append([label, rate(R, k), rate(E, k)])
story += [p("Quality checks", H), table(rows, [100 * mm, 38 * mm, 42 * mm], size=7.3)]
j = E.get("judge (1-10)")
if j:
    story += [Spacer(1, 2), p(f"<b>Second-model judge</b> (qwen3.8-27b, a different model, with a strict rubric; n={j['n']}): "
                              f"correct <b>{j['correct']}</b>, plain <b>{j['plain']}</b>, actionable <b>{j['actionable']}</b>, "
                              f"safe <b>{j['safe']}</b> out of 10; right language {j['language_ok'] * 100:.0f}%. " + facts["judge_note"])]

story += [p("Where it goes wrong", H)] + bullets(facts["failures"])
story += [p("Limitations (technical)", H),
          table([["Limitation", "What it means", "How I handle it, or what I would do next"]] + facts["limits"],
                [38 * mm, 72 * mm, 70 * mm], size=7.2)]
story += [p("Tools used, and where they got it wrong", H), p(facts["tools"])]

out = ROOT / "docs" / "Solution_Doc.pdf"
doc = SimpleDocTemplate(str(out), pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=11 * mm, bottomMargin=10 * mm,
                        title="Nyay Saathi - Solution Doc", author="2023mmb1417-crypto")
doc.build(story)
from pypdf import PdfReader  # noqa: E402

print(out, "pages:", len(PdfReader(str(out)).pages))
