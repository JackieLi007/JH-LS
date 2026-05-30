from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping

from kg_tool.neo4j_graph import Neo4jConfig, _import_driver, load_graph_from_neo4j
from kg_tool.neo4j_writeback import _quote_relation_type, write_link_results_to_neo4j


ENTITY_COLLECTION_KEY = "entities"
RELATION_COLLECTION_KEY = "relations"
TRIPLE_COLLECTION_KEY = "triples"
SCALAR_TYPES = (str, int, float, bool)
LEGACY_GENERIC_NODE_LABEL = "Entity"
DEFAULT_NODE_TYPE = "Unknown"
DEFAULT_RELATION_TYPE = "RELATION"


@dataclass(frozen=True)
class ParsedEntity:
    input_id: str
    name: str
    node_type: str
    properties: dict[str, Any]


@dataclass(frozen=True)
class ParsedRelation:
    input_id: str
    name: str
    subject_type: str
    object_type: str
    properties: dict[str, Any]


@dataclass(frozen=True)
class ParsedTriple:
    input_id: str
    subject_id: str
    predicate_id: str
    object_id: str
    properties: dict[str, Any]


@dataclass
class ParsedTriplePayload:
    entities: list[ParsedEntity]
    relations: list[ParsedRelation]
    triples: list[ParsedTriple]
    warnings: list[str]


