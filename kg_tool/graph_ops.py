from __future__ import annotations

from collections import deque
from typing import Any

from kg_tool.models import Edge, Graph


def subgraph(graph: Graph, center_id: str, hops: int = 1) -> dict[str, Any]:
    visited = {center_id}
    queue = deque([(center_id, 0)])
    collected_nodes = []
    collected_edges: list[Edge] = []

    while queue:
        current, depth = queue.popleft()
        node = graph.nodes.get(current)
        if node is None:
            continue
        collected_nodes.append(
            {
                "id": node.id,
                "name": node.name,
                "type": node.type,
                "description": node.description,
                "attributes": node.attributes,
            }
        )
        if depth >= hops:
            continue
        for edge in graph.edges:
            if edge.source != current and edge.target != current:
                continue
            collected_edges.append(
                {
                    "source": edge.source,
                    "target": edge.target,
                    "type": edge.type,
                    "attributes": edge.attributes,
                }
            )
            neighbor = edge.target if edge.source == current else edge.source
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, depth + 1))

    unique_nodes = {item["id"]: item for item in collected_nodes}
    unique_edges = {
        (item["source"], item["target"], item["type"]): item for item in collected_edges
    }
    return {"nodes": list(unique_nodes.values()), "edges": list(unique_edges.values())}
