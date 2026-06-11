from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any


DEFAULT_CONFIG: dict[str, Any] = {
    'semanticRoles': {
        'entity': [
            '总体', '系统', '单机', '组件', '零部组件',
            'Machine', 'System', 'Component',
        ],
        'fault_mode': [
            '故障模式', '组件级故障模式', '单机级故障模式',
            '系统级故障模式', '总体级故障模式',
            'ComponentFailureMode', 'UnitFailureMode', 'SystemFailureMode', 'OverallFailureMode',
        ],
        'attribute': [
            '属性',
            '发生阶段', '发生概率', '严酷度等级', '是否单点',
            'Attribute', 'OccurrenceStage', 'ProbabilityLevel', 'SeverityLevel', 'SinglePoint',
        ],
        'attribute_value': ['属性值'],
        'phenomenon': [
            '故障现象', '组件级故障现象', '单机级故障现象',
            '系统级故障现象', '总体级故障现象',
        ],
        'measure': ['设计措施', 'DesignMeasure'],
        'function': ['功能', '单机功能', '系统功能', '总体功能', '零部组件功能', 'Function'],
    },
    'relationGroups': {
        'hierarchy': ['包含', 'INCLUDE', '功能', 'HAS_FUNCTION'],
        'fault_link': ['故障模式', 'HAS_FAILURE_MODE'],
        'attribute_link': [
            '有', 'HAS',
            '发生阶段', '发生概率', '严酷度等级', '是否单点',
            'OCCURRENCE_STAGE', 'PROBABILITY', 'LEVEL_CLASSIFICATION', 'YES_OR_NO',
        ],
        'causal_link': ['导致', 'LEADS_TO'],
        'measure_link': ['设计措施', 'SOLUTION'],
        'similarity': ['相似', 'SIMILAR'],
    },
    'allowedRelationGroups': [
        'hierarchy', 'fault_link', 'attribute_link', 'causal_link', 'measure_link',
    ],
    'expectedSemanticRoles': [
        'entity', 'fault_mode', 'attribute', 'attribute_value', 'phenomenon', 'measure',
    ],
    'semanticRoleWeights': {
        'fault_mode': 1.0,
        'phenomenon': 0.95,
        'entity': 0.9,
        'attribute_value': 0.78,
        'attribute': 0.74,
        'measure': 0.7,
        'function': 0.62,
        'other': 0.5,
    },
    'relationGroupWeights': {
        'fault_link': 1.0,
        'causal_link': 0.95,
        'attribute_link': 0.85,
        'measure_link': 0.8,
        'hierarchy': 0.65,
    },
    'limits': {
        'candidateTopK': 50,
        'expansionEntryLimit': 8,
        'maxDepth': 3,
        'maxEdgesPerNode': 20,
        'maxResultNodes': 120,
        'maxResultEdges': 180,
    },
}


ENV_LIMIT_KEYS = {
    'candidateTopK': 'FAULT_QUERY_CANDIDATE_TOP_K',
    'expansionEntryLimit': 'FAULT_QUERY_EXPANSION_ENTRY_LIMIT',
    'maxDepth': 'FAULT_QUERY_MAX_DEPTH',
    'maxEdgesPerNode': 'FAULT_QUERY_MAX_EDGES_PER_NODE',
    'maxResultNodes': 'FAULT_QUERY_MAX_RESULT_NODES',
    'maxResultEdges': 'FAULT_QUERY_MAX_RESULT_EDGES',
}


def merge_config(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_config(merged[key], value)
        else:
            merged[key] = value
    return merged


@lru_cache(maxsize=1)
def fault_query_config() -> dict[str, Any]:
    config = DEFAULT_CONFIG
    config_path = os.environ.get('FAULT_QUERY_CONFIG', '').strip()
    path = (
        Path(config_path).expanduser()
        if config_path
        else Path(__file__).resolve().with_name('fault_query_config.json')
    )
    if config_path or path.exists():
        if not path.is_absolute():
            path = Path(__file__).resolve().parent.parent / path
        if path.exists():
            payload = json.loads(path.read_text(encoding='utf-8-sig'))
            if isinstance(payload, dict):
                config = merge_config(DEFAULT_CONFIG, payload)

    config = merge_config({}, config)
    limits = dict(config.get('limits') or {})
    for key, env_key in ENV_LIMIT_KEYS.items():
        value = os.environ.get(env_key, '').strip()
        if value:
            limits[key] = max(1, int(value))
    config['limits'] = limits
    return config


def normalized_mapping_value(value: Any) -> str:
    return ''.join(str(value or '').strip().lower().split())


def match_mapping(values: list[Any], mapping: dict[str, list[str]], fallback: str) -> str:
    normalized_values = [normalized_mapping_value(value) for value in values if normalized_mapping_value(value)]
    for group, aliases in mapping.items():
        normalized_aliases = {normalized_mapping_value(alias) for alias in aliases}
        if any(value in normalized_aliases for value in normalized_values):
            return group

    best_match = fallback
    best_length = -1
    for group, aliases in mapping.items():
        for alias in aliases:
            normalized_alias = normalized_mapping_value(alias)
            if not normalized_alias:
                continue
            if any(normalized_alias in value for value in normalized_values) and len(normalized_alias) > best_length:
                best_match = group
                best_length = len(normalized_alias)
    return best_match


def semantic_role_for_node(node: dict[str, Any]) -> str:
    config = fault_query_config()
    return match_mapping(
        [
            node.get('semantic_role'),
            node.get('semanticRole'),
            node.get('level'),
            node.get('label'),
            node.get('status'),
            node.get('type'),
        ],
        config['semanticRoles'],
        'other',
    )


def relation_group_for_edge(edge: dict[str, Any]) -> str:
    config = fault_query_config()
    return match_mapping(
        [
            edge.get('relation_group'),
            edge.get('relationGroup'),
            edge.get('relationType'),
            edge.get('rawRelationType'),
            edge.get('label'),
        ],
        config['relationGroups'],
        'other',
    )
