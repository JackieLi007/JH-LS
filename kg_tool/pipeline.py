from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Any, Mapping

from kg_tool.models import Graph
from kg_tool.neo4j_graph import Neo4jConfig, load_graph_from_neo4j
from kg_tool.neo4j_writeback import write_link_results_to_neo4j
from kg_tool.triple_ingest import load_triple_payload, upsert_triples_to_neo4j
from kg_tool.versioning import (
    DEFAULT_MAX_VERSIONS,
    DEFAULT_VERSION_HISTORY_PATH,
    record_triple_version,
    rollback_latest_triple_version,
)


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


def ingest_triples_link_and_index(
    payload: str | Path | Mapping[str, Any],
    neo4j_config: Neo4jConfig,
    artifact_dir: str | Path,
    *,
    ml_config: Any | None = None,
    index_config: Any | None = None,
    write_link_results: bool = True,
    focus_only: bool = True,
    output_graph: str | Path | None = None,
    report_path: str | Path | None = None,
    record_version: bool = True,
    version_history_path: str | Path = DEFAULT_VERSION_HISTORY_PATH,
    max_versions: int = DEFAULT_MAX_VERSIONS,
) -> dict[str, Any]:
    """Incrementally ingest triples, run knowledge linking, and rebuild the local index."""
    write_summary = upsert_triples_to_neo4j(neo4j_config, payload)

    summary: dict[str, Any] = {"write": write_summary}
    try:
        from kg_tool.indexing import build_semantic_index
        from kg_tool.ml_linking import connect_graph_with_ml

        graph = load_graph_from_neo4j(neo4j_config)
        focus_node_ids = set(write_summary["touched_node_ids"]) if focus_only else None
        link_result = connect_graph_with_ml(graph, config=ml_config, focus_node_ids=focus_node_ids)

        writeback = None
        if write_link_results:
            writeback = write_link_results_to_neo4j(
                neo4j_config,
                merge_edges=link_result.merge_edges,
                added_edges=link_result.added_edges,
            )
            write_summary["link_relationship_changes"] = writeback.get("relationship_changes", [])
            write_summary["link_writeback"] = {
                key: value for key, value in writeback.items() if key != "relationship_changes"
            }

        if output_graph:
            link_result.merged_graph.save(output_graph)

        index_artifacts = build_semantic_index(link_result.merged_graph, artifact_dir=artifact_dir, config=index_config)
        summary["linking"] = _link_summary(graph, link_result, writeback)
        summary["index"] = {
            **asdict(index_artifacts),
            "node_count": len(index_artifacts.node_order),
        }
    except Exception as exc:
        summary["postprocess"] = {
            "status": "skipped",
            "error": str(exc),
        }

    if record_version:
        version_record = record_triple_version(
            load_triple_payload(payload),
            write_summary,
            history_path=version_history_path,
            max_versions=max_versions,
        )
        write_summary["version"] = {
            "version_id": version_record["version_id"],
            "history_path": str(version_history_path),
        }

    if report_path:
        output = Path(report_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    return summary


def rollback_latest_version_and_reindex(
    neo4j_config: Neo4jConfig,
    *,
    artifact_dir: str | Path | None = None,
    index_config: Any | None = None,
    version_history_path: str | Path = DEFAULT_VERSION_HISTORY_PATH,
    output_graph: str | Path | None = None,
    report_path: str | Path | None = None,
) -> dict[str, Any]:
    rollback_summary = rollback_latest_triple_version(neo4j_config, history_path=version_history_path)
    summary: dict[str, Any] = {"rollback": rollback_summary}

    if artifact_dir or output_graph:
        graph = load_graph_from_neo4j(neo4j_config)
        if output_graph:
            graph.save(output_graph)
        if artifact_dir:
            try:
                from kg_tool.indexing import build_semantic_index

                index_artifacts = build_semantic_index(graph, artifact_dir=artifact_dir, config=index_config)
                summary["index"] = {
                    **asdict(index_artifacts),
                    "node_count": len(index_artifacts.node_order),
                }
            except Exception as exc:
                summary["postprocess"] = {
                    "status": "skipped",
                    "error": str(exc),
                }

    if report_path:
        output = Path(report_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    return summary
