from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any

import numpy as np

from kg_tool.graph_ops import subgraph
from kg_tool.graphsage import GraphSAGEConfig, train_graphsage_embeddings
from kg_tool.ml_text import SentenceBertEncoder, build_node_texts, resolve_default_sentence_model_name
from kg_tool.models import Graph


@dataclass
class IndexConfig:
    sentence_model_name: str = field(default_factory=resolve_default_sentence_model_name)
    sentence_batch_size: int = 32
    graphsage_hidden_dim: int = 256
    graphsage_output_dim: int = 128
    graphsage_epochs: int = 30
    device: str | None = None


@dataclass
class IndexArtifacts:
    artifact_dir: str
    node_order: list[str]
    metadata_path: str
    embedding_path: str
    graph_snapshot_path: str


def build_semantic_index(graph: Graph, artifact_dir: str | Path, config: IndexConfig | None = None) -> IndexArtifacts:
    if config is None:
        config = IndexConfig()
    artifact_root = Path(artifact_dir)
    artifact_root.mkdir(parents=True, exist_ok=True)
    node_order, node_texts = build_node_texts(graph)
    sentence_encoder = SentenceBertEncoder(model_name=config.sentence_model_name, device=config.device)
    text_embeddings = sentence_encoder.encode(node_texts, batch_size=config.sentence_batch_size)
    graph_embeddings, training_info = train_graphsage_embeddings(
        graph,
        node_order=node_order,
        initial_features=text_embeddings,
        config=GraphSAGEConfig(
            hidden_dim=config.graphsage_hidden_dim,
            output_dim=config.graphsage_output_dim,
            epochs=config.graphsage_epochs,
            device=config.device,
        ),
    )
    metadata = {
        "node_order": node_order,
        "sentence_model_name": config.sentence_model_name,
        "graphsage_config": asdict(GraphSAGEConfig(hidden_dim=config.graphsage_hidden_dim, output_dim=config.graphsage_output_dim, epochs=config.graphsage_epochs, device=config.device)),
        "training_info": training_info,
        "nodes": [
            {
                "id": node_id,
                "name": graph.nodes[node_id].name,
                "type": graph.nodes[node_id].type,
                "description": graph.nodes[node_id].description,
                "aliases": graph.nodes[node_id].aliases,
                "sources": graph.nodes[node_id].sources,
                "text": node_texts[index],
                "attributes": graph.nodes[node_id].attributes,
            }
            for index, node_id in enumerate(node_order)
        ],
    }
    metadata_path = artifact_root / "metadata.json"
    embedding_path = artifact_root / "embeddings.npz"
    graph_snapshot_path = artifact_root / "graph_snapshot.json"
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    np.savez_compressed(embedding_path, text_embeddings=text_embeddings, graph_embeddings=graph_embeddings)
    graph.save(graph_snapshot_path)
    return IndexArtifacts(str(artifact_root), node_order, str(metadata_path), str(embedding_path), str(graph_snapshot_path))


def load_index(artifact_dir: str | Path) -> tuple[dict[str, Any], dict[str, np.ndarray], Graph]:
    artifact_root = Path(artifact_dir)
    metadata = json.loads((artifact_root / "metadata.json").read_text(encoding="utf-8"))
    embeddings_npz = np.load(artifact_root / "embeddings.npz")
    embeddings = {"text_embeddings": embeddings_npz["text_embeddings"], "graph_embeddings": embeddings_npz["graph_embeddings"]}
    graph = Graph.load(artifact_root / "graph_snapshot.json")
    return metadata, embeddings, graph


def _cosine_scores(query_embedding: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    if matrix.size == 0:
        return np.zeros((0,), dtype=np.float32)
    return matrix @ query_embedding.astype(np.float32)


def _keyword_score(query: str, text: str) -> float:
    query = query.strip().lower()
    text = text.strip().lower()
    if not query or not text:
        return 0.0
    if query in text:
        return 1.0
    overlap = len(set(query) & set(text))
    return overlap / max(len(set(query)), 1)


def query_semantic_index(artifact_dir: str | Path, query_text: str, top_k: int = 10, expand_hops: int = 1) -> list[dict[str, Any]]:
    metadata, embeddings, graph = load_index(artifact_dir)
    sentence_encoder = SentenceBertEncoder(model_name=metadata["sentence_model_name"])
    query_embedding = sentence_encoder.encode([query_text])[0]
    text_scores = _cosine_scores(query_embedding, embeddings["text_embeddings"])
    seed_count = min(max(top_k, 3), len(text_scores))
    seed_indices = np.argsort(text_scores)[::-1][:seed_count]
    graph_embeddings = embeddings["graph_embeddings"]
    if len(seed_indices) > 0 and graph_embeddings.size > 0:
        seed_graphs = graph_embeddings[seed_indices]
        graph_scores = np.max(graph_embeddings @ seed_graphs.T, axis=1)
    else:
        graph_scores = np.zeros_like(text_scores)
    results = []
    for index, node_info in enumerate(metadata["nodes"]):
        keyword = _keyword_score(query_text, node_info["text"])
        final_score = 0.65 * float(text_scores[index]) + 0.2 * float(graph_scores[index]) + 0.15 * keyword
        node = graph.nodes.get(node_info["id"])
        item = {
            "node_id": node_info["id"],
            "name": node.name if node else node_info["name"],
            "type": node.type if node else node_info["type"],
            "description": node.description if node else node_info.get("description", ""),
            "aliases": list(node.aliases) if node else list(node_info.get("aliases", [])),
            "attributes": dict(node.attributes) if node else dict(node_info.get("attributes", {})),
            "sources": list(node.sources) if node else list(node_info.get("sources", [])),
            "score": round(final_score, 4),
            "text_score": round(float(text_scores[index]), 4),
            "graph_score": round(float(graph_scores[index]), 4),
            "keyword_score": round(keyword, 4),
        }
        if expand_hops > 0:
            item["subgraph"] = subgraph(graph, node_info["id"], hops=expand_hops)
        results.append(item)
    return sorted(results, key=lambda item: item["score"], reverse=True)[:top_k]
