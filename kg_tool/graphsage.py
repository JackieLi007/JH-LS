from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Sequence

import numpy as np
import torch
from torch import nn
import torch.nn.functional as F

from kg_tool.models import Graph
from kg_tool.ml_text import normalize_embeddings


@dataclass
class GraphSAGEConfig:
    hidden_dim: int = 128
    output_dim: int = 96
    epochs: int = 12
    learning_rate: float = 1e-3
    negative_ratio: int = 1
    weight_decay: float = 1e-5
    seed: int = 42
    device: str | None = None


def _resolve_device(device: str | None = None) -> str:
    if device:
        return device
    return "cuda" if torch.cuda.is_available() else "cpu"


def _set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


class GraphSAGELayer(nn.Module):
    def __init__(self, input_dim: int, output_dim: int) -> None:
        super().__init__()
        self.linear = nn.Linear(input_dim * 2, output_dim)

    def forward(self, x: torch.Tensor, adjacency: Sequence[list[int]]) -> torch.Tensor:
        aggregated = []
        for index, neighbors in enumerate(adjacency):
            if neighbors:
                neighbor_tensor = x[neighbors].mean(dim=0)
            else:
                neighbor_tensor = x[index]
            aggregated.append(torch.cat([x[index], neighbor_tensor], dim=0))
        stacked = torch.stack(aggregated, dim=0)
        return F.relu(self.linear(stacked))


class GraphSAGEModel(nn.Module):
    def __init__(self, input_dim: int, hidden_dim: int, output_dim: int) -> None:
        super().__init__()
        self.layer1 = GraphSAGELayer(input_dim, hidden_dim)
        self.layer2 = GraphSAGELayer(hidden_dim, output_dim)

    def forward(self, x: torch.Tensor, adjacency: Sequence[list[int]]) -> torch.Tensor:
        hidden = self.layer1(x, adjacency)
        output = self.layer2(hidden, adjacency)
        return F.normalize(output, p=2, dim=1)


def _build_graph_structures(graph: Graph, node_order: list[str]) -> tuple[list[list[int]], list[tuple[int, int]]]:
    index_map = {node_id: idx for idx, node_id in enumerate(node_order)}
    adjacency_sets = [set() for _ in node_order]
    edge_set: set[tuple[int, int]] = set()
    for edge in graph.edges:
        if edge.source not in index_map or edge.target not in index_map:
            continue
        left = index_map[edge.source]
        right = index_map[edge.target]
        if left == right:
            continue
        adjacency_sets[left].add(right)
        adjacency_sets[right].add(left)
        edge_set.add((min(left, right), max(left, right)))
    adjacency = [sorted(items) for items in adjacency_sets]
    return adjacency, list(edge_set)


def _negative_pairs(num_nodes: int, edge_lookup: set[tuple[int, int]], count: int, seed: int) -> list[tuple[int, int]]:
    rng = random.Random(seed)
    pairs: list[tuple[int, int]] = []
    attempts = 0
    max_attempts = max(count * 20, 100)
    while len(pairs) < count and attempts < max_attempts:
        left = rng.randrange(num_nodes)
        right = rng.randrange(num_nodes)
        attempts += 1
        if left == right:
            continue
        key = (min(left, right), max(left, right))
        if key in edge_lookup:
            continue
        pairs.append((left, right))
    return pairs


def train_graphsage_embeddings(
    graph: Graph,
    node_order: list[str],
    initial_features: np.ndarray,
    config: GraphSAGEConfig | None = None,
) -> tuple[np.ndarray, dict[str, float]]:
    if config is None:
        config = GraphSAGEConfig()
    _set_seed(config.seed)
    device = _resolve_device(config.device)
    features = np.asarray(initial_features, dtype=np.float32)
    if len(node_order) == 0:
        return np.zeros((0, config.output_dim), dtype=np.float32), {"loss": 0.0}
    adjacency, edge_pairs = _build_graph_structures(graph, node_order)
    if not edge_pairs:
        return normalize_embeddings(features), {"loss": 0.0}

    edge_lookup = set(edge_pairs)
    x = torch.tensor(features, dtype=torch.float32, device=device)
    model = GraphSAGEModel(x.shape[1], config.hidden_dim, config.output_dim).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=config.learning_rate, weight_decay=config.weight_decay)
    pos_src = torch.tensor([src for src, _ in edge_pairs], device=device)
    pos_dst = torch.tensor([dst for _, dst in edge_pairs], device=device)
    final_loss = 0.0

    for epoch in range(config.epochs):
        optimizer.zero_grad()
        embeddings = model(x, adjacency)
        pos_score = (embeddings[pos_src] * embeddings[pos_dst]).sum(dim=1)

        negative_pairs = _negative_pairs(
            num_nodes=len(node_order),
            edge_lookup=edge_lookup,
            count=max(len(edge_pairs) * config.negative_ratio, 1),
            seed=config.seed + epoch,
        )
        if negative_pairs:
            neg_src = torch.tensor([src for src, _ in negative_pairs], device=device)
            neg_dst = torch.tensor([dst for _, dst in negative_pairs], device=device)
            neg_score = (embeddings[neg_src] * embeddings[neg_dst]).sum(dim=1)
            loss = -F.logsigmoid(pos_score).mean() - F.logsigmoid(-neg_score).mean()
        else:
            loss = -F.logsigmoid(pos_score).mean()

        loss.backward()
        optimizer.step()
        final_loss = float(loss.detach().cpu().item())

    with torch.inference_mode():
        trained = model(x, adjacency).detach().cpu().numpy().astype(np.float32)
    return normalize_embeddings(trained), {"loss": final_loss}
