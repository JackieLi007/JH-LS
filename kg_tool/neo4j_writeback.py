from __future__ import annotations

from typing import Any

from kg_tool.models import Edge
from kg_tool.neo4j_graph import Neo4jConfig, _import_driver


SIMILAR_RELATION_MAP = {
    # 兼容历史输出和旧 Neo4j 关系；新的关系名称统一写为“相似”。
    "similar_to": {
        "neo4j_type": "相似",
        "zh": "相似",
    },
    "相似": {
        "neo4j_type": "相似",
        "zh": "相似",
    },
    "相似（SIMILAR_TO）": {
        "neo4j_type": "相似",
        "zh": "相似",
    },
    "merged_to": {
        "neo4j_type": "相似",
        "zh": "相似",
    },
    "融合": {
        "neo4j_type": "相似",
        "zh": "相似",
    },
    "融合（MERGED_TO）": {
        "neo4j_type": "相似",
        "zh": "相似",
    },
    "设备同义不同名（EQUIPMENT_SYNONYM_MERGED_TO）": {
        "neo4j_type": "相似",
        "zh": "相似",
    },
}


def _quote_relation_type(value: str) -> str:
    return f"`{value.replace('`', '``')}`"


def _write_similar_edges(
    session: Any,
    edges: list[Edge],
) -> tuple[int, dict[str, int]]:
    count = 0
    by_type: dict[str, int] = {}
    for edge in edges:
        relation_spec = SIMILAR_RELATION_MAP.get(edge.type)
        if relation_spec is None:
            continue
        relation_type = relation_spec["neo4j_type"]
        quoted_relation = _quote_relation_type(relation_type)
        session.run(
            "MATCH (a) WHERE elementId(a) = $source_id "
            "MATCH (b) WHERE elementId(b) = $target_id "
            f"MERGE (a)-[r:{quoted_relation}]->(b) "
            "SET r += $attributes, "
            "    r.updated_by = 'fkg_ml_linker', "
            "    r.name = $relation_name_zh, "
            "    r.name_zh = $relation_name_zh, "
            "    r.display_name = $relation_name_zh "
            "REMOVE r.relation_type_en",
            source_id=edge.source,
            target_id=edge.target,
            attributes=dict(edge.attributes),
            relation_name_zh=relation_spec["zh"],
        ).consume()
        count += 1
        by_type[relation_type] = by_type.get(relation_type, 0) + 1
    return count, by_type


def write_link_results_to_neo4j(
    config: Neo4jConfig,
    merge_edges: list[Edge],
    added_edges: list[Edge],
) -> dict[str, Any]:
    graph_db = _import_driver()
    driver = graph_db.driver(config.uri, auth=(config.user, config.password))
    merge_count = 0
    added_count = 0
    merge_by_type: dict[str, int] = {}
    added_by_type: dict[str, int] = {}
    try:
        with driver.session(database=config.database) as session:
            merge_count, merge_by_type = _write_similar_edges(session, merge_edges)
            added_count, added_by_type = _write_similar_edges(session, added_edges)
    finally:
        driver.close()
    return {
        "merge_relationships": merge_count,
        "merge_relationships_by_type": merge_by_type,
        "added_relationships": added_count,
        "added_relationships_by_type": added_by_type,
    }
