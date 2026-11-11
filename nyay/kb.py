"""The law notes (kb/laws.json) and retrieval over them.

The model never writes a section number from memory: it gets the notes retrieved here, each with an id
(CON-2, CHQ-2 ...), and may only cite those ids. Code checks every id and prints the law text itself.
Retrieval = issue filter (from the classifier / case file) + TF-IDF ranking on the English case summary.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

ROOT = Path(__file__).resolve().parent.parent
KB_PATH = ROOT / "kb" / "laws.json"


@lru_cache(maxsize=1)
def laws() -> dict[str, dict]:
    return {e["id"]: e for e in json.loads(KB_PATH.read_text(encoding="utf-8"))}


@lru_cache(maxsize=1)
def _index():
    ids = list(laws())
    docs = [f"{laws()[i]['title']} {laws()[i]['law']} {laws()[i]['plain']}" for i in ids]
    vec = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, stop_words="english").fit(docs)
    return ids, vec, vec.transform(docs)


def retrieve(issue: str, query: str, k: int = 8) -> list[dict]:
    """All notes tagged with the issue, ranked by similarity to the query; the generic notes come last."""
    ids, vec, mat = _index()
    sims = cosine_similarity(vec.transform([query or issue]), mat)[0]
    ranked = sorted(range(len(ids)), key=lambda i: -sims[i])
    tagged = [ids[i] for i in ranked if issue in laws()[ids[i]]["issues"] and not ids[i].startswith("GEN")]
    generic = [ids[i] for i in ranked if issue in laws()[ids[i]]["issues"] and ids[i].startswith("GEN")]
    return [laws()[i] for i in (tagged + generic)[:k]]


def render(entries: list[dict]) -> str:
    return "\n".join(f"[{e['id']}] {e['title']} ({e['law']}): {e['plain']}" for e in entries)
