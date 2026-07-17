"""
model.py — a genuine, from-scratch statistical language model.

No external ML frameworks, no network access, no canned/mocked responses:
this trains real trigram/bigram/unigram frequency tables from a text corpus
and generates text by actually sampling from those learned distributions.

It is intentionally simple (word-level n-gram model with stupid backoff)
so that it has zero dependencies beyond the Python standard library and can
be trained and run entirely offline in seconds. Swap in a real transformer
checkpoint later (see README) without changing the server's API shape.
"""

import random
import re
from collections import defaultdict, Counter
from typing import List, Optional


TOKEN_RE = re.compile(r"[A-Za-z']+|[.,!?;]")


def tokenize(text: str) -> List[str]:
    return TOKEN_RE.findall(text.lower())


class NGramModel:
    """A trigram language model with stupid backoff to bigram/unigram."""

    def __init__(self):
        self.trigram_counts = defaultdict(Counter)   # (w1, w2) -> Counter(w3)
        self.bigram_counts = defaultdict(Counter)     # (w1,) -> Counter(w2)
        self.unigram_counts = Counter()                # w -> count
        self.vocab: List[str] = []
        self.trained = False
        self.training_tokens = 0

    def train(self, text: str) -> None:
        tokens = tokenize(text)
        if len(tokens) < 3:
            raise ValueError("Training corpus is too small to build a trigram model")

        self.training_tokens = len(tokens)

        for i in range(len(tokens) - 2):
            w1, w2, w3 = tokens[i], tokens[i + 1], tokens[i + 2]
            self.trigram_counts[(w1, w2)][w3] += 1
            self.bigram_counts[(w1,)][w2] += 1
            self.unigram_counts[w1] += 1
        # count the last two unigrams too
        self.unigram_counts[tokens[-2]] += 1
        self.unigram_counts[tokens[-1]] += 1

        self.vocab = list(self.unigram_counts.keys())
        self.trained = True

    # -- sampling -----------------------------------------------------

    def _weighted_choice(self, counter: Counter, temperature: float, top_p: float) -> str:
        items = list(counter.items())
        words = [w for w, _ in items]
        counts = [c for _, c in items]

        # temperature-scaled softmax over raw counts
        if temperature <= 0:
            # greedy: pick the most frequent continuation
            return max(items, key=lambda kv: kv[1])[0]

        scaled = [c ** (1.0 / max(temperature, 1e-6)) for c in counts]
        total = sum(scaled)
        probs = [s / total for s in scaled]

        # top-p (nucleus) filtering
        ranked = sorted(zip(words, probs), key=lambda wp: wp[1], reverse=True)
        cumulative = 0.0
        kept = []
        for w, p in ranked:
            if cumulative >= top_p and kept:
                break
            kept.append((w, p))
            cumulative += p

        kept_words = [w for w, _ in kept]
        kept_probs = [p for _, p in kept]
        norm = sum(kept_probs)
        kept_probs = [p / norm for p in kept_probs]

        return random.choices(kept_words, weights=kept_probs, k=1)[0]

    def next_word(self, w1: Optional[str], w2: Optional[str], temperature: float, top_p: float) -> str:
        # try trigram
        if w1 is not None and w2 is not None:
            key = (w1, w2)
            if key in self.trigram_counts and self.trigram_counts[key]:
                return self._weighted_choice(self.trigram_counts[key], temperature, top_p)
        # backoff to bigram
        if w2 is not None:
            key = (w2,)
            if key in self.bigram_counts and self.bigram_counts[key]:
                return self._weighted_choice(self.bigram_counts[key], temperature, top_p)
        # backoff to unigram
        return self._weighted_choice(self.unigram_counts, temperature, top_p)

    def generate(
        self,
        prompt: str,
        max_new_tokens: int = 60,
        temperature: float = 0.8,
        top_p: float = 0.95,
        stop: Optional[List[str]] = None,
    ) -> str:
        if not self.trained:
            raise RuntimeError("Model has not been trained yet")

        prompt_tokens = tokenize(prompt)
        if not prompt_tokens:
            # start from a random point in the training distribution
            prompt_tokens = [random.choice(self.vocab)]

        generated: List[str] = []
        w1 = prompt_tokens[-2] if len(prompt_tokens) >= 2 else None
        w2 = prompt_tokens[-1]

        for _ in range(max_new_tokens):
            nxt = self.next_word(w1, w2, temperature, top_p)
            generated.append(nxt)
            w1, w2 = w2, nxt

            joined = detokenize(generated)
            if stop and any(s in joined for s in stop):
                break

        text = detokenize(generated)
        if stop:
            for s in stop:
                idx = text.find(s)
                if idx != -1:
                    text = text[:idx]
        return text


def detokenize(tokens: List[str]) -> str:
    out = ""
    for tok in tokens:
        if tok in {".", ",", "!", "?", ";"}:
            out = out.rstrip() + tok + " "
        else:
            out += tok + " "
    return out.strip()
