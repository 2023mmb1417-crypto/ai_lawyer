"""Run the AI lawyer on a set of test conversations and save everything it said.

  python run.py                                    # tests/cases.json on Groq (key in .env)
  python run.py --rules-only                       # no model at all, free, < 1 s
  python run.py --cases tests/cases.json --only CHQ-EN-1,DEP-HI-1
  python run.py --lawyer groq:qwen/qwen3.8-27b --out outputs/qwen
  python run.py --text "My landlord won't return my 50,000 deposit"   # one message, printed
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from nyay import llm as llm_mod
from nyay import render
from nyay.agent import Session
from nyay.llm import LLM, enable_cache, load_env

ROOT = Path(__file__).resolve().parent


def run_case(c: dict, make, today: date, with_draft: bool = True) -> dict:
    s: Session = make(today)
    t0 = time.time()
    turns = []
    try:
        r = s.send(c["message"])
        turns.append({"user": c["message"], "bot": r["answer"], "kind": r["kind"]})
        asked = r["kind"] == "followup"
        if asked:
            reply = c.get("followup") or "I don't know the other details."
            r = s.send(reply)
            turns.append({"user": reply, "bot": r["answer"], "kind": r["kind"]})
        d = s.draft() if with_draft and s.case and s.case.issue in render.DOC_FOR_ISSUE and not s.flags else None
        g = s.grade()
        err = None
    except Exception as e:  # keep going; the failure is part of the results
        r, d, g, asked, err = {}, None, None, False, f"{type(e).__name__}: {e}"
    return {"id": c["id"], "lang_expected": c["lang"], "turns": turns, "asked_followup": asked,
            "result": r, "draft": d, "judge": g, "error": err, "seconds": round(time.time() - t0, 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default="tests/cases.json")
    ap.add_argument("--only")
    ap.add_argument("--text")
    ap.add_argument("--lawyer", default="groq:openai/gpt-oss-120b")
    ap.add_argument("--fallback", default="groq:openai/gpt-oss-20b")
    ap.add_argument("--judge", default="groq:qwen/qwen3.8-27b")
    ap.add_argument("--no-judge", action="store_true")
    ap.add_argument("--rules-only", action="store_true")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--out")
    args = ap.parse_args()
    load_env()
    enable_cache()
    sys.stdout.reconfigure(encoding="utf-8")

    if args.rules_only:
        lawyer = judge = None
        name = "rules-only"
    else:
        lawyer = LLM(args.lawyer, fallback=args.fallback, max_tokens=2500, expected_out=900)
        judge = None if args.no_judge else LLM(args.judge, max_tokens=1200, otpm=1000, expected_out=250, temperature=0)
        name = args.lawyer.split("/")[-1].split(":")[-1]

    def make(today):
        return Session(lawyer=lawyer, judge=judge, today=today)

    if args.text:
        s = make(date.today())
        print(s.send(args.text)["answer"])
        return

    spec = json.loads((ROOT / args.cases).read_text(encoding="utf-8"))
    today = date.fromisoformat(spec["today"])
    cases = spec["cases"]
    if args.only:
        keep = set(args.only.split(","))
        cases = [c for c in cases if c["id"] in keep]
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=1 if args.rules_only else args.workers) as ex:
        results = list(ex.map(lambda c: run_case(c, make, today), cases))
        for r in results:
            print(f"{r['id']:10s} {r['result'].get('issue', 'ERROR')!s:16s} {r['result'].get('lang', '')!s:9s} "
                  f"{'followup ' if r['asked_followup'] else ''}{r['error'] or ''}")

    out = ROOT / (args.out or f"outputs/{name}")
    out.mkdir(parents=True, exist_ok=True)
    meta = {"lawyer": None if args.rules_only else args.lawyer, "judge": None if (args.rules_only or args.no_judge) else args.judge,
            "cases": len(results), "today": spec["today"], "runtime_s": round(time.time() - t0, 1), "usage": llm_mod.USAGE}
    (out / "results.json").write_text(json.dumps({"meta": meta, "results": results}, indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "run_meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    md = [f"# Answers ({name})\n"]
    for r in results:
        md.append(f"\n---\n## {r['id']}\n")
        for t in r["turns"]:
            md.append(f"**Person:** {t['user']}\n\n```\n{t['bot']}\n```\n")
        if r["draft"]:
            md.append(f"**Drafted document** (checks: {'pass' if r['draft']['ok'] else r['draft']['errors']}):\n\n```\n{r['draft']['text']}\n```\n")
        if r["judge"]:
            md.append(f"**Judge ({r['judge']['judge']}):** correct {r['judge']['correct']}, plain {r['judge']['plain']}, "
                      f"actionable {r['judge']['actionable']}, safe {r['judge']['safe']}, language ok {r['judge']['language_ok']}. "
                      f"Weakest point: {r['judge']['problem']}\n")
        if r["result"].get("log"):
            md.append("**Check log:** " + " · ".join(r["result"]["log"]) + "\n")
        if r["error"]:
            md.append(f"**ERROR:** {r['error']}\n")
    (out / "answers.md").write_text("\n".join(md), encoding="utf-8")
    print("saved", out, f"in {meta['runtime_s']} s")


if __name__ == "__main__":
    main()
