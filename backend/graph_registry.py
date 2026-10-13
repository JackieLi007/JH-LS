"""Registry and lifecycle helpers for multiple Neo4j knowledge graphs.

Each product model is stored in a separate Neo4j database.  The registry keeps
the user-facing graph name, the database name and lifecycle metadata outside of
Neo4j so that an existing single-database deployment can be adopted without a
migration.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

from flask import g, has_request_context, request
from neo4j import GraphDatabase


PROJECT_ROOT = Path(__file__).resolve().parent.parent
GRAPH_ARTIFACT_ROOT = PROJECT_ROOT / "artifacts" / "kg_graphs"
GRAPH_REGISTRY_PATH = GRAPH_ARTIFACT_ROOT / "registry.json"
DATABASE_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,62}$")


class GraphRegistryError(ValueError):
    """Raised when a graph selection or graph registration is invalid."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _neo4j_uri() -> str:
    return os.environ.get("KG_NEO4J_URI") or os.environ.get("NEO4J_URI") or "bolt://127.0.0.1:7687"


def _neo4j_user() -> str:
    return os.environ.get("KG_NEO4J_USER") or os.environ.get("NEO4J_USERNAME") or "neo4j"


def _neo4j_password() -> str:
    return os.environ.get("KG_NEO4J_PASSWORD") or os.environ.get("NEO4J_PASSWORD") or "123456789"


def configured_default_database() -> str:
    """Return the legacy database so existing deployments remain available."""
    database = os.environ.get("KG_NEO4J_DATABASE") or os.environ.get("NEO4J_DATABASE") or "neo4j"
    return validate_database_name(database)


def validate_database_name(value: object) -> str:
    database = str(value or "").strip()
    if not DATABASE_NAME_RE.fullmatch(database):
        raise GraphRegistryError(
            "图谱数据库名称只能包含字母、数字、点、下划线和连字符，且必须以字母开头。"
        )
    return database


def _quote_identifier(value: str) -> str:
    return f"`{value.replace('`', '``')}`"


def _safe_graph_record(item: Mapping[str, Any]) -> dict[str, Any] | None:
    try:
        database = validate_database_name(item.get("database"))
    except GraphRegistryError:
        return None
    name = str(item.get("name") or "").strip() or database
    return {
        "database": database,
        "name": name,
        "description": str(item.get("description") or "").strip(),
        "createdAt": str(item.get("createdAt") or _utc_now()),
        "updatedAt": str(item.get("updatedAt") or item.get("createdAt") or _utc_now()),
        "isDefault": bool(item.get("isDefault")),
    }


def _default_registry() -> dict[str, Any]:
    database = configured_default_database()
    now = _utc_now()
    return {
        "schemaVersion": 1,
        "graphs": [{
            "database": database,
            "name": "默认图谱",
            "description": "系统原有知识图谱",
            "createdAt": now,
            "updatedAt": now,
            "isDefault": True,
        }],
    }


def _load_registry() -> dict[str, Any]:
    if not GRAPH_REGISTRY_PATH.exists():
        return _default_registry()
    try:
        raw = json.loads(GRAPH_REGISTRY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GraphRegistryError(f"图谱登记文件无法读取：{exc}") from exc
    if not isinstance(raw, Mapping):
        raise GraphRegistryError("图谱登记文件格式无效。")

    records: list[dict[str, Any]] = []
    used_databases: set[str] = set()
    for item in raw.get("graphs", []):
        if not isinstance(item, Mapping):
            continue
        record = _safe_graph_record(item)
        if record and record["database"] not in used_databases:
            records.append(record)
            used_databases.add(record["database"])
    if not records:
        return _default_registry()
    if not any(record["isDefault"] for record in records):
        records[0]["isDefault"] = True
    return {"schemaVersion": 1, "graphs": records}


def _save_registry(registry: Mapping[str, Any]) -> None:
    GRAPH_ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    GRAPH_REGISTRY_PATH.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def graph_artifact_dir(database: str) -> Path:
    return GRAPH_ARTIFACT_ROOT / validate_database_name(database)


def graph_version_history_path(database: str) -> Path:
    return graph_artifact_dir(database) / "versions" / "history.json"


def graph_index_dir(database: str) -> Path:
    return graph_artifact_dir(database) / "neo4j_index"


def graph_report_dir(database: str) -> Path:
    return graph_artifact_dir(database) / "kg_build_reports"


def list_registered_graphs() -> list[dict[str, Any]]:
    return [dict(item) for item in _load_registry()["graphs"]]


def default_graph() -> dict[str, Any]:
    graphs = list_registered_graphs()
    return next((item for item in graphs if item.get("isDefault")), graphs[0])


def find_graph(database: object | None) -> dict[str, Any]:
    selected = validate_database_name(database or configured_default_database())
    for graph in list_registered_graphs():
        if graph["database"] == selected:
            return graph
    raise GraphRegistryError("指定图谱不存在，请先在图谱构建页面创建或选择已登记图谱。")


def request_graph_database() -> str:
    """Get the request-selected graph database, falling back to the default."""
    if has_request_context():
        selected = getattr(g, "knowledge_graph_database", None)
        if selected:
            return str(selected)
    return default_graph()["database"]


def _request_graph_reference() -> str:
    header_value = request.headers.get("X-KG-Database", "").strip()
    query_value = request.args.get("graph", "").strip()
    if header_value:
        return header_value
    if query_value:
        return query_value
    if request.is_json:
        payload = request.get_json(silent=True) or {}
        if isinstance(payload, Mapping):
            return str(payload.get("graphDatabase") or payload.get("graph") or "").strip()
    if request.content_type and "multipart/form-data" in request.content_type:
        return str(request.form.get("graphDatabase") or request.form.get("graph") or "").strip()
    return ""


def select_request_graph() -> dict[str, Any]:
    """Resolve and record the active graph for the current Flask request."""
    selected = _request_graph_reference()
    graph = find_graph(selected or default_graph()["database"])
    g.knowledge_graph_database = graph["database"]
    g.knowledge_graph = graph
    return graph


def _database_name_from_display_name(name: str, existing: set[str]) -> str:
    ascii_stem = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not ascii_stem:
        ascii_stem = "model"
    ascii_stem = ascii_stem[:38]
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]
    base = f"kg-{ascii_stem}-{digest}"
    candidate = base
    suffix = 2
    while candidate in existing:
        candidate = f"{base[:58]}-{suffix}"
        suffix += 1
    return validate_database_name(candidate)


