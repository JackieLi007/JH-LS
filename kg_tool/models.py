from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import json
from typing import Any


@dataclass
class Node:
    id: str
    name: str
    type: str
    description: str = ""
    aliases: list[str] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    sources: list[str] = field(default_factory=list)

    def all_names(self) -> list[str]:
        seen: set[str] = set()
        names: list[str] = []
        for item in [self.name, *self.aliases]:
            if item and item not in seen:
                seen.add(item)
                names.append(item)
        return names


@dataclass
class Edge:
    source: str
    target: str
    type: str
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class Graph:
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Graph":
        nodes = {
            item["id"]: Node(
                id=item["id"],
                name=item["name"],
                type=item["type"],
                description=item.get("description", ""),
                aliases=list(item.get("aliases", [])),
                attributes=dict(item.get("attributes", {})),
                sources=list(item.get("sources", [])),
            )
            for item in data.get("nodes", [])
        }
        edges = [
            Edge(
                source=item["source"],
                target=item["target"],
                type=item["type"],
                attributes=dict(item.get("attributes", {})),
            )
            for item in data.get("edges", [])
        ]
        return cls(nodes=nodes, edges=edges)

    @classmethod
    def load(cls, path: str | Path) -> "Graph":
        with Path(path).open("r", encoding="utf-8") as handle:
            return cls.from_dict(json.load(handle))

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [
                {
                    "id": node.id,
                    "name": node.name,
                    "type": node.type,
                    "description": node.description,
                    "aliases": node.aliases,
                    "attributes": node.attributes,
                    "sources": node.sources,
                }
                for node in self.nodes.values()
            ],
            "edges": [
                {
                    "source": edge.source,
                    "target": edge.target,
                    "type": edge.type,
                    "attributes": edge.attributes,
                }
                for edge in self.edges
            ],
        }

    def save(self, path: str | Path) -> None:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", encoding="utf-8") as handle:
            json.dump(self.to_dict(), handle, ensure_ascii=False, indent=2)

    def neighbors(self, node_id: str) -> set[str]:
        result: set[str] = set()
        for edge in self.edges:
            if edge.source == node_id:
                result.add(edge.target)
            if edge.target == node_id:
                result.add(edge.source)
        return result

    def edge_types(self, node_id: str) -> set[str]:
        result: set[str] = set()
        for edge in self.edges:
            if edge.source == node_id or edge.target == node_id:
                result.add(edge.type)
        return result

    def remove_nodes(self, node_ids: set[str]) -> None:
        self.nodes = {
            node_id: node
            for node_id, node in self.nodes.items()
            if node_id not in node_ids
        }
        self.edges = [
            edge
            for edge in self.edges
            if edge.source not in node_ids and edge.target not in node_ids
        ]

