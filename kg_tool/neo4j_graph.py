from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from kg_tool.models import Edge, Graph, Node


DEFAULT_NAME_KEYS = ("name", "title", "key")
DEFAULT_DESCRIPTION_KEYS = ("description", "raw_text", "summary")
DEFAULT_NODE_TYPE_KEYS = (
    "node_type",
    "entity_type",
    "type_name",
    "class_name",
    "category",
    "type",
)
DEFAULT_RELATION_TYPE_KEYS = (
    "relation_type",
    "relationship_type",
    "type_name",
    "name",
    "type",
)
GENERIC_NODE_LABELS = {"Entity", "ENTITY", "Node", "NODE", "KnowledgeNode", "实体", "节点"}
GENERIC_RELATION_TYPES = {"RELATION", "Relationship", "RELATIONSHIP", "EDGE", "LINK", "关系", "连接"}


@dataclass
class Neo4jConfig:
    uri: str
    user: str
    password: str
    database: str = "neo4j"


def _import_driver() -> Any:
    try:
        from neo4j import GraphDatabase
    except ImportError as exc:
        raise RuntimeError("缺少 neo4j Python 驱动，请先安装：pip install neo4j") from exc
    return GraphDatabase


def _display_name(properties: dict[str, Any], labels: list[str], element_id: str) -> str:
    for key in DEFAULT_NAME_KEYS:
        value = properties.get(key)
        if value:
            return str(value)
    owner = properties.get("owner")
    raw_key = properties.get("key")
    if owner and raw_key:
        return f"{owner}:{raw_key}"
    if raw_key:
        return str(raw_key)
    if labels:
        return f"{labels[0]}:{element_id}"
    return element_id


def _node_type(properties: dict[str, Any], labels: list[str]) -> tuple[str, str]:
    for key in DEFAULT_NODE_TYPE_KEYS:
        value = properties.get(key)
        if value:
            return str(value), f"property:{key}"
    non_generic_labels = [label for label in labels if label not in GENERIC_NODE_LABELS]
    if non_generic_labels:
        return str(non_generic_labels[0]), "label"
    if labels:
        return str(labels[0]), "label"
    return "Unknown", "fallback"


def _relationship_type(rel_type: str, properties: dict[str, Any]) -> tuple[str, str]:
    if rel_type not in GENERIC_RELATION_TYPES:
        return rel_type, "neo4j_type"
    for key in DEFAULT_RELATION_TYPE_KEYS:
        value = properties.get(key)
        if value:
            return str(value), f"property:{key}"
    return rel_type, "neo4j_type"


def _description(properties: dict[str, Any]) -> str:
    for key in DEFAULT_DESCRIPTION_KEYS:
        value = properties.get(key)
        if value:
            return str(value)
    return ""


def _aliases(properties: dict[str, Any]) -> list[str]:
    candidates = []
    for key in ("aliases", "alias", "synonyms"):
        value = properties.get(key)
        if isinstance(value, list):
            candidates.extend(str(item) for item in value if item)
        elif isinstance(value, str) and value.strip():
            separators = ["|", ";", "，", ",", "、"]
            parts = [value]
            for sep in separators:
                next_parts: list[str] = []
                for part in parts:
                    next_parts.extend(part.split(sep))
                parts = next_parts
            candidates.extend(part.strip() for part in parts if part.strip())
    return list(dict.fromkeys(candidates))


def _sources(properties: dict[str, Any]) -> list[str]:
    value = properties.get("sources")
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    source = properties.get("source")
    if source:
        return [str(source)]
    return []


