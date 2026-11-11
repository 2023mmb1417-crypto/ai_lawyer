"""Everything that is plain code, no model: language detection, safety triage, issue classifier,
amount/date extraction and deadline maths. It runs in < 10 ms and is also the free 'rules-only' mode."""
from __future__ import annotations

import re
from datetime import date, timedelta

# ---------------------------------------------------------------- language
SCRIPTS = {  # unicode block -> language code
    "hi": (0x0900, 0x097F), "bn": (0x0980, 0x09FF), "pa": (0x0A00, 0x0A7F), "gu": (0x0A80, 0x0AFF),
    "or": (0x0B00, 0x0B7F), "ta": (0x0B80, 0x0BFF), "te": (0x0C00, 0x0C7F), "kn": (0x0C80, 0x0CFF),
    "ml": (0x0D00, 0x0D7F),
}
LANG_NAMES = {"en": "English", "hinglish": "Hinglish (Hindi written in English letters)", "hi": "Hindi", "bn": "Bengali",
              "pa": "Punjabi", "gu": "Gujarati", "or": "Odia", "ta": "Tamil", "te": "Telugu", "kn": "Kannada",
              "ml": "Malayalam", "mr": "Marathi"}
HINGLISH = set("""hai hain nahi nahin nhi kya kab kaise kaisa mera meri mere mujhe maine humne hum aap apna apni
kar karo kiya kiye diya diye liya raha rahi rahe tha thi the ho gaya gayi paisa paise wapas vapas bola boli
bhi aur lekin par se ko ka ki ke ne abhi kuch sab koi please bhai ji wala wali mahine mahina saal din
rupaye rupay salary nhi hoga hogi milega mila mili dena dene""".split())
MARATHI_HINTS = ("आहे", "माझे", "माझा", "माझी", "नाही", "केले", "दिले", "परत")


def detect_language(text: str) -> str:
    counts = {k: 0 for k in SCRIPTS}
    latin = 0
    for ch in text:
        o = ord(ch)
        if ch.isascii() and ch.isalpha():
            latin += 1
            continue
        for k, (a, b) in SCRIPTS.items():
            if a <= o <= b:
                counts[k] += 1
                break
    best = max(counts, key=counts.get)
    if counts[best] > latin * 0.5 and counts[best] > 3:
        if best == "hi" and sum(text.count(w) for w in MARATHI_HINTS) >= 2:
            return "mr"
        return best
    words = re.findall(r"[a-z]+", text.lower())
    if words and sum(w in HINGLISH for w in words) / len(words) > 0.18:
        return "hinglish"
    return "en"


def script_matches(reply: str, lang: str) -> bool:
    """Is the reply written in the script the person used? (Hinglish/English replies must be Latin script.)"""
    letters = [c for c in reply if c.isalpha()]
    if not letters:
        return False
    if lang in ("en", "hinglish"):
        return sum(c.isascii() for c in letters) / len(letters) > 0.9
    code = "hi" if lang == "mr" else lang
    a, b = SCRIPTS[code]
    return sum(a <= ord(c) <= b for c in letters) / len(letters) > 0.5


# ---------------------------------------------------------------- safety triage (runs before any model)
EMERGENCY = {
    "violence": ["beat me", "beats me", "hit me", "hits me", "slapped me", "threatening to kill", "threatened to kill",
                 "kill me", "attacked", "maarta", "maarte", "maar dalega", "maarpeet", "मारता", "मारते", "मार डालेगा",
                 "जान से मार", "पीटता", "jaan se maar", "acid"],
    "self_harm": ["suicide", "kill myself", "end my life", "want to die", "khudkushi", "aatmahatya", "आत्महत्या",
                  "मर जाना चाहता", "मर जाना चाहती", "marna chahta", "marna chahti", "jeena nahi"],
    "custody": ["arrested", "in police custody", "police took my", "police ne pakad", "giraftar", "गिरफ्तार",
                "police uthake", "detained"],
    "child": ["child abuse", "touching my child", "minor girl", "बच्चे के साथ गलत", "child marriage", "bal vivah"],
}
HELPLINES = {"violence": "112 (police) and 181 (women's helpline)", "self_harm": "Tele-MANAS 14416 or 112",
             "custody": "NALSA legal aid 15100: a person in custody has the right to a free lawyer",
             "child": "Childline 1098 and 112"}


def triage(text: str) -> list[str]:
    t = text.lower()
    return [k for k, words in EMERGENCY.items() if any(w in t for w in words)]


