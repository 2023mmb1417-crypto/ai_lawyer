# Nyay Saathi: an AI lawyer for everyday problems in India

Kuku AI Generalist Assignment, **Problem 2: Build an AI Lawyer**.

A person describes their problem **by text or voice, in their own language** (English, Hindi, Hinglish, Marathi, Tamil,
Bengali ...). Nyay Saathi:

1. **builds the case**: what happened, when, how much, who the other side is and what proof they have (and asks for missing details);
2. **explains where they stand** and their options in plain language, cheapest first, citing only checked law notes;
3. **works out the deadlines in code** (e.g. the 30-day window to send a cheque-bounce notice) and warns when one has passed;
4. **drafts the document**: legal notice, consumer complaint, bank fraud complaint, wage demand or a reply to a notice;
5. **lets them practise** arguing with the other side (the AI plays the landlord / company / employer and then coaches them).

It covers the six problems that bring most ordinary people to a lawyer's door: **security deposit not returned, refund /
defective product or service, unpaid salary, bounced cheque, a legal notice they don't understand, and online/UPI fraud**.
Anything else (divorce, property, criminal cases) gets an honest "this needs a real lawyer" plus the free legal-aid route.
Emergencies (violence, self-harm, police custody, children) are caught by code **before** any model runs and get helplines first.

## Run it

```bash
python -m venv .venv && .venv\Scripts\activate         # Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env                                  # then paste a free key from console.groq.com

python chat.py                                          # talk to it (type, or /voice note.ogg)
python chat.py --rules-only                             # no model, works offline, free
python run.py                                           # run all 30 test conversations -> outputs/gpt-oss-120b/
python run.py --rules-only                              # same, no model (baseline)
python run.py --text "Landlord won't return my 40k deposit, I left on 1 Oct 2026"
python run.py --lawyer groq:qwen/qwen3.8-27b --out outputs/qwen   # swap the model with one string
python eval/evaluate.py outputs/rules-only outputs/gpt-oss-120b   # score runs against the expected answers
python -m pytest -q                                     # 57 unit tests for the code parts (no network)
```

Any provider LangChain's `init_chat_model` supports works as `provider:model` (`openai:gpt-4.1-mini`,
`anthropic:claude-sonnet-5-5`, or an OpenAI-compatible gateway) once its package and key are installed.

In the chat: `/draft` writes the letter, `/practice` starts role-play (type `END` for coaching), `/case` shows the case
file, `/voice <file>` takes a voice note, `/save` saves the conversation.

## How it works

```
message ─► triage (code: emergencies → helplines first)
        ─► language (code: script + Hinglish word list)
        ─► understand (LLM → Pydantic CaseFile: issue, timeline, amounts with quotes, proof)
        ─► verify facts (code: drop amounts the person never said, future dates)
        ─► missing details? (code, per issue) ─► ask once (LLM phrases the questions in their language)
        ─► retrieve law notes (RAG: issue filter + TF-IDF over kb/laws.json, 29 notes with ids)
        ─► deadlines (code, from the dates)
        ─► advise (LLM → Pydantic Advice, cites note ids only)
        ─► check (code: unknown ids, invented section numbers, promises, wrong language) ─► repair (LLM, once)
        ─► render (code adds deadlines, helplines, legal aid 15100, disclaimer)
/draft  ─► draft (LLM → Draft) ─► check (amount = case amount, reply days, no invented names/sections) ─► repair once
judge   ─► a different model (qwen3.8-27b) scores each answer 1-10: correct / plain / actionable / safe / language
```

| part | who | why |
|---|---|---|
| emergency triage, language, issue classifier, amounts, dates | code (`nyay/rules.py`) | must never fail silently; free, instant; also the offline mode |
| deadlines | code | a wrong date can lose a case; models are bad at date maths |
| case file, follow-up questions, explanation, documents | LLM | messy stories in many languages need a model |
| law | curated notes (`kb/laws.json`) + RAG | the model cites ids, never section numbers from memory |
| quality | code checks + repair + a second model as judge + 30 hand-written test cases | |
| sending anything / going to court | the person (with legal aid) | the tool prepares; a human decides and signs |

## Files

| path | what |
|---|---|
| `tests/cases.json` | **30 test conversations** with expected issue, language, flags, amounts, dates, deadlines and laws |
| `tests/test_rules.py` | 57 unit tests for the code parts |
| `outputs/<run>/answers.md` | every answer and drafted document, readable |
| `outputs/<run>/results.json` | everything, incl. case files, check logs, judge scores |
| `outputs/eval_results.json` | scores of each run against `tests/cases.json` |
| `outputs/demo/` | a full chat transcript: voice note → advice → notice → practice round |
| `docs/Solution_Doc.pdf` | the 2-page write-up |

## Limits

Not a lawyer and not legal advice; it says so in every answer. Law notes were written from public sources (India Code,
RBI, Consumer Affairs, NALSA) and checked by me, not by a lawyer. State rent laws differ and are covered only in
general terms. The rules-only mode answers in English only.
