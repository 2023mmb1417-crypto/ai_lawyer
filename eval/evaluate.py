"""Score runs against the hand-written expectations in tests/cases.json.

  python eval/evaluate.py outputs/rules-only outputs/gpt-oss-120b
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from nyay import rules, validate  # noqa: E402

DATE_TYPES = {"purchase": {"purchase", "problem"}, "problem": {"purchase", "problem"}}


def score(run_dir: Path, cases: list[dict]) -> dict:
    res = {r["id"]: r for r in json.loads((run_dir / "results.json").read_text(encoding="utf-8"))["results"]}
    tally: dict[str, list[int]] = {}
    fails: dict[str, list[str]] = {}

    def mark(metric, ok, cid, detail=""):
        tally.setdefault(metric, [0, 0])
        tally[metric][0] += bool(ok)
        tally[metric][1] += 1
        if not ok:
            fails.setdefault(metric, []).append(cid + (f" ({detail})" if detail else ""))

    judge = []
    for c in cases:
        e, r = c["expect"], res.get(c["id"])
        if r is None:
            continue
        out = r["result"] or {}
        if r["error"]:
            mark("ran without error", False, c["id"], r["error"][:80])
            continue
        mark("ran without error", True, c["id"])
        case = out.get("case") or {}
        mark("issue correct", out.get("issue") == e["issue"], c["id"], f"got {out.get('issue')}")
        mark("language detected", out.get("lang") == c["lang"], c["id"], f"got {out.get('lang')}")
        mark("safety flags correct", sorted(out.get("flags", [])) == sorted(e["flags"]), c["id"], f"got {out.get('flags')}")
        if e["flags"]:
            mark("helpline shown first", out["answer"].lstrip().startswith("!!"), c["id"])
        if "amount" in e:
            vals = [a["value"] for a in case.get("amounts", [])]
            mark("amount found", any(abs(v - e["amount"]) < 1 for v in vals), c["id"], f"got {vals}")
        for typ, iso in e.get("dates", {}).items():
            want = date.fromisoformat(iso)
            types = DATE_TYPES.get(typ, {typ})
            got = [ev["date"] for ev in case.get("timeline", []) if ev["type"] in types and ev.get("date")]
            tol = 3 if any(w in c["message"] + c.get("followup", "") for w in ("months", "pehle", "पहले", "ago")) else 0
            ok = any(abs((date.fromisoformat(g) - want).days) <= tol for g in got)
            mark("key date found", ok, c["id"], f"{typ}: got {got}")
        for law_id, iso in e.get("deadlines", {}).items():
            got = [d["by"] for d in out.get("deadlines", []) if d["law_id"] == law_id]
            mark("deadline correct", iso in got, c["id"], f"{law_id}: want {iso}, got {got}")
        cited = set(out.get("law_ids", []))
        for law_id in e["must_cite"]:
            mark("must-cite law used", law_id in cited, c["id"], law_id)
        mark("no unknown law cited", all(i in validate.kb.laws() for i in cited), c["id"])
        if e.get("followup") is not None:
            mark("asked follow-up when needed", r["asked_followup"] == e["followup"], c["id"], f"asked={r['asked_followup']}")
        final = out.get("answer", "")
        mark("no promises / risky wording", not any(b in final.lower() for b in validate.BANNED), c["id"])
        if run_dir.name != "rules-only":
            body = final.split("\n", 2)[-1] if final.startswith("!!") else final
            mark("answer in person's language", rules.script_matches(body, c["lang"]), c["id"])
            mark("passed checks first time", not any("check failed" in x for x in out.get("log", [])), c["id"])
        if r.get("draft"):
            mark("document passes checks", r["draft"]["ok"], c["id"], "; ".join(r["draft"]["errors"])[:120])
        if r.get("judge"):
            judge.append(r["judge"])
    summary = {k: {"pass": a, "of": b, "rate": round(a / b, 2)} for k, (a, b) in tally.items()}
    if judge:
        summary["judge (1-10)"] = {k: round(sum(j[k] for j in judge) / len(judge), 1) for k in ("correct", "plain", "actionable", "safe")}
        summary["judge (1-10)"]["language_ok"] = round(sum(j["language_ok"] for j in judge) / len(judge), 2)
        summary["judge (1-10)"]["n"] = len(judge)
        summary["judge lowest"] = sorted(({"id": c, **j} for c, j in zip([c["id"] for c in cases if res.get(c["id"], {}).get("judge")], judge)),
                                         key=lambda j: j["correct"] + j["safe"])[:5]
    return {"run": run_dir.name, "summary": summary, "failures": fails}


def main():
    cases = json.loads((ROOT / "tests" / "cases.json").read_text(encoding="utf-8"))["cases"]
    runs = [score(ROOT / d, cases) for d in (sys.argv[1:] or ["outputs/rules-only"])]
    sys.stdout.reconfigure(encoding="utf-8")
    for r in runs:
        print(f"\n=== {r['run']}")
        for k, v in r["summary"].items():
            if k != "judge lowest":
                print(f"  {k:32s} {v}")
        for k, v in r["failures"].items():
            print(f"  FAIL {k}: {', '.join(v)}")
    (ROOT / "outputs" / "eval_results.json").write_text(json.dumps(runs, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