# ---------------------------------------------------------------- issue classifier
KEYWORDS = {
    "deposit": ["security deposit", "deposit", "landlord", "makaan malik", "makan malik", "मकान मालिक", "किराया",
                "kiraya", "rent agreement", "flat", "pg owner", "advance rent", "जमा राशि", "सिक्योरिटी", "vacate",
                "vacated", "moved out", "khali kiya", "खाली किया", "tenant", "किरायेदार", "owner is not returning"],
    "consumer_refund": ["refund", "order", "amazon", "flipkart", "myntra", "meesho", "swiggy", "zomato", "delivered",
                        "defective", "damaged", "warranty", "replacement", "customer care", "रिफंड", "ऑर्डर", "airline",
                        "flight cancelled", "flight", "booking", "insurance claim", "service center", "product", "ola",
                        "seller", "e-commerce", "wapas nahi kiya paisa", "course fee", "coaching", "कोचिंग", "फीस",
                        "ऑनलाइन", "परतावा", "मागवला", "ऑर्डर", "ஆர்டர்", "ஆன்லைன்", "பணத்தை", "অর্ডার"],
    "salary": ["salary", "wages", "wage", "payslip", "employer", "company owes", "tankhwah", "tankha", "तनख्वाह",
               "वेतन", "सैलरी", "full and final", "f&f", "resigned", "fired", "terminated", "notice period", "hr ",
               "naukri", "नौकरी", "मजदूरी", "majdoori", "boss", "last working day"],
    "cheque_bounce": ["cheque", "check bounce", "cheque bounce", "bounced", "चेक", "insufficient funds",
                      "return memo", "funds insufficient", "dishonour", "dishonored"],
    "notice_reply": ["legal notice", "received a notice", "got a notice", "notice from", "नोटिस", "notice aaya",
                     "notice mila", "summons", "advocate sent", "lawyer sent", "court se", "समन", "case number",
                     "hearing date", "filed a suit", "filed a case against me", "from the court", "civil court"],
    "cyber_fraud": ["fraud", "scam", "otp", "upi", "phonepe", "gpay", "google pay", "paytm", "hacked", "fake call",
                    "kyc", "link pe click", "clicked a link", "धोखा", "ठगी", "thagi", "cyber", "unknown number",
                    "money was debited", "debited without", "customs officer", "digital arrest", "लिंक", "पैसे कट", "कट गए",
                    "खाते से", "otp diya", "account se paise", "fake app", "investment app", "task job"],
}
WEIGHTS = {"cheque": 3, "cheque bounce": 4, "legal notice": 4, "security deposit": 4, "otp": 3, "fraud": 3,
           "scam": 3, "salary": 3, "refund": 3, "landlord": 3, "मकान मालिक": 3, "चेक": 3, "नोटिस": 3,
           "digital arrest": 4, "ठगी": 3, "सैलरी": 3, "वेतन": 3, "तनख्वाह": 3, "summons": 4}


def classify(text: str) -> tuple[str, dict[str, int]]:
    t = " " + text.lower() + " "
    scores = {k: sum(WEIGHTS.get(w, 1) for w in ws if w in t) for k, ws in KEYWORDS.items()}
    # a legal notice ABOUT a cheque/deposit is still a notice to reply to, if the person RECEIVED it
    if scores["notice_reply"] and re.search(r"(received|got|mila|aaya|आया|मिला|sent me|bheja)", t):
        scores["notice_reply"] += 3
    best = max(scores, key=scores.get)
    return (best if scores[best] >= 2 else "other"), scores


# ---------------------------------------------------------------- amounts
_NUM = r"(\d[\d,]*(?:\.\d+)?)"
_AMT_PATTERNS = [
    (re.compile(r"(?:rs\.?|inr|₹|rupees?)\s*" + _NUM + r"\s*(lakh|lac|lakhs|k|thousand|हजार|लाख|hazaar|hazar|crore)?", re.I), 1),
    (re.compile(_NUM + r"\s*(lakh|lac|lakhs|k|thousand|हजार|लाख|hazaar|hazar|crore)?\s*(?:rs\.?|rupees?|rupaye|rupay|रुपय\w*|रुपए|₹|/-|ரூபாய்\w*|টাকা)", re.I), 1),
    (re.compile(_NUM + r"\s*(lakh|lac|lakhs|हजार|लाख|hazaar|hazar|crore)\b", re.I), 1),
    (re.compile(r"\b" + _NUM + r"(k)\b", re.I), 1),
]
_MULT = {"lakh": 1e5, "lac": 1e5, "lakhs": 1e5, "लाख": 1e5, "k": 1e3, "thousand": 1e3, "हजार": 1e3, "hazaar": 1e3,
         "hazar": 1e3, "crore": 1e7}


