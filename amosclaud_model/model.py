"""A compact, deterministic language-model bootstrap trained entirely from local folders."""

from __future__ import annotations

import json
import hashlib
import math
import random
import re
import tempfile
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from amosclaud_model.config import ModelConfig
from amosclaud_model.workspace import iter_documents

TOKEN_RE = re.compile(r"\n|[A-Za-z_][A-Za-z_0-9]*|\d+(?:\.\d+)?|[^\w\s]", re.UNICODE)


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text)


def detokenize(tokens: list[str]) -> str:
    output = ""
    for token in tokens:
        if token == "\n":
            output = output.rstrip() + "\n"
        elif not output or output.endswith(("\n", " ")) or token in ".,;:!?)]}":
            output += token
        elif output[-1] in "([{":
            output += token
        else:
            output += " " + token
    return output.strip()


class FolderLanguageModel:
    def __init__(self, root: Path):
        self.root = root
        self.config = ModelConfig.load(root)
        self.transitions: dict[tuple[str, ...], Counter[str]] = {}
        self.vocabulary: Counter[str] = Counter()

    @property
    def checkpoint_path(self) -> Path:
        return self.root / "checkpoints" / "current.json"

    def train(self) -> dict:
        transitions: dict[tuple[str, ...], Counter[str]] = defaultdict(Counter)
        vocabulary: Counter[str] = Counter()
        documents = 0
        tokens_seen = 0
        for document in iter_documents(self.root):
            tokens = ["<bos>"] * self.config.order + tokenize(document) + ["<eos>"]
            documents += 1
            tokens_seen += len(tokens) - self.config.order
            vocabulary.update(tokens[self.config.order :])
            for index in range(self.config.order, len(tokens)):
                for size in range(1, self.config.order + 1):
                    transitions[tuple(tokens[index - size : index])][tokens[index]] += 1
        if not documents:
            raise ValueError("No training documents found under datasets/raw or datasets/curated")
        payload = {
            "format": 1,
            "model": self.config.name,
            "order": self.config.order,
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "documents": documents,
            "tokens": tokens_seen,
            "vocabulary": dict(vocabulary),
            "transitions": {"\u001f".join(key): dict(value) for key, value in transitions.items()},
        }
        encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        checkpoint_id = (
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
            + "-"
            + hashlib.sha256(encoded).hexdigest()[:12]
        )
        payload["checkpoint_id"] = checkpoint_id
        encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        checksum = hashlib.sha256(encoded).hexdigest()
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        version_path = self.root / "checkpoints" / "versions" / f"{checkpoint_id}.json"
        version_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("wb", dir=version_path.parent, delete=False) as handle:
            handle.write(encoded)
            temporary = Path(handle.name)
        temporary.replace(version_path)
        self._activate(version_path)
        (self.root / "tokenizer" / "vocab.json").write_text(
            json.dumps(dict(vocabulary.most_common()), indent=2) + "\n", encoding="utf-8"
        )
        self.load()
        metrics = self.evaluate(list(iter_documents(self.root, ("eval",))))
        record = {
            **{
                key: payload[key]
                for key in ("checkpoint_id", "model", "trained_at", "documents", "tokens")
            },
            "sha256": checksum,
            "metrics": metrics,
        }
        with (self.root / "checkpoints" / "index.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
        return record

    def _activate(self, source: Path) -> None:
        with tempfile.NamedTemporaryFile(
            "wb", dir=self.checkpoint_path.parent, delete=False
        ) as handle:
            with source.open("rb") as checkpoint:
                shutil.copyfileobj(checkpoint, handle)
            temporary = Path(handle.name)
        temporary.replace(self.checkpoint_path)

    def checkpoints(self) -> list[dict]:
        index = self.root / "checkpoints" / "index.jsonl"
        if not index.exists():
            return []
        return [
            json.loads(line)
            for line in index.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def promote(self, checkpoint_id: str) -> dict:
        records = {item["checkpoint_id"]: item for item in self.checkpoints()}
        record = records.get(checkpoint_id)
        path = self.root / "checkpoints" / "versions" / f"{checkpoint_id}.json"
        if not record or not path.exists():
            raise ValueError("Checkpoint does not exist")
        if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
            raise ValueError("Checkpoint integrity verification failed")
        self._activate(path)
        self.load()
        return record

    def rollback(self) -> dict:
        current = json.loads(self.checkpoint_path.read_text(encoding="utf-8")).get("checkpoint_id")
        history = self.checkpoints()
        candidates = [record for record in history if record["checkpoint_id"] != current]
        if not candidates:
            raise ValueError("No previous checkpoint is available")
        return self.promote(candidates[-1]["checkpoint_id"])

    def load(self) -> None:
        if not self.checkpoint_path.exists():
            raise FileNotFoundError("No model checkpoint. Run `amosclaud-model train` first.")
        payload = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
        self.transitions = {
            tuple(key.split("\u001f")): Counter(values)
            for key, values in payload["transitions"].items()
        }
        self.vocabulary = Counter(payload["vocabulary"])

    def evaluate(self, documents: list[str] | None = None) -> dict | None:
        if not self.transitions:
            self.load()
        documents = (
            documents if documents is not None else list(iter_documents(self.root, ("eval",)))
        )
        if not documents:
            return None
        negative_log_likelihood = 0.0
        predicted = 0
        matched = 0
        vocabulary_size = max(len(self.vocabulary), 1)
        for document in documents:
            tokens = ["<bos>"] * self.config.order + tokenize(document) + ["<eos>"]
            for index in range(self.config.order, len(tokens)):
                context = tuple(tokens[index - self.config.order : index])
                options = self.transitions.get(context, Counter())
                count = options.get(tokens[index], 0)
                total = sum(options.values())
                negative_log_likelihood -= math.log((count + 1) / (total + vocabulary_size))
                predicted += 1
                matched += int(count > 0)
        return {
            "documents": len(documents),
            "tokens": predicted,
            "perplexity": round(math.exp(negative_log_likelihood / max(predicted, 1)), 4),
            "context_coverage": round(matched / max(predicted, 1), 4),
        }

    def _sample(self, options: Counter[str], rng: random.Random, temperature: float) -> str:
        if temperature <= 0:
            return options.most_common(1)[0][0]
        tokens, counts = zip(*options.items())
        weights = [math.pow(count, 1.0 / max(temperature, 0.05)) for count in counts]
        return rng.choices(tokens, weights=weights, k=1)[0]

    def generate(
        self, prompt: str, max_tokens: int | None = None, temperature: float | None = None
    ) -> str:
        if not self.transitions:
            self.load()
        prompt_tokens = tokenize(prompt)
        context = (["<bos>"] * self.config.order + prompt_tokens)[-self.config.order :]
        output: list[str] = []
        rng = random.Random(self.config.seed + sum(ord(char) for char in prompt))
        limit = min(max_tokens or self.config.max_tokens, 4096)
        heat = self.config.temperature if temperature is None else temperature
        for _ in range(limit):
            options = None
            for size in range(min(len(context), self.config.order), 0, -1):
                options = self.transitions.get(tuple(context[-size:]))
                if options:
                    break
            if not options:
                options = self.vocabulary
            token = self._sample(options, rng, heat)
            if token == "<eos>":
                break
            if token != "<bos>":
                output.append(token)
                context.append(token)
                context = context[-self.config.order :]
        return detokenize(output) or "I need more local training examples to answer that reliably."