def load_graph_from_neo4j(config: Neo4jConfig) -> Graph:
    graph_db = _import_driver()
    driver = graph_db.driver(config.uri, auth=(config.user, config.password))
    try:
        with driver.session(database=config.database) as session:
            node_records = session.run(
                "MATCH (n) RETURN elementId(n) AS id, labels(n) AS labels, properties(n) AS props"
            )
            edge_records = session.run(
                "MATCH (s)-[r]->(t) "
                "RETURN elementId(s) AS source, elementId(t) AS target, type(r) AS rel_type, properties(r) AS props"
            )

            nodes: dict[str, Node] = {}
            for record in node_records:
                element_id = str(record["id"])
                labels = list(record["labels"] or [])
                properties = dict(record["props"] or {})
                primary_type, type_source = _node_type(properties, labels)
                attributes = dict(properties)
                attributes["_labels"] = labels
                attributes["_type_source"] = type_source
                nodes[element_id] = Node(
                    id=element_id,
                    name=_display_name(properties, labels, element_id),
                    type=primary_type,
                    description=_description(properties),
                    aliases=_aliases(properties),
                    attributes=attributes,
                    sources=_sources(properties),
                )

            edges = []
            for record in edge_records:
                properties = dict(record["props"] or {})
                rel_type, type_source = _relationship_type(str(record["rel_type"]), properties)
                attributes = dict(properties)
                attributes["_neo4j_type"] = str(record["rel_type"])
                attributes["_type_source"] = type_source
                edges.append(
                    Edge(
                        source=str(record["source"]),
                        target=str(record["target"]),
                        type=rel_type,
                        attributes=attributes,
                    )
                )
            return Graph(nodes=nodes, edges=edges)
    finally:
        driver.close()


def inspect_neo4j_schema(config: Neo4jConfig) -> dict[str, Any]:
    graph_db = _import_driver()
    driver = graph_db.driver(config.uri, auth=(config.user, config.password))
    try:
        with driver.session(database=config.database) as session:
            labels = [record["label"] for record in session.run("CALL db.labels() YIELD label RETURN label ORDER BY label")]
            relationship_types = [
                record["relationshipType"]
                for record in session.run(
                    "CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType ORDER BY relationshipType"
                )
            ]
            node_counts = {
                record["label"]: record["count"]
                for record in session.run(
                    "MATCH (n) UNWIND labels(n) AS label RETURN label, count(*) AS count ORDER BY count DESC"
                )
            }
            relationship_counts = {
                record["type"]: record["count"]
                for record in session.run(
                    "MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS count ORDER BY count DESC"
                )
            }
            sample_properties: dict[str, list[str]] = {}
            for label in labels:
                records = session.run(f"MATCH (n:`{label}`) RETURN keys(n) AS keys LIMIT 20")
                keys: set[str] = set()
                for record in records:
                    keys.update(record["keys"] or [])
                sample_properties[label] = sorted(keys)

            dynamic_node_types: dict[str, int] = {}
            dynamic_node_type_sources: dict[str, str] = {}
            node_type_records = session.run("MATCH (n) RETURN labels(n) AS labels, properties(n) AS props")
            for record in node_type_records:
                node_type, type_source = _node_type(dict(record["props"] or {}), list(record["labels"] or []))
                dynamic_node_types[node_type] = dynamic_node_types.get(node_type, 0) + 1
                dynamic_node_type_sources.setdefault(node_type, type_source)

            dynamic_relationship_types: dict[str, int] = {}
            dynamic_relationship_type_sources: dict[str, str] = {}
            relationship_type_records = session.run(
                "MATCH ()-[r]->() RETURN type(r) AS rel_type, properties(r) AS props"
            )
            for record in relationship_type_records:
                rel_type, type_source = _relationship_type(str(record["rel_type"]), dict(record["props"] or {}))
                dynamic_relationship_types[rel_type] = dynamic_relationship_types.get(rel_type, 0) + 1
                dynamic_relationship_type_sources.setdefault(rel_type, type_source)

            return {
                "labels": labels,
                "relationship_types": relationship_types,
                "node_counts": node_counts,
                "relationship_counts": relationship_counts,
                "sample_properties": sample_properties,
                "dynamic_node_types": dict(sorted(dynamic_node_types.items(), key=lambda item: item[1], reverse=True)),
                "dynamic_node_type_sources": dynamic_node_type_sources,
                "dynamic_relationship_types": dict(sorted(dynamic_relationship_types.items(), key=lambda item: item[1], reverse=True)),
                "dynamic_relationship_type_sources": dynamic_relationship_type_sources,
            }
    finally:
        driver.close()