def extract_amounts(text: str) -> list[float]:
    text = normalize_digits(text)
    found: list[tuple[int, float]] = []
    taken: list[tuple[int, int]] = []
    for pat, _ in _AMT_PATTERNS:
        for m in pat.finditer(text):
            if any(a <= m.start() < b for a, b in taken):
                continue
            num = float(m.group(1).replace(",", ""))
            unit = (m.group(2) or "").lower() if m.lastindex and m.lastindex >= 2 else ""
            val = num * _MULT.get(unit, 1)
            if val >= 100:          # ignore '2 months', '3 days' that slipped through
                found.append((m.start(), val))
                taken.append((m.start(), m.end()))
    return [v for _, v in sorted(found)]


_DIGITS = {ord(c): str(i % 10) for start in (0x0966, 0x09E6, 0x0A66, 0x0AE6, 0x0B66, 0x0BE6, 0x0C66, 0x0CE6, 0x0D66)
           for i, c in enumerate(chr(start + k) for k in range(10))}


def normalize_digits(text: str) -> str:
    """१२३ / ১২৩ / ௧௨௩ -> 123"""
    return text.translate(_DIGITS)


def numbers_in_text(text: str) -> list[float]:
    """Every number the person wrote (with lakh/k multipliers), with or without a currency word.
    Used to verify the model's amounts: '18000 per month' counts even without 'Rs'."""
    text = normalize_digits(text)
    vals = extract_amounts(text)
    for m in re.finditer(r"(?<![\d.])(\d[\d,]*(?:\.\d+)?)(?![\d])", text):
        try:
            vals.append(float(m.group(1).replace(",", "")))
        except ValueError:
            pass
    return [v for v in vals if v >= 100]


def amount_in_text(value: float, text: str) -> bool:
    return any(abs(v - value) < 1 for v in numbers_in_text(text))


# ---------------------------------------------------------------- dates
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
MONTHS.update({"जनवरी": 1, "फरवरी": 2, "मार्च": 3, "अप्रैल": 4, "मई": 5, "जून": 6, "जुलाई": 7, "अगस्त": 8,
               "सितंबर": 9, "अक्टूबर": 10, "नवंबर": 11, "दिसंबर": 12})


