from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from kg_tool.neo4j_graph import Neo4jConfig, _import_driver


DEFAULT_VERSION_HISTORY_PATH = Path("artifacts/kg_versions/history.json")
DEFAULT_MAX_VERSIONS = 10


def _quote_identifier(value: str) -> str:
    return f"`{value.replace('`', '``')}`"


def _quote_relation_type(value: str) -> str:
    return f"`{value.replace('`', '``')}`"


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _load_history(path: str | Path) -> dict[str, Any]:
    history_path = Path(path)
    if not history_path.exists():
        return {"schema_version": 1, "versions": []}
    data = json.loads(history_path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise ValueError("version history must be a JSON object")
    versions = data.get("versions")
    if not isinstance(versions, list):
        raise ValueError("version history must include a versions list")
    return {"schema_version": int(data.get("schema_version", 1)), "versions": versions}


def _save_history(path: str | Path, history: Mapping[str, Any]) -> None:
    history_path = Path(path)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(json.dumps(history, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def record_triple_version(
    payload: Any,
    write_summary: Mapping[str, Any],
    *,
    history_path: str | Path = DEFAULT_VERSION_HISTORY_PATH,
    max_versions: int = DEFAULT_MAX_VERSIONS,
) -> dict[str, Any]:
    history = _load_history(history_path)
    now = datetime.now(timezone.utc).isoformat()
    record = {
        "version_id": f"{now}-{uuid4().hex[:8]}",
        "created_at": now,
        "payload": _jsonable(payload),
        "write_summary": _jsonable(write_summary),
    }
    versions = [*history["versions"], record]
    history["versions"] = versions[-max_versions:]
    _save_history(history_path, history)
    return record


def list_triple_versions(
    *,
    history_path: str | Path = DEFAULT_VERSION_HISTORY_PATH,
) -> list[dict[str, Any]]:
    return list(_load_history(history_path)["versions"])


def _delete_relationship(tx: Any, change: Mapping[str, Any]) -> int:
    relation_type = _quote_relation_type(str(change["relation_name"]))
    result = tx.run(
        "MATCH (s {id: $source_entity_id})-[r:"
        f"{relation_type}"
        "]->(o {id: $target_entity_id}) "
        "WITH r LIMIT 1 "
        "WITH collect(r) AS relationships "
        "FOREACH (item IN relationships | DELETE item) "
        "RETURN size(relationships) AS count",
        source_entity_id=change["source_entity_id"],
        target_entity_id=change["target_entity_id"],
    )
    record = result.single()
    return int(record["count"] if record else 0)


def _restore_relationship(tx: Any, change: Mapping[str, Any]) -> int:
    before = change.get("before")
    if not before:
        return _delete_relationship(tx, change)
    relation_type = _quote_relation_type(str(change["relation_name"]))
    result = tx.run(
        "MATCH (s {id: $source_entity_id})-[r:"
        f"{relation_type}"
        "]->(o {id: $target_entity_id}) "
        "SET r = $properties "
        "RETURN count(r) AS count",
        source_entity_id=change["source_entity_id"],
        target_entity_id=change["target_entity_id"],
        properties=dict(before.get("properties", {})),
    )
    record = result.single()
    return int(record["count"] if record else 0)


def _delete_node(tx: Any, change: Mapping[str, Any]) -> int:
    result = tx.run(
        "MATCH (n {id: $entity_id}) "
        "WITH collect(n) AS nodes "
        "FOREACH (item IN nodes | DETACH DELETE item) "
        "RETURN size(nodes) AS count",
        entity_id=change["entity_id"],
    )
    record = result.single()
    return int(record["count"] if record else 0)


def _restore_node(tx: Any, change: Mapping[str, Any]) -> int:
    before = change.get("before")
    if not before:
        return _delete_node(tx, change)
    labels = [str(label) for label in before.get("labels", []) if str(label)]
    after_labels = [str(label) for label in change.get("after", {}).get("labels", []) if str(label)]
    labels_to_remove = [label for label in after_labels if label not in set(labels)]
    remove_labels = "".join(f":{_quote_identifier(label)}" for label in labels_to_remove)
    set_labels = "".join(f":{_quote_identifier(label)}" for label in labels)
    query = "MATCH (n {id: $entity_id}) "
    if remove_labels:
        query += f"REMOVE n{remove_labels} "
    query += "SET n = $properties "
    if set_labels:
        query += f"SET n{set_labels} "
    query += "RETURN count(n) AS count"
    result = tx.run(
        query,
        entity_id=change["entity_id"],
        properties=dict(before.get("properties", {})),
    )
    record = result.single()
    return int(record["count"] if record else 0)


def rollback_latest_triple_version(
    config: Neo4jConfig,
    *,
    history_path: str | Path = DEFAULT_VERSION_HISTORY_PATH,
) -> dict[str, Any]:
    history = _load_history(history_path)
    versions = list(history["versions"])
    if not versions:
        return {"rolled_back": False, "reason": "no version history"}

    record = deepcopy(versions[-1])
    write_summary = record.get("write_summary", {})
    relationship_changes = list(write_summary.get("relationship_changes", []))
    entity_changes = list(write_summary.get("entity_changes", []))

    graph_db = _import_driver()
    driver = graph_db.driver(config.uri, auth=(config.user, config.password))
    deleted_relationships = 0
    restored_relationships = 0
    deleted_nodes = 0
    restored_nodes = 0
    try:
        with driver.session(database=config.database) as session:
            tx = session.begin_transaction()
            try:
                for change in reversed(relationship_changes):
                    if change.get("created"):
                        deleted_relationships += _delete_relationship(tx, change)
                    else:
                        restored_relationships += _restore_relationship(tx, change)

                for change in reversed(entity_changes):
                    if change.get("created"):
                        deleted_nodes += _delete_node(tx, change)
                    else:
                        restored_nodes += _restore_node(tx, change)

                tx.commit()
            except Exception:
                tx.rollback()
                raise
    finally:
        driver.close()

    history["versions"] = versions[:-1]
    _save_history(history_path, history)
    return {
        "rolled_back": True,
        "version_id": record.get("version_id"),
        "created_at": record.get("created_at"),
        "deleted_relationships": deleted_relationships,
        "restored_relationships": restored_relationships,
        "deleted_nodes": deleted_nodes,
        "restored_nodes": restored_nodes,
        "remaining_versions": len(history["versions"]),
    }
