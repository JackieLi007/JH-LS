from __future__ import annotations

import os
from pathlib import Path
from threading import Lock
from typing import Iterable

import numpy as np
import torch


def _env_bool(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


KG_HF_OFFLINE = _env_bool("KG_HF_OFFLINE", True)
if KG_HF_OFFLINE:
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("HF_DATASETS_OFFLINE", "1")

from sentence_transformers import SentenceTransformer
from transformers import AutoModel, AutoTokenizer

from kg_tool.models import Graph, Node


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCAL_MODEL_ROOT = PROJECT_ROOT / "models"
HF_CACHE_ROOT = Path.home() / ".cache" / "huggingface" / "hub"
DEFAULT_BERT_MODEL_NAME = "bert-base-chinese"
DEFAULT_SENTENCE_MODEL_NAME = DEFAULT_BERT_MODEL_NAME
IGNORED_TEXT_ATTRIBUTE_KEYS = {"id"}
_ENCODER_CACHE_LOCK = Lock()
_BERT_ENCODER_CACHE: dict[tuple[str, str, int], "BertTextEncoder"] = {}
_SENTENCE_ENCODER_CACHE: dict[tuple[str, str], "SentenceBertEncoder"] = {}
_BERT_TEXT_EMBEDDING_CACHE: dict[tuple[str, int, str], np.ndarray] = {}


def resolve_default_sentence_model_name() -> str:
    configured = os.environ.get("KG_SENTENCE_MODEL") or os.environ.get("SENTENCE_MODEL_NAME")
    return configured.strip() if configured and configured.strip() else DEFAULT_SENTENCE_MODEL_NAME


def normalize_embeddings(matrix: np.ndarray) -> np.ndarray:
    matrix = np.asarray(matrix, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    return matrix / norms


def _embedding_cache_limit() -> int:
    raw = os.environ.get("KG_BERT_EMBEDDING_CACHE_SIZE", "20000").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 20000


def _remember_embedding(cache_key: tuple[str, int, str], embedding: np.ndarray) -> None:
    limit = _embedding_cache_limit()
    if limit <= 0:
        return
    if len(_BERT_TEXT_EMBEDDING_CACHE) >= limit and cache_key not in _BERT_TEXT_EMBEDDING_CACHE:
        # Dicts preserve insertion order; trimming one item keeps the cache bounded.
        oldest_key = next(iter(_BERT_TEXT_EMBEDDING_CACHE))
        _BERT_TEXT_EMBEDDING_CACHE.pop(oldest_key, None)
    _BERT_TEXT_EMBEDDING_CACHE[cache_key] = embedding


def _model_cache_dir(model_name: str) -> Path:
    normalized = model_name.replace("/", "--")
    return HF_CACHE_ROOT / f"models--{normalized}"


def _project_model_candidates(model_name: str) -> list[Path]:
    normalized = model_name.replace("/", "--")
    return [
        LOCAL_MODEL_ROOT / model_name,
        LOCAL_MODEL_ROOT / normalized,
    ]


def resolve_local_model_path(model_name: str) -> str | None:
    candidate = Path(model_name)
    if candidate.exists():
        return str(candidate)
    for project_candidate in _project_model_candidates(model_name):
        if project_candidate.exists():
            return str(project_candidate)
    snapshot_root = _model_cache_dir(model_name) / "snapshots"
    if not snapshot_root.exists():
        return None
    snapshots = sorted(path for path in snapshot_root.iterdir() if path.is_dir())
    if not snapshots:
        return None
    return str(snapshots[-1])


def _neighbor_contexts(graph: Graph, max_neighbors: int = 8) -> dict[str, list[str]]:
    contexts = {node_id: [] for node_id in graph.nodes}
    for edge in graph.edges:
        if edge.source in graph.nodes and edge.target in graph.nodes:
            target = graph.nodes[edge.target]
            source_items = contexts[edge.source]
            if len(source_items) < max_neighbors:
                source_items.append(f"{edge.type}->{target.type}:{target.name}")

            source = graph.nodes[edge.source]
            target_items = contexts[edge.target]
            if len(target_items) < max_neighbors:
                target_items.append(f"{edge.type}<-{source.type}:{source.name}")
    return contexts


def compose_node_text(node: Node, neighbor_parts: list[str] | None = None) -> str:
    alias_text = "；".join(node.aliases[:6])
    attr_parts = []
    for key, value in node.attributes.items():
        if key.startswith("_") or key in IGNORED_TEXT_ATTRIBUTE_KEYS:
            continue
        attr_parts.append(f"{key}:{value}")
    pieces = [
        f"名称:{node.name}",
        f"类型:{node.type}",
    ]
    if alias_text:
        pieces.append(f"别名:{alias_text}")
    if node.description:
        pieces.append(f"描述:{node.description}")
    if attr_parts:
        pieces.append("属性:" + "；".join(attr_parts))
    if neighbor_parts:
        pieces.append("邻域:" + "；".join(neighbor_parts))
    return "。".join(pieces)


def build_node_texts(graph: Graph, node_order: Iterable[str] | None = None, max_neighbors: int = 8) -> tuple[list[str], list[str]]:
    ordered_ids = list(node_order or graph.nodes.keys())
    contexts = _neighbor_contexts(graph, max_neighbors=max_neighbors)
    texts = [compose_node_text(graph.nodes[node_id], contexts.get(node_id, [])) for node_id in ordered_ids]
    return ordered_ids, texts


def _resolve_device(device: str | None = None) -> str:
    if device:
        return device
    return "cuda" if torch.cuda.is_available() else "cpu"


def _mean_pool(last_hidden_state: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
    mask = attention_mask.unsqueeze(-1).expand(last_hidden_state.size()).float()
    masked = last_hidden_state * mask
    summed = masked.sum(dim=1)
    counts = torch.clamp(mask.sum(dim=1), min=1e-9)
    return summed / counts


def _load_auto_model(model_source: str, local_only: bool, device: str) -> AutoModel:
    load_kwargs: dict[str, object] = {"local_files_only": local_only}
    try:
        load_kwargs["low_cpu_mem_usage"] = True
        if device == "cuda":
            load_kwargs["torch_dtype"] = torch.float16
        model = AutoModel.from_pretrained(model_source, **load_kwargs)
    except TypeError:
        load_kwargs.pop("low_cpu_mem_usage", None)
        load_kwargs.pop("torch_dtype", None)
        model = AutoModel.from_pretrained(model_source, **load_kwargs)
    return model.to(device)


class BertTextEncoder:
    def __init__(
        self,
        model_name: str = DEFAULT_BERT_MODEL_NAME,
        device: str | None = None,
        max_length: int = 128,
    ) -> None:
        self.model_name = model_name
        self.device = _resolve_device(device)
        self.max_length = max_length
        model_source = resolve_local_model_path(model_name) or model_name
        local_only = KG_HF_OFFLINE or model_source != model_name
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(model_source, local_files_only=local_only)
            self.model = _load_auto_model(model_source, local_only=local_only, device=self.device)
            self.model.eval()
        except Exception as exc:
            raise RuntimeError(
                f"无法加载 BERT 模型 {model_name}。请确认模型名可用，或先在联网环境下完成下载。"
            ) from exc

    @torch.inference_mode()
    def encode(self, texts: list[str], batch_size: int = 16) -> np.ndarray:
        hidden_size = int(self.model.config.hidden_size)
        if not texts:
            return np.zeros((0, hidden_size), dtype=np.float32)

        embeddings: list[np.ndarray | None] = [None] * len(texts)
        pending_texts: list[str] = []
        pending_positions: list[int] = []
        cache_enabled = _embedding_cache_limit() > 0
        for index, text in enumerate(texts):
            cache_key = (self.model_name, self.max_length, text)
            cached = _BERT_TEXT_EMBEDDING_CACHE.get(cache_key) if cache_enabled else None
            if cached is None:
                pending_texts.append(text)
                pending_positions.append(index)
            else:
                embeddings[index] = cached

        for offset in range(0, len(pending_texts), batch_size):
            batch_texts = pending_texts[offset : offset + batch_size]
            batch_positions = pending_positions[offset : offset + batch_size]
            encoded = self.tokenizer(
                batch_texts,
                padding=True,
                truncation=True,
                max_length=self.max_length,
                return_tensors="pt",
            )
            encoded = {key: value.to(self.device) for key, value in encoded.items()}
            outputs = self.model(**encoded)
            pooled = _mean_pool(outputs.last_hidden_state, encoded["attention_mask"])
            batch_embeddings = normalize_embeddings(pooled.detach().cpu().numpy().astype(np.float32))
            for position, embedding in zip(batch_positions, batch_embeddings):
                embeddings[position] = embedding
                _remember_embedding((self.model_name, self.max_length, texts[position]), embedding)

        return np.vstack([embedding for embedding in embeddings if embedding is not None]).astype(np.float32)


def get_bert_text_encoder(
    model_name: str = DEFAULT_BERT_MODEL_NAME,
    device: str | None = None,
    max_length: int = 128,
) -> BertTextEncoder:
    key = (model_name, device or "", max_length)
    with _ENCODER_CACHE_LOCK:
        encoder = _BERT_ENCODER_CACHE.get(key)
        if encoder is None:
            encoder = BertTextEncoder(model_name=model_name, device=device, max_length=max_length)
            _BERT_ENCODER_CACHE[key] = encoder
        return encoder


class SentenceBertEncoder:
    def __init__(
        self,
        model_name: str | None = None,
        device: str | None = None,
    ) -> None:
        self.model_name = model_name or resolve_default_sentence_model_name()
        model_name = self.model_name
        self.device = _resolve_device(device)
        model_source = resolve_local_model_path(self.model_name) or self.model_name
        local_only = KG_HF_OFFLINE or model_source != self.model_name
        try:
            self.model = SentenceTransformer(model_source, device=self.device, local_files_only=local_only)
        except Exception as exc:
            raise RuntimeError(
                f"无法加载 Sentence-BERT 模型 {model_name}。请确认模型名可用，或先在联网环境下完成下载。"
            ) from exc

    def encode(self, texts: list[str], batch_size: int = 32) -> np.ndarray:
        if not texts:
            embedding_dim = int(self.model.get_sentence_embedding_dimension())
            return np.zeros((0, embedding_dim), dtype=np.float32)
        embeddings = self.model.encode(
            texts,
            batch_size=batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return np.asarray(embeddings, dtype=np.float32)


def get_sentence_bert_encoder(
    model_name: str | None = None,
    device: str | None = None,
) -> SentenceBertEncoder:
    resolved_name = model_name or resolve_default_sentence_model_name()
    key = (resolved_name, device or "")
    with _ENCODER_CACHE_LOCK:
        encoder = _SENTENCE_ENCODER_CACHE.get(key)
        if encoder is None:
            encoder = SentenceBertEncoder(model_name=resolved_name, device=device)
            _SENTENCE_ENCODER_CACHE[key] = encoder
        return encoder