def extract_dates(text: str, today: date) -> list[date]:
    text = normalize_digits(text)
    out: list[tuple[int, date]] = []
    for m in re.finditer(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})\b", text):          # 15/03/2026 (Indian d/m/y)
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        y += 2000 if y < 100 else 0
        try:
            out.append((m.start(), date(y, mo, d)))
        except ValueError:
            pass
    month_re = "|".join(sorted(MONTHS, key=len, reverse=True))
    for m in re.finditer(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({month_re})[a-z]*,?\s*(\d{{4}})?", text, re.I):
        d, mo = int(m.group(1)), MONTHS[m.group(2).lower()[:3] if m.group(2).isascii() else m.group(2)]
        y = int(m.group(3)) if m.group(3) else today.year
        try:
            dt = date(y, mo, d)
            if not m.group(3) and dt > today:
                dt = date(y - 1, mo, d)
            out.append((m.start(), dt))
        except ValueError:
            pass
    for m in re.finditer(r"\b(\d{1,2}|a|one|two|three|four|five|six|ek|do|teen|char)\s+(day|week|month|year|din|hafte|mahine|saal)s?\s+(ago|back|pehle|pahle)",
                         text, re.I):
        n = {"a": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "ek": 1, "do": 2, "teen": 3,
             "char": 4}.get(m.group(1).lower())
        n = n or int(m.group(1))
        unit = {"din": "day", "hafte": "week", "mahine": "month", "saal": "year"}.get(m.group(2).lower(), m.group(2).lower())
        days = {"day": 1, "week": 7, "month": 30, "year": 365}[unit] * n
        out.append((m.start(), today - timedelta(days=days)))
    for m in re.finditer(r"(\d{1,2})\s*(दिन|हफ्ते|महीने|साल)\s*(पहले)", text):
        days = {"दिन": 1, "हफ्ते": 7, "महीने": 30, "साल": 365}[m.group(2)] * int(m.group(1))
        out.append((m.start(), today - timedelta(days=days)))
    if re.search(r"\b(yesterday|kal raat|कल)\b", text, re.I):
        out.append((10 ** 6, today - timedelta(days=1)))
    if re.search(r"\b(today|aaj|आज)\b", text, re.I):
        out.append((10 ** 6 + 1, today))
    return [d for _, d in sorted(out)]


# ---------------------------------------------------------------- deadlines (always code, never the model)
def add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    y, m = d.year + y, m + 1
    for day in (d.day, 30, 29, 28):
        try:
            return date(y, m, day)
        except ValueError:
            continue
    raise ValueError(d)


def working_days_after(d: date, n: int) -> date:
    while n:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def deadlines(issue: str, events: list[dict], today: date) -> list[dict]:
    """events: [{'type': ..., 'date': date}] -> [{'what', 'by', 'days_left', 'rule', 'law_id'}]"""
    ev = {}
    for e in events:
        if e.get("date"):
            ev.setdefault(e["type"], e["date"])
    out = []

    def add(what, by, rule, law_id):
        out.append({"what": what, "by": by.isoformat(), "days_left": (by - today).days, "rule": rule, "law_id": law_id})

    if issue == "cheque_bounce" and "cheque_return_memo" in ev:
        memo = ev["cheque_return_memo"]
        add("Send the demand notice to the person who gave the cheque", memo + timedelta(days=30),
            "30 days from the bank's return memo", "CHQ-2")
        add("If unpaid, file the complaint in court (latest possible date, if the notice is delivered on the 30th day)",
            add_months(memo + timedelta(days=30 + 15), 1), "15 days to pay after notice, then 1 month", "CHQ-3")
    if issue == "consumer_refund":
        start = ev.get("problem") or ev.get("purchase")
        if start:
            add("File a consumer complaint", add_months(start, 24), "2 years from the problem", "CON-3")
    if issue == "deposit" and "moved_out" in ev:
        add("File a civil suit for the deposit (if notice fails)", add_months(ev["moved_out"], 36),
            "3 years for money claims", "DEP-4")
    if issue == "salary":
        start = ev.get("last_working_day") or ev.get("salary_due")
        if start:
            if "last_working_day" in ev:
                add("Date by which the employer had to pay all dues", working_days_after(ev["last_working_day"], 2),
                    "2 working days after leaving", "SAL-1")
            add("File a wage claim with the Labour Department", add_months(start, 36), "3 years", "SAL-2")
    if issue == "cyber_fraud" and "fraud_transaction" in ev:
        add("Inform your bank in writing for zero liability", working_days_after(ev["fraud_transaction"], 3),
            "3 working days from the fraud", "CYB-2")
    if issue == "notice_reply" and "notice_received" in ev:
        add("Reply to the notice (most notices give 15 days; check yours)", ev["notice_received"] + timedelta(days=15),
            "15 days is the usual period stated in a notice", "NOT-3")
    return out


# ---------------------------------------------------------------- what we must know before advising
REQUIRED = {  # issue -> [(field, question)]
    "deposit": [("amount", "How much was the security deposit?"),
                ("moved_out", "When did you move out and hand back the keys?")],
    "consumer_refund": [("amount", "How much did you pay?"),
                        ("other_side", "Which company or seller is it (for example the app or shop name)?")],
    "salary": [("amount", "How much salary is unpaid (and for which months)?"),
               ("other_side", "What is the name of the employer/company?")],
    "cheque_bounce": [("amount", "What is the amount on the cheque?"),
                      ("cheque_return_memo", "On what date did your bank give you the 'cheque returned' memo or message?")],
    "notice_reply": [("other_side", "Who sent the notice (name of the person/company or their lawyer)?"),
                     ("notice_received", "On what date did you receive the notice?")],
    "cyber_fraud": [("amount", "How much money was taken?"),
                    ("fraud_transaction", "When exactly did the money go out of your account (date and time)?")],
}
HINDI_Q = {
    "How much was the security deposit?": "सिक्योरिटी डिपॉजिट कितना था?",
    "When did you move out and hand back the keys?": "आपने घर कब खाली किया और चाबी कब लौटाई?",
    "How much did you pay?": "आपने कितने पैसे दिए थे?",
    "Which company or seller is it (for example the app or shop name)?": "कौन सी कंपनी या विक्रेता है (ऐप या दुकान का नाम)?",
    "How much salary is unpaid (and for which months)?": "कितनी सैलरी बाकी है, और किन महीनों की?",
    "What is the name of the employer/company?": "कंपनी या मालिक का नाम क्या है?",
    "What is the amount on the cheque?": "चेक कितने रुपये का है?",
    "On what date did your bank give you the 'cheque returned' memo or message?": "बैंक ने चेक लौटने का मेमो या मैसेज किस तारीख को दिया?",
    "Who sent the notice (name of the person/company or their lawyer)?": "नोटिस किसने भेजा है (व्यक्ति/कंपनी या उनका वकील)?",
    "On what date did you receive the notice?": "आपको नोटिस किस तारीख को मिला?",
    "How much money was taken?": "कितने पैसे कटे?",
    "When exactly did the money go out of your account (date and time)?": "पैसे खाते से ठीक कब कटे (तारीख और समय)?",
}


def missing_fields(issue: str, have_amount: bool, other_side: str, event_types: set[str]) -> list[tuple[str, str]]:
    miss = []
    for field, q in REQUIRED.get(issue, []):
        ok = {"amount": have_amount, "other_side": bool(other_side.strip())}.get(field, field in event_types)
        if not ok:
            miss.append((field, q))
    return miss