def create_registered_graph(name: object, description: object = "") -> dict[str, Any]:
    graph_name = str(name or "").strip()
    if not graph_name:
        raise GraphRegistryError("请填写图谱名称。")
    if len(graph_name) > 80:
        raise GraphRegistryError("图谱名称不能超过 80 个字符。")

    registry = _load_registry()
    graphs = registry["graphs"]
    if any(str(item["name"]).casefold() == graph_name.casefold() for item in graphs):
        raise GraphRegistryError("同名图谱已存在，请直接选择该图谱。")

    database = _database_name_from_display_name(graph_name, {item["database"] for item in graphs})
    try:
        driver = GraphDatabase.driver(_neo4j_uri(), auth=(_neo4j_user(), _neo4j_password()))
        try:
            with driver.session(database="system") as session:
                session.run(f"CREATE DATABASE {_quote_identifier(database)} IF NOT EXISTS WAIT").consume()
        finally:
            driver.close()
    except Exception as exc:
        raise GraphRegistryError(
            "无法创建 Neo4j 数据库。请确认 Neo4j Desktop 已启动、当前账号具备创建数据库权限，"
            f"并支持多数据库功能。详情：{exc}"
        ) from exc

    now = _utc_now()
    graph = {
        "database": database,
        "name": graph_name,
        "description": str(description or "").strip(),
        "createdAt": now,
        "updatedAt": now,
        "isDefault": False,
    }
    registry["graphs"] = [*graphs, graph]
    _save_registry(registry)
    return dict(graph)


def delete_registered_graph(database: object) -> dict[str, Any]:
    """Drop one user-created Neo4j database and its graph-local artifacts."""
    import shutil

    target = find_graph(database)
    if target.get("isDefault"):
        raise GraphRegistryError("默认图谱承载原有知识，不能在此处删除。")

    database_name = target["database"]
    try:
        driver = GraphDatabase.driver(_neo4j_uri(), auth=(_neo4j_user(), _neo4j_password()))
        try:
            with driver.session(database="system") as session:
                session.run(f"DROP DATABASE {_quote_identifier(database_name)} IF EXISTS WAIT").consume()
        finally:
            driver.close()
    except Exception as exc:
        raise GraphRegistryError(f"无法删除 Neo4j 图谱数据库：{exc}") from exc

    # The target is based on a strictly validated database identifier and is
    # therefore always a direct child of the dedicated graph-artifact folder.
    artifact_dir = graph_artifact_dir(database_name)
    if artifact_dir.exists():
        shutil.rmtree(artifact_dir)

    registry = _load_registry()
    registry["graphs"] = [item for item in registry["graphs"] if item["database"] != database_name]
    _save_registry(registry)
    return dict(target)


def touch_graph(database: str) -> None:
    registry = _load_registry()
    touched = False
    for graph in registry["graphs"]:
        if graph["database"] == database:
            graph["updatedAt"] = _utc_now()
            touched = True
            break
    if touched:
        _save_registry(registry)


def _version_overview(database: str) -> tuple[int, str]:
    history_path = graph_version_history_path(database)
    if not history_path.exists():
        return 0, ""
    try:
        history = json.loads(history_path.read_text(encoding="utf-8"))
        versions = history.get("versions", []) if isinstance(history, Mapping) else []
        latest = versions[-1] if versions and isinstance(versions[-1], Mapping) else {}
        return len(versions), str(latest.get("created_at") or "")
    except (OSError, json.JSONDecodeError):
        return 0, ""


def graph_summary(graph: Mapping[str, Any]) -> dict[str, Any]:
    """Return registry data plus lightweight information from its Neo4j DB."""
    result = dict(graph)
    database = validate_database_name(result["database"])
    version_count, latest_version_at = _version_overview(database)
    result.update({
        "id": database,
        "versionCount": version_count,
        "latestVersionAt": latest_version_at,
        "nodeCount": 0,
        "edgeCount": 0,
        "relationTypeCount": 0,
        "available": False,
        "error": "",
    })
    try:
        driver = GraphDatabase.driver(_neo4j_uri(), auth=(_neo4j_user(), _neo4j_password()))
        try:
            with driver.session(database=database) as session:
                result["nodeCount"] = int(session.run("MATCH (n) RETURN count(n) AS count").single()["count"])
                result["edgeCount"] = int(session.run("MATCH ()-[r]->() RETURN count(r) AS count").single()["count"])
                result["relationTypeCount"] = int(
                    session.run("MATCH ()-[r]->() RETURN count(DISTINCT type(r)) AS count").single()["count"]
                )
            result["available"] = True
        finally:
            driver.close()
    except Exception as exc:
        result["error"] = str(exc)
    return result


def list_graph_summaries() -> list[dict[str, Any]]:
    return [graph_summary(graph) for graph in list_registered_graphs()]
