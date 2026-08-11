from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

from backend.graph_registry import (
    graph_index_dir,
    graph_report_dir,
    graph_version_history_path,
    request_graph_database,
    touch_graph,
    validate_database_name,
)
from kg_tool.neo4j_graph import Neo4jConfig
from kg_tool.versioning import DEFAULT_MAX_VERSIONS, DEFAULT_VERSION_HISTORY_PATH, list_triple_versions


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ARTIFACT_DIR = PROJECT_ROOT / 'artifacts' / 'neo4j_index'
DEFAULT_REPORT_DIR = PROJECT_ROOT / 'artifacts' / 'kg_build_reports'
ATTRIBUTE_TYPES = {'属性值', '属性', 'Attribute', 'ATTRIBUTE'}
ATTRIBUTE_RELATION_NAMES = {'发生阶段', '是否单点', '严酷度等级', '发生概率', '设计措施'}


def _env_bool(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {'0', 'false', 'no', 'off', '否'}


def kg_auto_build_enabled() -> bool:
    return _env_bool('KG_AUTO_BUILD', False)


def get_neo4j_config(
    overrides: Mapping[str, Any] | None = None,
    *,
    database: str | None = None,
) -> Neo4jConfig:
    overrides = overrides or {}
    requested_database = database or overrides.get('database') or os.environ.get('KG_NEO4J_DATABASE') or os.environ.get('NEO4J_DATABASE') or 'neo4j'
    return Neo4jConfig(
        uri=str(overrides.get('uri') or os.environ.get('KG_NEO4J_URI') or os.environ.get('NEO4J_URI') or 'bolt://127.0.0.1:7687'),
        user=str(overrides.get('user') or os.environ.get('KG_NEO4J_USER') or os.environ.get('NEO4J_USERNAME') or 'neo4j'),
        password=str(overrides.get('password') or os.environ.get('KG_NEO4J_PASSWORD') or os.environ.get('NEO4J_PASSWORD') or '123456789'),
        database=validate_database_name(requested_database),
    )


def _stable_id(prefix: str, *parts: object) -> str:
    raw = '\n'.join(str(part or '').strip() for part in parts)
    digest = hashlib.sha1(raw.encode('utf-8')).hexdigest()[:16]
    return f'{prefix}_{digest}'


def _append_property(properties: dict[str, Any], key: str, value: str) -> None:
    prop_name = str(key or '').strip()
    text = str(value or '').strip()
    if not prop_name or not text:
        return
    existing = properties.get(prop_name)
    if existing is None:
        properties[prop_name] = text
    elif isinstance(existing, list):
        if text not in existing:
            existing.append(text)
    elif existing != text:
        properties[prop_name] = [existing, text]


def _is_canonical_triple_payload(payload: Mapping[str, Any]) -> bool:
    triples = payload.get('triples')
    return (
        isinstance(payload.get('entities'), list)
        and isinstance(payload.get('relations'), list)
        and isinstance(triples, list)
        and all(isinstance(item, Mapping) and 'subject_id' in item for item in triples)
    )


def _safe_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def normalize_extraction_result_to_triple_payload(extraction_result: Mapping[str, Any]) -> dict[str, Any]:
    """Convert frontend/backend extraction output into the canonical KG pipeline payload."""
    if _is_canonical_triple_payload(extraction_result):
        return {
            **dict(extraction_result),
            'generatedAt': extraction_result.get('generatedAt') or datetime.now().isoformat(timespec='seconds'),
        }

    legacy_triples = extraction_result.get('triples')
    legacy_entities = extraction_result.get('entities')
    if isinstance(legacy_entities, list) and isinstance(legacy_triples, list) and legacy_triples:
        first_triple = legacy_triples[0]
        if isinstance(first_triple, Mapping) and {'subject', 'predicate', 'object'}.issubset(first_triple.keys()):
            entity_by_id = {
                str(item.get('id') or '').strip(): dict(item)
                for item in legacy_entities
                if isinstance(item, Mapping) and str(item.get('id') or '').strip()
            }
            relations: dict[tuple[str, str, str], dict[str, Any]] = {}
            triples: list[dict[str, Any]] = []
            for index, row in enumerate(legacy_triples):
                if not isinstance(row, Mapping):
                    continue
                subject_id = str(row.get('subject') or '').strip()
                predicate = str(row.get('predicate') or '').strip()
                object_id = str(row.get('object') or '').strip()
                subject = entity_by_id.get(subject_id)
                obj = entity_by_id.get(object_id)
                if not subject or not obj or not predicate:
                    continue
                subject_type = str(subject.get('type') or '').strip()
                object_type = str(obj.get('type') or '').strip()
                relation_key = (predicate, subject_type, object_type)
                if relation_key not in relations:
                    relations[relation_key] = {
                        'id': _stable_id('R', *relation_key),
                        'name': predicate,
                        'subject_type': subject_type,
                        'object_type': object_type,
                    }
                relation_id = relations[relation_key]['id']
                triples.append(
                    {
                        'id': str(row.get('id') or '') or _stable_id('T', subject_id, relation_id, object_id, index),
                        'subject_id': subject_id,
                        'predicate_id': relation_id,
                        'object_id': object_id,
                        'properties': _safe_mapping(row.get('properties') or row.get('attributes') or {}),
                    }
                )
            return {
                **{key: value for key, value in dict(extraction_result).items() if key not in {'relations', 'triples'}},
                'generatedAt': extraction_result.get('generatedAt') or datetime.now().isoformat(timespec='seconds'),
                'entities': [
                    {
                        **dict(item),
                        'properties': _safe_mapping(item.get('properties') or item.get('attributes') or {}),
                    }
                    for item in legacy_entities
                    if isinstance(item, Mapping)
                ],
                'relations': list(relations.values()),
                'triples': triples,
            }

    triple_rows = extraction_result.get('tripleRows')
    if not isinstance(triple_rows, list):
        raise ValueError('抽取结果中没有可导入的 tripleRows。')

    file_name = str(extraction_result.get('fileName') or '').strip()
    source_type = str(extraction_result.get('sourceType') or '').strip()
    entity_index: dict[tuple[str, str], dict[str, Any]] = {}
    relation_index: dict[tuple[str, str, str], dict[str, Any]] = {}
    triples: list[dict[str, Any]] = []
    seen_triples: set[tuple[str, str, str]] = set()
    skipped_rows = 0

    def ensure_entity(name: str, entity_type: str, scope: str = '') -> str:
        clean_name = str(name or '').strip()
        clean_type = str(entity_type or '').strip() or '未知类型'
        if not clean_name:
            return ''
        clean_scope = str(scope or '').strip()
        key = (clean_type, clean_name, clean_scope)
        if key not in entity_index:
            entity_index[key] = {
                'id': _stable_id('E', clean_type, clean_name, clean_scope),
                'name': clean_name,
                'type': clean_type,
                'properties': {
                    'source_file': file_name,
                    'source_type': source_type,
                },
            }
        return str(entity_index[key]['id'])

    def ensure_relation(name: str, subject_type: str, object_type: str) -> str:
        clean_name = str(name or '').strip()
        clean_subject_type = str(subject_type or '').strip() or '未知类型'
        clean_object_type = str(object_type or '').strip() or '未知类型'
        if not clean_name:
            return ''
        key = (clean_name, clean_subject_type, clean_object_type)
        if key not in relation_index:
            relation_index[key] = {
                'id': _stable_id('R', clean_name, clean_subject_type, clean_object_type),
                'name': clean_name,
                'subject_type': clean_subject_type,
                'object_type': clean_object_type,
                'properties': {
                    'source_file': file_name,
                    'source_type': source_type,
                },
            }
        return str(relation_index[key]['id'])

    attribute_groups: dict[tuple[str, str, str, str], list[str]] = {}
    normal_rows: list[tuple[str, str, str, str, str]] = []

    for row in triple_rows:
        if not isinstance(row, Mapping):
            skipped_rows += 1
            continue
        subject = str(row.get('subject') or '').strip()
        predicate = str(row.get('predicate') or '').strip()
        obj = str(row.get('object') or '').strip()
        subject_type = str(row.get('subjectType') or row.get('subject_type') or '').strip()
        object_type = str(row.get('objectType') or row.get('object_type') or '').strip()
        if not subject or not predicate or not obj:
            skipped_rows += 1
            continue

        if object_type in ATTRIBUTE_TYPES or predicate in ATTRIBUTE_RELATION_NAMES or object_type in ATTRIBUTE_RELATION_NAMES:
            grouped_type = object_type if object_type not in ATTRIBUTE_TYPES else predicate
            grouped_type = grouped_type if grouped_type in ATTRIBUTE_RELATION_NAMES else object_type
            group_key = (subject_type, subject, predicate, grouped_type)
            values = attribute_groups.setdefault(group_key, [])
            if obj not in values:
                values.append(obj)
            continue

        normal_rows.append((subject, subject_type, predicate, obj, object_type))

    for subject, subject_type, predicate, obj, object_type in normal_rows:
        subject_id = ensure_entity(subject, subject_type)
        object_id = ensure_entity(obj, object_type)
        relation_id = ensure_relation(predicate, subject_type, object_type)
        triple_key = (subject_id, relation_id, object_id)
        if not subject_id or not object_id or not relation_id or triple_key in seen_triples:
            continue
        seen_triples.add(triple_key)
        triples.append(
            {
                'id': _stable_id('T', *triple_key),
                'subject_id': subject_id,
                'predicate_id': relation_id,
                'object_id': object_id,
                'properties': {
                    'source_file': file_name,
                    'source_type': source_type,
                },
            }
        )

    for (subject_type, subject, predicate, object_type), values in attribute_groups.items():
        clean_values = [value for value in values if value]
        if not clean_values:
            continue
        obj = ' / '.join(clean_values)
        scope = f'{subject_type}:{subject}:{predicate}'
        subject_id = ensure_entity(subject, subject_type)
        object_id = ensure_entity(obj, object_type, scope=scope)
        relation_id = ensure_relation(predicate, subject_type, object_type)
        triple_key = (subject_id, relation_id, object_id)
        if not subject_id or not object_id or not relation_id or triple_key in seen_triples:
            continue
        seen_triples.add(triple_key)
        triples.append(
            {
                'id': _stable_id('T', *triple_key),
                'subject_id': subject_id,
                'predicate_id': relation_id,
                'object_id': object_id,
                'properties': {
                    'source_file': file_name,
                    'source_type': source_type,
                },
            }
        )

    payload = {
        'fileName': file_name,
        'sourceType': source_type,
        'generatedAt': datetime.now().isoformat(timespec='seconds'),
        'entities': list(entity_index.values()),
        'relations': list(relation_index.values()),
        'triples': triples,
        'metadata': {
            'source': 'backend_extraction',
            'input_triple_rows': len(triple_rows),
            'skipped_rows': skipped_rows,
        },
    }
    return payload


def _safe_file_stem(file_name: str) -> str:
    stem = Path(file_name or 'kg_build').stem.strip() or 'kg_build'
    safe = []
    for ch in stem:
        if ch.isalnum() or ch in {'-', '_'} or '\u4e00' <= ch <= '\u9fff':
            safe.append(ch)
        else:
            safe.append('_')
    return ''.join(safe).strip('_') or 'kg_build'


def _compact_pipeline_summary(summary: Mapping[str, Any]) -> dict[str, Any]:
    write = summary.get('write') if isinstance(summary.get('write'), Mapping) else {}
    linking = summary.get('linking') if isinstance(summary.get('linking'), Mapping) else {}
    index = summary.get('index') if isinstance(summary.get('index'), Mapping) else {}
    postprocess = summary.get('postprocess') if isinstance(summary.get('postprocess'), Mapping) else {}
    writeback = linking.get('writeback') if isinstance(linking.get('writeback'), Mapping) else {}
    return {
        'write': {
            'input_entities': write.get('input_entities', 0),
            'input_relations': write.get('input_relations', 0),
            'input_triples': write.get('input_triples', 0),
            'created_nodes': write.get('created_nodes', 0),
            'matched_nodes': write.get('matched_nodes', 0),
            'created_relationships': write.get('created_relationships', 0),
            'matched_relationships': write.get('matched_relationships', 0),
            'version': write.get('version'),
            'warnings': write.get('warnings', []),
        },
        'linking': {
            'input_nodes': linking.get('input_nodes', 0),
            'output_nodes': linking.get('output_nodes', 0),
            'input_edges': linking.get('input_edges', 0),
            'output_edges': linking.get('output_edges', 0),
            'merge_edge_count': linking.get('merge_edge_count', 0),
            'added_edge_count': linking.get('added_edge_count', 0),
            'writeback': writeback,
        },
        'index': {
            'node_count': index.get('node_count', 0),
            'artifact_dir': index.get('artifact_dir'),
        },
        'postprocess': {
            'status': postprocess.get('status'),
            'error': postprocess.get('error'),
        } if postprocess else None,
    }


def build_kg_from_extraction_result(
    extraction_result: Mapping[str, Any],
    *,
    neo4j_overrides: Mapping[str, Any] | None = None,
    artifact_dir: str | Path | None = None,
    report_dir: str | Path | None = None,
    record_version: bool = True,
    graph_database: str | None = None,
) -> dict[str, Any]:
    payload = normalize_extraction_result_to_triple_payload(extraction_result)
    if not payload.get('triples') and not payload.get('entities'):
        return {
            'status': 'skipped',
            'reason': '没有可写入知识图谱的节点或关系。',
            'payloadCounts': {'entities': 0, 'relations': 0, 'triples': 0},
        }

    from kg_tool.pipeline import ingest_triples_link_and_index

    database = validate_database_name(graph_database or request_graph_database())
    # Keep non-Neo4j artifacts segregated as well: a version rollback or an
    # embedding rebuild for one product model must never affect another one.
    target_artifact_dir = Path(artifact_dir or graph_index_dir(database))
    target_report_dir = Path(report_dir or graph_report_dir(database))
    target_report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    report_path = target_report_dir / f'{_safe_file_stem(str(payload.get("fileName") or ""))}_{timestamp}.json'

    summary = ingest_triples_link_and_index(
        payload,
        neo4j_config=get_neo4j_config(neo4j_overrides, database=database),
        artifact_dir=target_artifact_dir,
        report_path=report_path,
        record_version=record_version,
        version_history_path=graph_version_history_path(database),
        max_versions=DEFAULT_MAX_VERSIONS,
    )
    touch_graph(database)
    return {
        'status': 'ok',
        'graphDatabase': database,
        'reportPath': str(report_path.relative_to(PROJECT_ROOT)).replace('\\', '/'),
        'payloadCounts': {
            'entities': len(payload.get('entities', [])),
            'relations': len(payload.get('relations', [])),
            'triples': len(payload.get('triples', [])),
        },
        'summary': _compact_pipeline_summary(summary),
    }


def build_kg_from_extraction_result_safe(
    extraction_result: Mapping[str, Any],
    **kwargs: Any,
) -> dict[str, Any]:
    try:
        return build_kg_from_extraction_result(extraction_result, **kwargs)
    except Exception as exc:
        try:
            payload_counts = _payload_counts(normalize_extraction_result_to_triple_payload(extraction_result))
        except Exception:
            payload_counts = {'entities': 0, 'relations': 0, 'triples': 0}
        return {
            'status': 'failed',
            'error': str(exc),
            'payloadCounts': payload_counts,
        }


def _payload_counts(payload: Any) -> dict[str, int]:
    if not isinstance(payload, Mapping):
        return {'entities': 0, 'relations': 0, 'triples': 0}
    return {
        'entities': len(payload.get('entities', []) if isinstance(payload.get('entities'), list) else []),
        'relations': len(payload.get('relations', []) if isinstance(payload.get('relations'), list) else []),
        'triples': len(payload.get('triples', []) if isinstance(payload.get('triples'), list) else []),
    }


def _version_record_summary(record: Mapping[str, Any]) -> dict[str, Any]:
    payload = record.get('payload') if isinstance(record.get('payload'), Mapping) else {}
    write_summary = record.get('write_summary') if isinstance(record.get('write_summary'), Mapping) else {}
    return {
        'versionId': record.get('version_id', ''),
        'createdAt': record.get('created_at', ''),
        'fileName': payload.get('fileName') or payload.get('file_name') or '未命名数据',
        'sourceType': payload.get('sourceType') or payload.get('source_type') or '',
        'counts': _payload_counts(payload),
        'write': {
            'createdNodes': write_summary.get('created_nodes', 0),
            'matchedNodes': write_summary.get('matched_nodes', 0),
            'createdRelationships': write_summary.get('created_relationships', 0),
            'matchedRelationships': write_summary.get('matched_relationships', 0),
            'warnings': write_summary.get('warnings', []),
        },
    }


def list_kg_versions(
    limit: int = DEFAULT_MAX_VERSIONS,
    *,
    graph_database: str | None = None,
) -> dict[str, Any]:
    database = validate_database_name(graph_database or request_graph_database())
    versions = list_triple_versions(history_path=graph_version_history_path(database))
    limited = list(reversed(versions))[:limit]
    return {
        'status': 'ok',
        'graphDatabase': database,
        'limit': limit,
        'versions': [_version_record_summary(record) for record in limited if isinstance(record, Mapping)],
    }


def rollback_latest_kg_version(*, graph_database: str | None = None) -> dict[str, Any]:
    from kg_tool.pipeline import rollback_latest_version_and_reindex

    database = validate_database_name(graph_database or request_graph_database())
    summary = rollback_latest_version_and_reindex(
        get_neo4j_config(database=database),
        artifact_dir=graph_index_dir(database),
        version_history_path=graph_version_history_path(database),
    )
    if summary.get('rollback', {}).get('rolled_back'):
        touch_graph(database)
    return {
        'status': 'ok',
        'graphDatabase': database,
        'summary': json.loads(json.dumps(summary, ensure_ascii=False, default=str)),
        'history': list_kg_versions(graph_database=database),
    }
