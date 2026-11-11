"""Talk to the AI lawyer in the terminal.

  python chat.py                         # Groq free tier (GROQ_API_KEY in .env)
  python chat.py --rules-only            # no model, works offline
  python chat.py --lawyer openai:gpt-4.1-mini

In the chat:
  type your problem in any language     /voice path/to/note.ogg   speak instead of typing
  /draft     write the notice / complaint letter for this case
  /practice  practise arguing: the AI plays the other side (type END to stop and get coaching)
  /case      show the case file (what happened, when, amounts, proof)
  /save      save this conversation to outputs/chats/
  /new       start a new case          /quit
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from nyay.agent import Session
from nyay.llm import LLM, enable_cache, load_env

ROOT = Path(__file__).resolve().parent


def make_session(args) -> Session:
    if args.rules_only:
        return Session()
    return Session(lawyer=LLM(args.lawyer, fallback=args.fallback, max_tokens=2500))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lawyer", default="groq:openai/gpt-oss-120b")
    ap.add_argument("--fallback", default="groq:openai/gpt-oss-20b")
    ap.add_argument("--rules-only", action="store_true")
    args = ap.parse_args()
    load_env()
    enable_cache()
    sys.stdout.reconfigure(encoding="utf-8")
    s = make_session(args)
    print("Nyay Saathi - tell me your problem in your own words (any language). /help for commands.\n")
    practising = False
    transcript = []
    while True:
        try:
            msg = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not msg:
            continue
        transcript.append(("you", msg))
        if msg == "/quit":
            break
        if msg == "/help":
            print(__doc__)
            continue
        if msg == "/new":
            s, practising = make_session(args), False
            print("New case. Tell me what happened.")
            continue
        if msg == "/case":
            print(json.dumps(s.case.model_dump() if s.case else {}, indent=1, ensure_ascii=False))
            continue
        if msg == "/save":
            out = ROOT / "outputs" / "chats" / f"chat_{int(time.time())}.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps({"transcript": transcript, "case": s.case.model_dump() if s.case else None,
                                       "log": s.log}, indent=1, ensure_ascii=False), encoding="utf-8")
            print("saved", out)
            continue
        if msg.startswith("/voice"):
            from nyay.voice import transcribe
            text, lang = transcribe(msg.split(maxsplit=1)[1].strip('"'))
            print(f"(heard, {lang}): {text}")
            msg = text
        if msg == "/draft":
            r = s.draft()
            reply = r["text"] + (f"\n(checks still failing: {r['errors']})" if r["errors"] else "")
        elif msg == "/practice":
            practising = True
            reply = "Practice mode. I am now the other side. Make your case. (type END to stop and get feedback)"
        elif practising:
            reply = s.practise(msg)
            practising = msg.strip().upper() != "END"
        else:
            reply = s.send(msg)["answer"]
            if s.advice or (s.lawyer is None and s.case):
                reply += "\n\n(/draft = write the letter for you, /practice = practise arguing with the other side)"
        transcript.append(("bot", reply))
        print("\n" + reply + "\n")


if __name__ == "__main__":
    main()