def _as_text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _collection(data: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    value = data.get(key)
    if not isinstance(value, list):
        raise ValueError(f"triple payload must include a {key} list")
    items: list[Mapping[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise ValueError(f"{key}[{index}] must be an object")
        items.append(item)
    return items


def _safe_property_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, SCALAR_TYPES):
        return value
    if isinstance(value, (list, tuple, set)):
        values = [_safe_property_value(item) for item in value]
        values = [item for item in values if item is not None]
        if all(isinstance(item, SCALAR_TYPES) for item in values):
            return values
        return [json.dumps(item, ensure_ascii=False, default=str) for item in values]
    return json.dumps(value, ensure_ascii=False, default=str)


def _safe_properties(properties: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in properties.items():
        key_text = _as_text(key)
        if not key_text:
            continue
        safe_value = _safe_property_value(value)
        if safe_value is not None:
            result[key_text] = safe_value
    return result


def _quote_identifier(value: str) -> str:
    return f"`{value.replace('`', '``')}`"


def _defined_properties(item: Mapping[str, Any]) -> dict[str, Any]:
    raw_properties = item.get("properties") or item.get("attributes") or {}
    if not raw_properties:
        return {}
    if not isinstance(raw_properties, Mapping):
        raise ValueError("properties must be an object")
    return _safe_properties(raw_properties)


def _required_text(item: Mapping[str, Any], key: str, context: str) -> str:
    value = _as_text(item.get(key))
    if not value:
        raise ValueError(f"{context}.{key} is required")
    return value


def _ensure_unique_ids(items: list[Any], label: str) -> None:
    seen: set[str] = set()
    for item in items:
        input_id = item.input_id
        if input_id in seen:
            raise ValueError(f"duplicate {label} id {input_id}")
        seen.add(input_id)


def _parse_entities(items: list[Mapping[str, Any]]) -> list[ParsedEntity]:
    entities: list[ParsedEntity] = []
    for index, item in enumerate(items):
        context = f"entities[{index}]"
        input_id = _required_text(item, "id", context)
        name = _required_text(item, "name", context)
        node_type = _as_text(item.get("type"), default=DEFAULT_NODE_TYPE)
        properties = {"id": input_id, "name": name}
        properties.update(_defined_properties(item))
        entities.append(ParsedEntity(input_id=input_id, name=name, node_type=node_type, properties=properties))
    _ensure_unique_ids(entities, "entity")
    return entities


def _parse_relations(items: list[Mapping[str, Any]]) -> list[ParsedRelation]:
    relations: list[ParsedRelation] = []
    for index, item in enumerate(items):
        context = f"relations[{index}]"
        input_id = _required_text(item, "id", context)
        name = _required_text(item, "name", context)
        relations.append(
            ParsedRelation(
                input_id=input_id,
                name=name or DEFAULT_RELATION_TYPE,
                subject_type=_as_text(item.get("subject_type")),
                object_type=_as_text(item.get("object_type")),
                properties=_defined_properties(item),
            )
        )
    _ensure_unique_ids(relations, "relation")
    return relations


def _parse_triples(
    items: list[Mapping[str, Any]],
    entity_ids: set[str],
    relation_ids: set[str],
) -> list[ParsedTriple]:
    triples: list[ParsedTriple] = []
    for index, item in enumerate(items):
        context = f"triples[{index}]"
        input_id = _as_text(item.get("id"), default=f"triple:{index}")
        subject_id = _required_text(item, "subject_id", context)
        predicate_id = _required_text(item, "predicate_id", context)
        object_id = _required_text(item, "object_id", context)
        if subject_id not in entity_ids:
            raise ValueError(f"triple {input_id} references missing subject entity {subject_id}")
        if object_id not in entity_ids:
            raise ValueError(f"triple {input_id} references missing object entity {object_id}")
        if predicate_id not in relation_ids:
            raise ValueError(f"triple {input_id} references missing relation {predicate_id}")
        triples.append(
            ParsedTriple(
                input_id=input_id,
                subject_id=subject_id,
                predicate_id=predicate_id,
                object_id=object_id,
                properties=_defined_properties(item),
            )
        )
    _ensure_unique_ids(triples, "triple")
    return triples


def _type_warnings(
    entities: list[ParsedEntity],
    relations: list[ParsedRelation],
    triples: list[ParsedTriple],
) -> list[str]:
    warnings: list[str] = []
    entity_by_id = {entity.input_id: entity for entity in entities}
    relation_by_id = {relation.input_id: relation for relation in relations}
    for triple in triples:
        subject = entity_by_id[triple.subject_id]
        relation = relation_by_id[triple.predicate_id]
        obj = entity_by_id[triple.object_id]
        if relation.subject_type and subject.node_type != relation.subject_type:
            warnings.append(
                f"triple {triple.input_id} subject type mismatch: expected {relation.subject_type}, got {subject.node_type}"
            )
        if relation.object_type and obj.node_type != relation.object_type:
            warnings.append(
                f"triple {triple.input_id} object type mismatch: expected {relation.object_type}, got {obj.node_type}"
            )
    return warnings


def load_triple_payload(payload: str | Path | Mapping[str, Any]) -> Any:
    if isinstance(payload, Mapping):
        return dict(payload)
    payload_text = str(payload)
    stripped = payload_text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        return json.loads(payload_text)
    candidate = Path(payload_text)
    try:
        exists = candidate.exists()
    except OSError:
        exists = False
    if exists:
        return json.loads(candidate.read_text(encoding="utf-8"))
    return json.loads(payload_text)


def parse_triple_payload(payload: str | Path | Mapping[str, Any]) -> ParsedTriplePayload:
    data = load_triple_payload(payload)
    if not isinstance(data, Mapping):
        raise ValueError("triple payload must be a JSON object")
    entities = _parse_entities(_collection(data, ENTITY_COLLECTION_KEY))
    relations = _parse_relations(_collection(data, RELATION_COLLECTION_KEY))
    entity_ids = {entity.input_id for entity in entities}
    relation_ids = {relation.input_id for relation in relations}
    triples = _parse_triples(_collection(data, TRIPLE_COLLECTION_KEY), entity_ids, relation_ids)
    warnings = _type_warnings(entities, relations, triples)
    return ParsedTriplePayload(entities=entities, relations=relations, triples=triples, warnings=warnings)


def _node_snapshot(record: Any) -> dict[str, Any]:
    return {
        "element_id": str(record["element_id"]),
        "labels": list(record["labels"] or []),
        "properties": dict(record["props"] or {}),
    }


def _find_existing_node(session: Any, input_id: str) -> dict[str, Any] | None:
    record = session.run(
        "MATCH (n) "
        "WHERE n.id = $input_id "
        "RETURN elementId(n) AS element_id, labels(n) AS labels, properties(n) AS props "
        "LIMIT 1",
        input_id=input_id,
    ).single()
    if record is None:
        return None
    return _node_snapshot(record)


def _node_snapshot_by_element_id(session: Any, element_id: str) -> dict[str, Any]:
    record = session.run(
        "MATCH (n) "
        "WHERE elementId(n) = $element_id "
        "RETURN elementId(n) AS element_id, labels(n) AS labels, properties(n) AS props "
        "LIMIT 1",
        element_id=element_id,
    ).single()
    if record is None:
        raise RuntimeError(f"node not found after write: {element_id}")
    return _node_snapshot(record)


def _remove_legacy_generic_label(session: Any) -> int:
    result = session.run(
        f"MATCH (n:{_quote_identifier(LEGACY_GENERIC_NODE_LABEL)}) "
        "WHERE size(labels(n)) > 1 "
        f"REMOVE n:{_quote_identifier(LEGACY_GENERIC_NODE_LABEL)} "
        "RETURN count(n) AS count"
    )
    record = result.single()
    return int(record["count"] if record else 0)


def _upsert_entity(session: Any, entity: ParsedEntity) -> tuple[str, bool, dict[str, Any] | None, dict[str, Any]]:
    node_type = entity.node_type or DEFAULT_NODE_TYPE
    type_label = _quote_identifier(node_type)
    before = _find_existing_node(session, entity.input_id)
    element_id = before["element_id"] if before else None
    created = before is None
    if created:
        result = session.run(
            f"CREATE (n:{type_label}) "
            "SET n = $properties "
            "RETURN elementId(n) AS element_id",
            properties=entity.properties,
        )
        created_element_id = str(result.single()["element_id"])
        return created_element_id, True, None, _node_snapshot_by_element_id(session, created_element_id)

    remove_legacy_label = ""
    if node_type != LEGACY_GENERIC_NODE_LABEL:
        remove_legacy_label = f"REMOVE n:{_quote_identifier(LEGACY_GENERIC_NODE_LABEL)} "
    query = (
        f"MATCH (n) WHERE elementId(n) = $element_id "
        f"{remove_legacy_label}"
        f"SET n:{type_label}, n = $properties"
    )
    session.run(
        query,
        element_id=element_id,
        properties=entity.properties,
    ).consume()
    return element_id, False, before, _node_snapshot_by_element_id(session, element_id)


def _relationship_snapshot(
    session: Any,
    source_element_id: str,
    target_element_id: str,
    relation_name: str,
) -> dict[str, Any] | None:
    relation_type = _quote_relation_type(relation_name)
    record = session.run(
        "MATCH (s) WHERE elementId(s) = $source_element_id "
        "MATCH (o) WHERE elementId(o) = $target_element_id "
        f"OPTIONAL MATCH (s)-[r:{relation_type}]->(o) "
        "RETURN elementId(r) AS element_id, properties(r) AS props "
        "LIMIT 1",
        source_element_id=source_element_id,
        target_element_id=target_element_id,
    ).single()
    if record is None or record["element_id"] is None:
        return None
    return {
        "element_id": str(record["element_id"]),
        "properties": dict(record["props"] or {}),
    }


def _upsert_relationship(
    session: Any,
    source_element_id: str,
    target_element_id: str,
    relation: ParsedRelation,
    triple: ParsedTriple,
) -> tuple[bool, dict[str, Any] | None, dict[str, Any]]:
    relation_name = relation.name or DEFAULT_RELATION_TYPE
    relation_type = _quote_relation_type(relation_name)
    before = _relationship_snapshot(session, source_element_id, target_element_id, relation_name)
    properties = {**relation.properties, **triple.properties}
    properties = _safe_properties(properties)
    query = (
        "MATCH (s) WHERE elementId(s) = $source_element_id "
        "MATCH (o) WHERE elementId(o) = $target_element_id "
        f"MERGE (s)-[r:{relation_type}]->(o) "
        "SET r = $properties "
    )
    result = session.run(
        query,
        source_element_id=source_element_id,
        target_element_id=target_element_id,
        properties=properties,
    )
    summary = result.consume()
    after = _relationship_snapshot(session, source_element_id, target_element_id, relation_name)
    if after is None:
        raise RuntimeError(f"relationship not found after write: {triple.input_id}")
    return bool(summary.counters.relationships_created), before, after


def upsert_triples_to_neo4j(config: Neo4jConfig, payload: str | Path | Mapping[str, Any]) -> dict[str, Any]:
    parsed = parse_triple_payload(payload)
    graph_db = _import_driver()
    driver = graph_db.driver(config.uri, auth=(config.user, config.password))
    entity_element_ids: dict[str, str] = {}
    created_nodes = 0
    matched_nodes = 0
    created_relationships = 0
    matched_relationships = 0
    cleaned_legacy_entity_labels = 0
    entity_changes: list[dict[str, Any]] = []
    relationship_changes: list[dict[str, Any]] = []
    try:
        with driver.session(database=config.database) as session:
            cleaned_legacy_entity_labels = _remove_legacy_generic_label(session)
            for entity in parsed.entities:
                element_id, created, before, after = _upsert_entity(session, entity)
                entity_element_ids[entity.input_id] = element_id
                entity_changes.append(
                    {
                        "entity_id": entity.input_id,
                        "element_id": element_id,
                        "created": created,
                        "before": before,
                        "after": after,
                    }
                )
                if created:
                    created_nodes += 1
                else:
                    matched_nodes += 1

            relation_by_id = {relation.input_id: relation for relation in parsed.relations}
            for triple in parsed.triples:
                relation = relation_by_id[triple.predicate_id]
                created, before, after = _upsert_relationship(
                    session,
                    source_element_id=entity_element_ids[triple.subject_id],
                    target_element_id=entity_element_ids[triple.object_id],
                    relation=relation,
                    triple=triple,
                )
                relationship_changes.append(
                    {
                        "triple_id": triple.input_id,
                        "source_entity_id": triple.subject_id,
                        "target_entity_id": triple.object_id,
                        "relation_id": relation.input_id,
                        "relation_name": relation.name or DEFAULT_RELATION_TYPE,
                        "element_id": after["element_id"],
                        "created": created,
                        "before": before,
                        "after": after,
                    }
                )
                if created:
                    created_relationships += 1
                else:
                    matched_relationships += 1
    finally:
        driver.close()

    return {
        "input_entities": len(parsed.entities),
        "input_relations": len(parsed.relations),
        "input_triples": len(parsed.triples),
        "created_nodes": created_nodes,
        "matched_nodes": matched_nodes,
        "created_relationships": created_relationships,
        "matched_relationships": matched_relationships,
        "cleaned_legacy_entity_labels": cleaned_legacy_entity_labels,
        "entity_element_ids": entity_element_ids,
        "touched_node_ids": list(dict.fromkeys(entity_element_ids.values())),
        "entity_changes": entity_changes,
        "relationship_changes": relationship_changes,
        "warnings": parsed.warnings,
    }


def _link_summary(graph: Graph, result: Any, writeback: dict[str, Any] | None) -> dict[str, Any]:
    summary = {
        "input_nodes": len(graph.nodes),
        "output_nodes": len(result.merged_graph.nodes),
        "input_edges": len(graph.edges),
        "output_edges": len(result.merged_graph.edges),
        "merged_nodes": result.merge_map,
        "merge_edge_count": len(result.merge_edges),
        "added_edge_count": len(result.added_edges),
        "graphsage_training": result.graphsage_training,
        "similarity_details": result.similarity_details,
    }
    if writeback is not None:
        summary["writeback"] = {key: value for key, value in writeback.items() if key != "relationship_changes"}
    return summary


def ingest_triples_json(
    payload: str | Path | Mapping[str, Any],
    neo4j_config: Neo4jConfig,
    ml_config: Any | None = None,
    *,
    run_linking: bool = True,
    write_link_results: bool = True,
    focus_only: bool = True,
    output_graph: str | Path | None = None,
    report_path: str | Path | None = None,
    record_version: bool = True,
    version_history_path: str | Path | None = None,
    max_versions: int = 10,
) -> dict[str, Any]:
    write_summary = upsert_triples_to_neo4j(neo4j_config, payload)
    summary: dict[str, Any] = {"write": write_summary}

    if run_linking:
        try:
            from kg_tool.ml_linking import connect_graph_with_ml

            graph = load_graph_from_neo4j(neo4j_config)
            focus_node_ids = set(write_summary["touched_node_ids"]) if focus_only else None
            result = connect_graph_with_ml(graph, config=ml_config, focus_node_ids=focus_node_ids)
            writeback = None
            if write_link_results:
                writeback = write_link_results_to_neo4j(
                    neo4j_config,
                    merge_edges=result.merge_edges,
                    added_edges=result.added_edges,
                )
                write_summary["link_relationship_changes"] = writeback.get("relationship_changes", [])
                write_summary["link_writeback"] = {
                    key: value for key, value in writeback.items() if key != "relationship_changes"
                }
            if output_graph:
                result.merged_graph.save(output_graph)
            summary["linking"] = _link_summary(graph, result, writeback)
        except Exception as exc:
            summary["postprocess"] = {
                "status": "skipped",
                "error": str(exc),
            }

    if record_version:
        from kg_tool.versioning import DEFAULT_VERSION_HISTORY_PATH, record_triple_version

        history_path = version_history_path or DEFAULT_VERSION_HISTORY_PATH
        version_record = record_triple_version(
            load_triple_payload(payload),
            write_summary,
            history_path=history_path,
            max_versions=max_versions,
        )
        write_summary["version"] = {
            "version_id": version_record["version_id"],
            "history_path": str(history_path),
        }

    if report_path:
        output = Path(report_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    return summary
