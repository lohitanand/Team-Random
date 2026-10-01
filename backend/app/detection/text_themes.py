"""Text theme classifier (CLAUDE.md §7.4).

Multilingual sentence embeddings + LogisticRegression. When the top probability is below
TEXT_THEME_MIN_PROB, the LLM is asked zero-shot with the same label set and a strict JSON schema;
if the LLM is disabled, over budget or returns anything invalid, the label is `other`.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Literal

import joblib
import numpy as np
from pydantic import BaseModel, ValidationError
from sklearn.linear_model import LogisticRegression

from backend.app.config import Settings, get_settings
from backend.app.llm.client import LLMClient, LLMError, load_prompt
from backend.app.schemas.llm import ThemeOut

EMBEDDER_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
THEME_MODEL_FILE = "text_theme_model.joblib"
Embed = Callable[[list[str]], np.ndarray]


class ThemePrediction(BaseModel):
    theme: str
    prob: float
    method: Literal["classifier", "llm", "fallback"]


@lru_cache
def sentence_embedder() -> Embed:
    """Load the multilingual model once (downloads on first use, then cached by Hugging Face)."""
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(EMBEDDER_NAME, device="cpu")

    def embed(texts: list[str]) -> np.ndarray:
        return model.encode(texts, batch_size=64, normalize_embeddings=True, show_progress_bar=False)

    return embed


def llm_zero_shot(client: LLMClient, text: str) -> str | None:
    """Theme from the LLM, or None if the call fails or the output is not a valid label."""
    try:
        raw = client.complete_json(load_prompt("text_theme"), f"Customer message:\n{text[:1000]}")
        return ThemeOut.model_validate(json.loads(raw)).theme
    except (LLMError, ValueError, ValidationError):
        return None


class ThemeClassifier:
    def __init__(self, clf: LogisticRegression, embed: Embed, llm: LLMClient | None = None,
                 settings: Settings | None = None) -> None:
        self.clf = clf
        self.embed = embed
        self.settings = settings or get_settings()
        self.llm = llm or LLMClient(self.settings)

    @classmethod
    def fit(cls, texts: list[str], labels: list[str], embed: Embed, seed: int, **kwargs) -> "ThemeClassifier":
        clf = LogisticRegression(max_iter=3000, C=4.0, random_state=seed)
        clf.fit(embed(texts), labels)
        return cls(clf, embed, **kwargs)

    @property
    def classes(self) -> list[str]:
        return [str(c) for c in self.clf.classes_]

    def predict_proba(self, texts: list[str]) -> np.ndarray:
        return self.clf.predict_proba(self.embed(texts))

    def classify(self, texts: list[str], llm_budget: int | None = None) -> list[ThemePrediction]:
        if not texts:
            return []
        budget = self.settings.text_llm_max_calls if llm_budget is None else llm_budget
        probs = self.predict_proba(texts)
        out: list[ThemePrediction] = []
        for text, row in zip(texts, probs):
            best = int(np.argmax(row))
            prob = float(row[best])
            if prob >= self.settings.text_theme_min_prob:
                out.append(ThemePrediction(theme=self.classes[best], prob=round(prob, 4), method="classifier"))
                continue
            theme = None
            if self.llm.active and budget > 0:
                budget -= 1
                theme = llm_zero_shot(self.llm, text)
            if theme is not None:
                out.append(ThemePrediction(theme=theme, prob=round(prob, 4), method="llm"))
            else:
                out.append(ThemePrediction(theme="other", prob=round(prob, 4), method="fallback"))
        return out

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"clf": self.clf, "embedder": EMBEDDER_NAME}, path)

    @classmethod
    def load(cls, path: Path, embed: Embed | None = None, **kwargs) -> "ThemeClassifier":
        data = joblib.load(path)
        return cls(data["clf"], embed or sentence_embedder(), **kwargs)
