"""Records one full conversation, the way a person would use it, to outputs/demo/demo_chat.md:
voice note -> follow-up -> advice -> drafted letter -> practice round with the other side -> coaching.

    python samples/demo_chat.py
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from nyay import llm as llm_mod  # noqa: E402
from nyay.agent import Session  # noqa: E402
from nyay.llm import LLM, enable_cache, load_env  # noqa: E402
from nyay.voice import transcribe  # noqa: E402

load_env()
enable_cache()
sys.stdout.reconfigure(encoding="utf-8")
s = Session(lawyer=LLM("groq:openai/gpt-oss-120b", fallback="groq:openai/gpt-oss-20b", max_tokens=2500),
            drafter=LLM("groq:openai/gpt-oss-20b", max_tokens=2000), today=date(2026, 11, 11))
log = []


def say(who, text):
    log.append((who, text))
    print(f"\n[{who}]\n{text}")


audio = ROOT / "samples" / "voice_complaint_en.wav"
text, lang = transcribe(str(audio))
say("Person (voice note samples/voice_complaint_en.wav, transcribed by Whisper, language: " + lang + ")", text)
r = s.send(text)
say("Nyay Saathi", r["answer"])
if r["kind"] == "followup":
    reply = "The shop is Sharma Electronics on MI Road, Jaipur. I have the bill and the warranty card."
    say("Person", reply)
    r = s.send(reply)
    say("Nyay Saathi", r["answer"])
say("Person", "/draft")
d = s.draft()
say("Nyay Saathi (drafted letter, checks: " + ("pass" if d["ok"] else "; ".join(d["errors"])) + ")", d["text"])
for msg in ["/practice",
            "I bought this washing machine from you for 22,000 rupees and it stopped working in one week. Please repair or refund it.",
            "It is under warranty and I have the bill. A machine that fails in a week is a defect under the Consumer Protection Act. "
            "If you don't fix it in 15 days I will complain on the National Consumer Helpline 1915 and file on e-Daakhil.",
            "END"]:
    say("Person", msg)
    if msg != "/practice":
        say("Nyay Saathi (playing the shop)" if msg != "END" else "Nyay Saathi (coach)", s.practise(msg))

out = ROOT / "outputs" / "demo"
out.mkdir(parents=True, exist_ok=True)
md = ["# Demo conversation (real run, unedited)\n", "Voice note -> follow-up -> advice -> letter -> practice round.\n"]
for who, t in log:
    md.append(f"\n**{who}:**\n\n```\n{t}\n```\n")
md.append(f"\nCheck log: {s.log}\n\nToken usage: {json.dumps(llm_mod.USAGE)}\n")
(out / "demo_chat.md").write_text("\n".join(md), encoding="utf-8")
print("saved", out / "demo_chat.md")
