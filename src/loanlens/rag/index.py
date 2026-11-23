"""Offline retrieval index: TF-IDF word + character n-grams, cosine scoring, metadata filters.

Scores are cosine similarities in [0, 1] where HIGHER IS BETTER, so the min_score cut-off
keeps working if this is swapped for dense embeddings + a vector database.

Character n-grams matter here: OCR output glues words together ("NetAmountPayable",
"LessDeductions"), which word tokens miss but character n-grams still match.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

import joblib
import numpy as np
from scipy.sparse import hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

from loanlens.rag.chunking import Chunk
from loanlens.rag.text import expand, tokens


class TfidfIndex:
    def __init__(self) -> None:
        # Word n-grams capture meaning; char n-grams tolerate typos, plurals and OCR glue.
        self.word_vec = TfidfVectorizer(ngram_range=(1, 2), stop_words="english", sublinear_tf=True)
        self.char_vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True)
        self.chunks: list[Chunk] = []
        self.matrix = None
        self._tokens: list[set[str]] = []

    def _transform(self, texts: list[str]):
        return normalize(hstack([self.word_vec.transform(texts),
                                 self.char_vec.transform(texts)]).tocsr())

    def build(self, chunks: list[Chunk]) -> None:
        if not chunks:
            raise ValueError("No chunks to index.")
        self.chunks = list(chunks)
        texts = [c.search_text() for c in self.chunks]
        self.word_vec.fit(texts)
        self.char_vec.fit(texts)
        self.matrix = self._transform(texts)
        self._tokens = [tokens(t) for t in texts]

    def idf(self, word: str) -> float:
        """Rarer words count for more: 'gross' says more than 'pay' about which line answers."""
        if not hasattr(self, "_df"):
            from collections import Counter
            self._df = Counter(t for toks in self._tokens for t in toks)
        n = len(self._tokens)
        return float(np.log((1 + n) / (1 + self._df.get(word, 0))) + 1)

    def search(self, query: str, k: int = 4, min_score: float = 0.0,
               where: Callable[[Chunk], bool] | None = None) -> list[tuple[Chunk, float]]:
        """Top-k chunks among those that pass the metadata filter `where`."""
        if self.matrix is None:
            return []
        # Query expansion with the lending glossary ("closing balance" -> also "ending")
        query = f"{query} {' '.join(sorted(expand(tokens(query)) - tokens(query)))}"
        scores = (self.matrix @ self._transform([query]).T).toarray().ravel()
        if where is not None:
            allowed = np.fromiter((where(c) for c in self.chunks), dtype=bool, count=len(self.chunks))
            scores = np.where(allowed, scores, -1.0)
        top = np.argsort(-scores)[:k]
        return [(self.chunks[i], float(scores[i])) for i in top if scores[i] >= max(min_score, 0)]

    def coverage(self, query: str, chunk: Chunk) -> float:
        """IDF-weighted share of the question's content words found in the chunk (0-1).

        Answers "does this passage actually talk about what was asked?". Words that appear
        in no document at all (e.g. "credit score") weigh the most, so questions about
        things the file doesn't contain score low and get "not found".
        """
        q = tokens(query)
        if not q:
            return 0.0
        n = len(self.chunks)
        doc_freq = {t: sum(t in toks for toks in self._tokens) for t in q}
        idf = {t: np.log((1 + n) / (1 + df)) + 1 for t, df in doc_freq.items()}
        found = {t for t in q if expand({t}) & tokens(chunk.search_text())}
        return float(sum(idf[t] for t in found) / sum(idf.values()))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"word": self.word_vec, "char": self.char_vec, "matrix": self.matrix,
                     "chunks": [asdict(c) for c in self.chunks]}, path)

    @classmethod
    def load(cls, path: Path) -> "TfidfIndex":
        data = joblib.load(path)
        index = cls()
        index.word_vec, index.char_vec, index.matrix = data["word"], data["char"], data["matrix"]
        index.chunks = [Chunk(**c) for c in data["chunks"]]
        index._tokens = [tokens(c.search_text()) for c in index.chunks]
        return index
