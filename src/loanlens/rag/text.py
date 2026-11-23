"""Shared tokenisation for answerability checks and extractive answers."""

import re

_WORD = re.compile(r"[a-z0-9]+")
STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "be", "of", "to", "in", "for", "and", "or", "on", "at",
    "with", "it", "its", "by", "as", "from", "this", "that", "there", "if", "not", "no",
    "what", "which", "who", "when", "where", "how", "many", "much",
    "do", "does", "did", "can", "could", "should", "must", "will", "would", "need", "get",
    "i", "me", "my", "we", "our", "you", "your", "s", "show", "tell", "give", "per",
    "applicant", "according", "want", "say", "says",
}


def tokens(text: str) -> set[str]:
    """Lowercase content words with crude plural stemming ("deposits" -> "deposit")."""
    return {w[:-1] if len(w) > 3 and w.endswith("s") else w
            for w in _WORD.findall(text.lower()) if w not in STOPWORDS}


NUMBER = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")


def numbers(text: str) -> set[float]:
    """Every number in the text as a float: '$6,664.44' -> 6664.44, '45%' -> 45.0."""
    out = set()
    for match in NUMBER.findall(text):
        try:
            out.add(round(float(match.replace(",", "")), 2))
        except ValueError:
            continue
    return out


# Lending glossary: the same thing is printed differently on different layouts and banks.
# Used for query expansion, so "closing balance" also finds "Ending Balance: 10,934.79".
SYNONYMS = [
    {"closing", "ending"},
    {"opening", "beginning"},
    {"net", "payable"},
    {"pay", "payable", "paid"},
    {"gross", "earning"},
    {"employee", "staff"},
    {"holder", "customer"},
    {"borrow", "loan"},
    {"money", "amount"},
    {"recommend", "recommendation", "recommended", "decision"},
    {"why", "reason", "because"},
    {"employer", "company", "payer", "work"},
    {"salary", "payroll", "wage", "pay"},
    {"payment", "pmt", "installment", "emi"},
    {"deduction", "withheld"},
    {"income", "salary", "earning"},
    {"dti", "debt"},
    {"statement", "bank"},
]


def expand(words: set[str]) -> set[str]:
    out = set(words)
    for group in SYNONYMS:
        if words & group:
            out |= group
    return out
