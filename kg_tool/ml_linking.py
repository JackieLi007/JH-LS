from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import re
from typing import Any

import numpy as np

from kg_tool.graphsage import GraphSAGEConfig, train_graphsage_embeddings
from kg_tool.ml_text import build_node_texts, get_bert_text_encoder
from kg_tool.models import Edge, Graph, Node


SIMILAR_RELATION = "相似"
MERGE_RELATION = SIMILAR_RELATION
RELATION_TYPE_ALIASES = {
    # 兼容历史输出和旧 Neo4j 关系；新的关系名称统一写为“相似”。
    "similar_to": SIMILAR_RELATION,
    "相似（SIMILAR_TO）": SIMILAR_RELATION,
    "merged_to": SIMILAR_RELATION,
    "融合": SIMILAR_RELATION,
    "融合（MERGED_TO）": SIMILAR_RELATION,
    "设备同义不同名（EQUIPMENT_SYNONYM_MERGED_TO）": SIMILAR_RELATION,
}

TYPE_ROLE_KEYS = (
    "ontology_role",
    "semantic_role",
    "node_role",
    "entity_role",
    "type_role",
    "category",
    "node_category",
    "entity_category",
    "本体角色",
    "语义角色",
    "节点角色",
    "实体角色",
    "类型角色",
    "类别",
)
EQUIPMENT_ROLE_KEYWORDS = (
    "equipment",
    "device",
    "component",
    "system",
    "subsystem",
    "part",
    "module",
    "assembly",
    "设备",
    "单机",
    "系统",
    "子系统",
    "组件",
    "部件",
    "阀",
    "管",
    "泵",
    "传感器",
    "发动机",
    "电机",
    "机构",
    "装置",
    "模块",
)
FAULT_MODE_ROLE_KEYWORDS = (
    "fault",
    "failure",
    "failuremode",
    "failure_mode",
    "faultmode",
    "fault_mode",
    "故障",
    "故障模式",
    "故障类型",
    "失效",
    "异常",
)
FUNCTION_ROLE_KEYWORDS = ("function", "功能", "作用")
MODEL_TOKEN_PATTERN = re.compile(r"[A-Za-z]+(?:[-_]?[A-Za-z0-9]+)*\d+(?:[-_]?[A-Za-z0-9]+)*")
EQUIPMENT_VARIANT_GROUPS = {
    "medium": ("液氧", "液氢", "氧", "氢"),
    "position": ("内管", "外管", "左", "右", "前", "后", "上", "下", "内", "外"),
    "role": ("主", "备"),
}
EQUIPMENT_VARIANT_TERMS = tuple(dict.fromkeys(term for terms in EQUIPMENT_VARIANT_GROUPS.values() for term in terms))
IGNORED_SIMILARITY_ATTRIBUTE_KEYS = {"id"}
SYSTEM_HINT_KEYS = ("system", "owner", "所属系统", "上层系统")
EXCLUDED_LINK_NODE_TYPES = ("发生概率", "发生阶段", "严酷度等级", "是否单点")
EXCLUDED_LINK_NODE_TYPE_KEYS = (
    "type",
    "node_type",
    "entity_type",
    "category",
    "level",
    "name_zh",
    "display_name",
)
CROSS_LEVEL_EQUIPMENT_TYPE_ALIASES = {
    "零部组件": "零部组件",
    "组件": "零部组件",
    "component": "零部组件",
    "单机": "单机",
    "machine": "单机",
    "系统": "系统",
    "system": "系统",
}
CROSS_LEVEL_FAULT_MODE_TYPE_ALIASES = {
    "组件级故障模式": "组件级故障模式",
    "componentfailuremode": "组件级故障模式",
    "单机级故障模式": "单机级故障模式",
    "unitfailuremode": "单机级故障模式",
    "系统级故障模式": "系统级故障模式",
    "systemfailuremode": "系统级故障模式",
    "总体级故障模式": "总体级故障模式",
    "overallfailuremode": "总体级故障模式",
}




@dataclass
class TypeProfile:
    node_type: str
    role: str
    count: int
    property_keys: set[str]


@dataclass
class GraphFeatureCache:
    index_map: dict[str, int]
    type_groups: dict[str, list[str]]
    neighbor_types: dict[str, set[str]]
    edge_types: dict[str, set[str]]
    type_profiles: dict[str, TypeProfile]
    node_roles: dict[str, str]
    function_texts: dict[str, str]
    phenomenon_texts: dict[str, str]
    normalized_names: dict[str, str]
    model_tokens: dict[str, set[str]]
    equipment_variant_features: dict[str, dict[str, str]]
    equipment_name_cores: dict[str, str]
    similar_pairs: set[tuple[str, str]]
    similar_neighbors: dict[str, set[str]]
    skip_link_node_ids: set[str]
    cross_level_equipment_groups: dict[str, list[str]]
    cross_level_fault_mode_groups: dict[str, list[str]]
    same_name_groups: dict[str, list[str]]
    name_prefix_groups: dict[str, list[str]]
    system_hint_groups: dict[str, list[str]]


def normalize_text(text: str) -> str:
    text = text.lower().strip()
    return re.sub(r"\s+", "", text)


def tokenize(text: str) -> set[str]:
    text = normalize_text(text)
    if not text:
        return set()
    ascii_tokens = re.findall(r"[a-z0-9_]+", text)
    chinese_chars = re.findall(r"[\u4e00-\u9fff]", text)
    return set(ascii_tokens + chinese_chars)


def jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def text_similarity(left_text: str, right_text: str) -> float:
    left = normalize_text(left_text)
    right = normalize_text(right_text)
    if not left or not right:
        return 0.0
    return max(SequenceMatcher(None, left, right).ratio(), jaccard(tokenize(left), tokenize(right)))


def name_similarity(left: Node, right: Node) -> float:
    scores: list[float] = []
    for left_name in left.all_names():
        for right_name in right.all_names():
            scores.append(text_similarity(left_name, right_name))
    return max(scores, default=0.0)


def attribute_similarity(left: Node, right: Node) -> float:
    keys = (set(left.attributes) | set(right.attributes)) - IGNORED_SIMILARITY_ATTRIBUTE_KEYS
    if not keys:
        return 0.5
    matched = 0.0
    for key in keys:
        left_value = str(left.attributes.get(key, "")).strip()
        right_value = str(right.attributes.get(key, "")).strip()
        if not left_value and not right_value:
            matched += 1.0
        elif left_value and right_value:
            matched += text_similarity(left_value, right_value)
    return matched / len(keys)


def redirect_edges(edges: list[Edge], merge_map: dict[str, str]) -> list[Edge]:
    dedup: dict[tuple[str, str, str], Edge] = {}
    for edge in edges:
        source = merge_map.get(edge.source, edge.source)
        target = merge_map.get(edge.target, edge.target)
        if source == target:
            continue
        relation = _normalize_relation_type(edge.type)
        attributes = _normalize_relation_attributes(edge.type, edge.attributes)
        key = (source, target, relation)
        existing = dedup.get(key)
        if existing is None:
            dedup[key] = Edge(source=source, target=target, type=relation, attributes=attributes)
        else:
            existing.attributes.update(attributes)
    return list(dedup.values())


def _cosine(left: np.ndarray, right: np.ndarray) -> float:
    denom = float(np.linalg.norm(left) * np.linalg.norm(right))
    if denom == 0.0:
        return 0.0
    return float(np.dot(left, right) / denom)


def _normalize_relation_type(relation_type: str) -> str:
    return RELATION_TYPE_ALIASES.get(relation_type, relation_type)


def _normalize_relation_attributes(relation_type: str, attributes: dict[str, Any]) -> dict[str, Any]:
    normalized_type = _normalize_relation_type(relation_type)
    normalized_attributes = dict(attributes)
    if normalized_type != SIMILAR_RELATION:
        return normalized_attributes

    normalized_attributes.pop("relation_type_en", None)
    for key in ("_neo4j_type", "relation_type", "relationship_type", "type_name", "type"):
        value = normalized_attributes.get(key)
        if isinstance(value, str):
            normalized_attributes[key] = _normalize_relation_type(value)
    return normalized_attributes


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return " ".join(f"{key} {item}" for key, item in value.items() if item is not None)
    if isinstance(value, (list, tuple, set)):
        return " ".join(_stringify(item) for item in value if item is not None)
    return str(value)


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    normalized = normalize_text(text)
    if not normalized:
        return False
    return any(normalize_text(keyword) in normalized for keyword in keywords if keyword)


def _classify_role_text(text: str) -> str | None:
    if _contains_any(text, FAULT_MODE_ROLE_KEYWORDS):
        return "fault_mode"
    if _contains_any(text, FUNCTION_ROLE_KEYWORDS):
        return "function"
    if _contains_any(text, EQUIPMENT_ROLE_KEYWORDS):
        return "equipment"
    return None


def _node_metadata_role_text(node: Node) -> str:
    pieces: list[str] = []
    for key in TYPE_ROLE_KEYS:
        value = node.attributes.get(key)
        if value:
            pieces.append(_stringify(value))
    labels = node.attributes.get("_labels", [])
    if isinstance(labels, (list, tuple, set)):
        pieces.extend(str(label) for label in labels if label)
    elif labels:
        pieces.append(str(labels))
    return " ".join(pieces)


def _infer_type_role(node_type: str, sample_nodes: list[Node]) -> str:
    metadata_text = " ".join(_node_metadata_role_text(node) for node in sample_nodes)
    role = _classify_role_text(f"{node_type} {metadata_text}")
    if role:
        return role
    sample_name_text = " ".join(" ".join(node.all_names()) for node in sample_nodes[:30])
    return _classify_role_text(sample_name_text) or "generic"


def _extract_function_text(node: Node) -> str:
    for key in ("function", "功能", "function_name"):
        value = str(node.attributes.get(key, "")).strip()
        if value:
            return value
    if _contains_any(node.type, FUNCTION_ROLE_KEYWORDS):
        return node.name or node.description
    return ""


def _extract_phenomenon_text(node: Node) -> str:
    for key in ("fault_phenomenon", "phenomenon", "故障现象", "raw_text"):
        value = str(node.attributes.get(key, "")).strip()
        if value:
            return value
    if _looks_like_fault_mode_type(node.type):
        return node.description or node.name
    return ""


def _looks_like_fault_mode_type(node_type: str) -> bool:
    return node_type.endswith("级故障模式") or "故障模式" in node_type or _contains_any(node_type, FAULT_MODE_ROLE_KEYWORDS)


def _is_fault_mode_type(node_type: str) -> bool:
    return _looks_like_fault_mode_type(node_type)


def _same_system_hint(left: Node, right: Node) -> bool:
    for key in SYSTEM_HINT_KEYS:
        left_value = str(left.attributes.get(key, "")).strip()
        right_value = str(right.attributes.get(key, "")).strip()
        if left_value and right_value and left_value == right_value:
            return True
    return False


def _same_owner_hint(left: Node, right: Node) -> bool:
    for key in ("owner", "所属对象", "组件", "单机", "系统"):
        left_value = str(left.attributes.get(key, "")).strip()
        right_value = str(right.attributes.get(key, "")).strip()
        if left_value and right_value and left_value == right_value:
            return True
    return False


def _normalized_primary_name(node: Node) -> str:
    return normalize_text(node.name)


def _name_prefix_key(normalized_name: str) -> str:
    return normalized_name[:4] if len(normalized_name) >= 4 else ""


def _pair_key(left_id: str, right_id: str) -> tuple[str, str]:
    return tuple(sorted((left_id, right_id)))


def _system_hint_values(node: Node) -> set[str]:
    values: set[str] = set()
    for key in SYSTEM_HINT_KEYS:
        value = str(node.attributes.get(key, "")).strip()
        if value:
            values.add(f"{key}:{value}")
    return values


def _link_type_texts(node: Node) -> list[str]:
    texts = [node.type]
    for key in EXCLUDED_LINK_NODE_TYPE_KEYS:
        value = node.attributes.get(key)
        if value:
            texts.append(_stringify(value))
    labels = node.attributes.get("_labels", [])
    if isinstance(labels, (list, tuple, set)):
        texts.extend(str(label) for label in labels if label)
    elif labels:
        texts.append(str(labels))
    return texts


def _is_excluded_link_node(node: Node) -> bool:
    excluded = {normalize_text(item) for item in EXCLUDED_LINK_NODE_TYPES}
    for text in _link_type_texts(node):
        normalized = normalize_text(text)
        if normalized in excluded:
            return True
    return False


def _cross_level_equipment_type(node: Node) -> str | None:
    aliases = {normalize_text(key): value for key, value in CROSS_LEVEL_EQUIPMENT_TYPE_ALIASES.items()}
    for text in _link_type_texts(node):
        canonical = aliases.get(normalize_text(text))
        if canonical:
            return canonical
    return None


def _cross_level_fault_mode_type(node: Node) -> str | None:
    aliases = {normalize_text(key): value for key, value in CROSS_LEVEL_FAULT_MODE_TYPE_ALIASES.items()}
    for text in _link_type_texts(node):
        canonical = aliases.get(normalize_text(text))
        if canonical:
            return canonical
    return None


def _is_cross_level_equipment_pair(left: Node, right: Node) -> bool:
    left_type = _cross_level_equipment_type(left)
    right_type = _cross_level_equipment_type(right)
    return bool(left_type and right_type and left_type != right_type)


def _is_cross_level_fault_mode_pair(left: Node, right: Node) -> bool:
    left_type = _cross_level_fault_mode_type(left)
    right_type = _cross_level_fault_mode_type(right)
    return bool(left_type and right_type and left_type != right_type)


def _extract_model_tokens(node: Node) -> set[str]:
    texts = [*node.all_names()]
    for key in ("model", "型号", "code", "编码", "part_no", "spec"):
        value = str(node.attributes.get(key, "")).strip()
        if value:
            texts.append(value)
    tokens: set[str] = set()
    for text in texts:
        for match in MODEL_TOKEN_PATTERN.findall(text.upper()):
            tokens.add(match)
    return tokens


def _equipment_model_conflict(cache: GraphFeatureCache, left_id: str, right_id: str) -> bool:
    left_tokens = cache.model_tokens.get(left_id, set())
    right_tokens = cache.model_tokens.get(right_id, set())
    if not left_tokens or not right_tokens:
        return False
    return left_tokens.isdisjoint(right_tokens)


def _extract_equipment_variant_features(node: Node) -> dict[str, str]:
    texts = [*node.all_names()]
    for key in ("medium", "介质", "position", "位置", "location", "side"):
        value = str(node.attributes.get(key, "")).strip()
        if value:
            texts.append(value)
    features: dict[str, str] = {}
    for group, terms in EQUIPMENT_VARIANT_GROUPS.items():
        for term in terms:
            if any(term in text for text in texts):
                features[group] = term
                break
    return features


def _equipment_variant_conflict(cache: GraphFeatureCache, left_id: str, right_id: str) -> bool:
    left_features = cache.equipment_variant_features.get(left_id, {})
    right_features = cache.equipment_variant_features.get(right_id, {})
    for group in set(left_features) & set(right_features):
        if left_features[group] != right_features[group]:
            return True
    return False


def _equipment_distinguishing_conflict(cache: GraphFeatureCache, left_id: str, right_id: str) -> bool:
    return _equipment_model_conflict(cache, left_id, right_id) or _equipment_variant_conflict(cache, left_id, right_id)


def _equipment_name_core(node: Node) -> str:
    text = node.name or ""
    text = MODEL_TOKEN_PATTERN.sub("", text)
    for term in EQUIPMENT_VARIANT_TERMS:
        text = text.replace(term, "")
    return normalize_text(text)


def _equipment_core_similarity(cache: GraphFeatureCache, left_id: str, right_id: str) -> float:
    return text_similarity(cache.equipment_name_cores.get(left_id, ""), cache.equipment_name_cores.get(right_id, ""))


@dataclass
class MLLinkConfig:
    bert_model_name: str = "bert-base-chinese"
    bert_batch_size: int = 8
    bert_max_length: int = 96
    merge_threshold: float = 0.9
    top_k_candidates: int = 4
    candidate_name_threshold: float = 0.6
    candidate_semantic_threshold: float = 0.86
    recall_semantic_top_k: int = 48
    relation_candidate_top_k: int = 16
    max_similarity_details: int = 20000
    name_weight: float = 0.5
    semantic_weight: float = 0.35
    attribute_weight: float = 0.05
    structure_weight: float = 0.05
    graph_weight: float = 0.05
    cross_level_name_threshold: float = 0.96
    cross_level_semantic_threshold: float = 0.985
    cross_level_attribute_threshold: float = 0.75
    cross_level_structure_threshold: float = 0.55
    cross_level_graph_threshold: float = 0.9
    cross_level_function_threshold: float = 0.95
    cross_level_phenomenon_threshold: float = 0.95
    cross_level_score_threshold: float = 0.95
    graphsage_hidden_dim: int = 128
    graphsage_output_dim: int = 96
    graphsage_epochs: int = 12
    device: str | None = None


@dataclass
class MLLinkResult:
    merged_graph: Graph
    merge_map: dict[str, str]
    merge_edges: list[Edge]
    added_edges: list[Edge]
    similarity_details: list[dict[str, Any]]
    node_order: list[str]
    node_texts: list[str]
    bert_embeddings: np.ndarray
    graphsage_embeddings: np.ndarray
    graphsage_training: dict[str, float]


def _type_groups(graph: Graph) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for node in graph.nodes.values():
        groups.setdefault(node.type, []).append(node.id)
    return groups


def _build_type_profiles(graph: Graph, type_groups: dict[str, list[str]]) -> dict[str, TypeProfile]:
    profiles: dict[str, TypeProfile] = {}
    for node_type, node_ids in type_groups.items():
        nodes = [graph.nodes[node_id] for node_id in node_ids if node_id in graph.nodes]
        property_keys: set[str] = set()
        for node in nodes:
            property_keys.update(node.attributes.keys())
        profiles[node_type] = TypeProfile(
            node_type=node_type,
            role=_infer_type_role(node_type, nodes[:50]),
            count=len(nodes),
            property_keys=property_keys,
        )
    return profiles


def _node_role(cache: GraphFeatureCache, node_id: str) -> str:
    return cache.node_roles.get(node_id, "generic")


def _is_equipment_node(cache: GraphFeatureCache, node_id: str) -> bool:
    return _node_role(cache, node_id) == "equipment"


def _is_fault_mode_node(cache: GraphFeatureCache, node_id: str) -> bool:
    return _node_role(cache, node_id) == "fault_mode"


def _build_feature_cache(graph: Graph, node_order: list[str]) -> GraphFeatureCache:
    index_map = {node_id: idx for idx, node_id in enumerate(node_order)}
    type_groups = _type_groups(graph)
    type_profiles = _build_type_profiles(graph, type_groups)
    node_roles = {
        node_id: type_profiles[node.type].role if node.type in type_profiles else "generic"
        for node_id, node in graph.nodes.items()
    }
    neighbor_types = {node_id: set() for node_id in graph.nodes}
    edge_types = {node_id: set() for node_id in graph.nodes}
    similar_pairs: set[tuple[str, str]] = set()
    similar_neighbors = {node_id: set() for node_id in graph.nodes}
    for edge in graph.edges:
        if edge.source in graph.nodes and edge.target in graph.nodes:
            relation_type = _normalize_relation_type(edge.type)
            edge_types[edge.source].add(relation_type)
            edge_types[edge.target].add(relation_type)
            neighbor_types[edge.source].add(graph.nodes[edge.target].type)
            neighbor_types[edge.target].add(graph.nodes[edge.source].type)
            if relation_type == SIMILAR_RELATION:
                similar_pairs.add(_pair_key(edge.source, edge.target))
                similar_neighbors[edge.source].add(edge.target)
                similar_neighbors[edge.target].add(edge.source)
    function_texts = {node_id: _extract_function_text(node) for node_id, node in graph.nodes.items()}
    phenomenon_texts = {node_id: _extract_phenomenon_text(node) for node_id, node in graph.nodes.items()}
    normalized_names = {node_id: _normalized_primary_name(node) for node_id, node in graph.nodes.items()}
    model_tokens = {node_id: _extract_model_tokens(node) for node_id, node in graph.nodes.items()}
    equipment_variant_features = {node_id: _extract_equipment_variant_features(node) for node_id, node in graph.nodes.items()}
    equipment_name_cores = {node_id: _equipment_name_core(node) for node_id, node in graph.nodes.items()}
    skip_link_node_ids = {node_id for node_id, node in graph.nodes.items() if _is_excluded_link_node(node)}
    cross_level_equipment_groups: dict[str, list[str]] = {}
    cross_level_fault_mode_groups: dict[str, list[str]] = {}
    for node_id, node in graph.nodes.items():
        if node_id in skip_link_node_ids:
            continue
        equipment_type = _cross_level_equipment_type(node)
        if equipment_type:
            cross_level_equipment_groups.setdefault(equipment_type, []).append(node_id)
        fault_mode_type = _cross_level_fault_mode_type(node)
        if fault_mode_type:
            cross_level_fault_mode_groups.setdefault(fault_mode_type, []).append(node_id)
    same_name_groups: dict[str, list[str]] = {}
    name_prefix_groups: dict[str, list[str]] = {}
    system_hint_groups: dict[str, list[str]] = {}
    for node_id, normalized_name in normalized_names.items():
        if normalized_name:
            same_name_groups.setdefault(normalized_name, []).append(node_id)
        prefix = _name_prefix_key(normalized_name)
        if prefix:
            name_prefix_groups.setdefault(prefix, []).append(node_id)
        for value in _system_hint_values(graph.nodes[node_id]):
            system_hint_groups.setdefault(value, []).append(node_id)
    return GraphFeatureCache(
        index_map=index_map,
        type_groups=type_groups,
        type_profiles=type_profiles,
        node_roles=node_roles,
        neighbor_types=neighbor_types,
        edge_types=edge_types,
        function_texts=function_texts,
        phenomenon_texts=phenomenon_texts,
        normalized_names=normalized_names,
        model_tokens=model_tokens,
        equipment_variant_features=equipment_variant_features,
        equipment_name_cores=equipment_name_cores,
        similar_pairs=similar_pairs,
        similar_neighbors=similar_neighbors,
        skip_link_node_ids=skip_link_node_ids,
        cross_level_equipment_groups=cross_level_equipment_groups,
        cross_level_fault_mode_groups=cross_level_fault_mode_groups,
        same_name_groups=same_name_groups,
        name_prefix_groups=name_prefix_groups,
        system_hint_groups=system_hint_groups,
    )


def _structural_similarity(cache: GraphFeatureCache, left_id: str, right_id: str) -> float:
    return 0.6 * jaccard(cache.neighbor_types[left_id], cache.neighbor_types[right_id]) + 0.4 * jaccard(cache.edge_types[left_id], cache.edge_types[right_id])


def _has_similar_relation(cache: GraphFeatureCache, left_id: str, right_id: str) -> bool:
    return _pair_key(left_id, right_id) in cache.similar_pairs


def _should_skip_link_node(cache: GraphFeatureCache, node_id: str) -> bool:
    return node_id in cache.skip_link_node_ids


def _candidate_group_ids_for_node(cache: GraphFeatureCache, node: Node) -> list[str]:
    candidate_ids = [
        node_id
        for node_id in cache.type_groups.get(node.type, [])
        if not _should_skip_link_node(cache, node_id)
    ]
    canonical_type = _cross_level_equipment_type(node)
    if canonical_type:
        for other_type, node_ids in cache.cross_level_equipment_groups.items():
            if other_type == canonical_type:
                continue
            candidate_ids.extend(node_ids)
    fault_mode_type = _cross_level_fault_mode_type(node)
    if fault_mode_type:
        for other_type, node_ids in cache.cross_level_fault_mode_groups.items():
            if other_type == fault_mode_type:
                continue
            candidate_ids.extend(node_ids)
    return list(dict.fromkeys(candidate_ids))


def _linkable_node_ids(cache: GraphFeatureCache) -> list[str]:
    return [
        node_id
        for node_id in cache.index_map
        if not _should_skip_link_node(cache, node_id)
    ]


def _choose_canonical(left: Node, right: Node) -> Node:
    def score(node: Node) -> tuple[int, int, int]:
        return (len(node.sources), len(node.attributes), -len(node.name))
    return max([left, right], key=score)


def _choose_canonical_with_focus(left: Node, right: Node, focus_node_ids: set[str] | None = None) -> Node:
    if focus_node_ids is not None:
        left_is_focus = left.id in focus_node_ids
        right_is_focus = right.id in focus_node_ids
        if left_is_focus and not right_is_focus:
            return right
        if right_is_focus and not left_is_focus:
            return left
    return _choose_canonical(left, right)


def _merge_node_data(canonical: Node, other: Node) -> Node:
    aliases = canonical.all_names() + other.all_names()
    canonical.aliases = [item for item in dict.fromkeys(aliases) if item != canonical.name]
    if not canonical.description:
        canonical.description = other.description
    for key, value in other.attributes.items():
        if key not in canonical.attributes or not canonical.attributes[key]:
            canonical.attributes[key] = value
    canonical.sources = list(dict.fromkeys([*canonical.sources, *other.sources]))
    return canonical


def _top_semantic_candidate_ids(group_ids: list[str], left_id: str, bert_embeddings: np.ndarray, cache: GraphFeatureCache, top_k: int) -> list[str]:
    if not group_ids:
        return []
    left_idx = cache.index_map[left_id]
    candidate_ids = [node_id for node_id in group_ids if node_id != left_id]
    if not candidate_ids:
        return []
    candidate_indices = np.asarray([cache.index_map[node_id] for node_id in candidate_ids], dtype=np.int32)
    scores = bert_embeddings[candidate_indices] @ bert_embeddings[left_idx]
    if len(candidate_ids) <= top_k:
        order = np.argsort(scores)[::-1]
    else:
        partial = np.argpartition(scores, -top_k)[-top_k:]
        order = partial[np.argsort(scores[partial])[::-1]]
    return [candidate_ids[int(idx)] for idx in order]


def _cheap_name_hint(left_name: str, right_name: str) -> bool:
    if not left_name or not right_name:
        return False
    if left_name == right_name:
        return True
    if left_name in right_name or right_name in left_name:
        return True
    return left_name[:4] == right_name[:4] and len(left_name) >= 4 and len(right_name) >= 4


def _recall_candidates(graph: Graph, node: Node, bert_embeddings: np.ndarray, cache: GraphFeatureCache, config: MLLinkConfig) -> list[Node]:
    if _should_skip_link_node(cache, node.id):
        return []
    group_ids = _candidate_group_ids_for_node(cache, node)
    if len(group_ids) <= 1:
        return []
    candidate_ids: set[str] = set(_top_semantic_candidate_ids(group_ids, node.id, bert_embeddings, cache, config.recall_semantic_top_k))
    left_name = cache.normalized_names[node.id]
    group_id_lookup = set(group_ids)
    for indexed_ids in (
        cache.same_name_groups.get(left_name, []),
        cache.name_prefix_groups.get(_name_prefix_key(left_name), []),
        cache.similar_neighbors.get(node.id, set()),
    ):
        for other_id in indexed_ids:
            if other_id != node.id and other_id in group_id_lookup:
                candidate_ids.add(other_id)
    for system_value in _system_hint_values(node):
        for other_id in cache.system_hint_groups.get(system_value, []):
            if other_id != node.id and other_id in group_id_lookup:
                candidate_ids.add(other_id)
    left_idx = cache.index_map[node.id]
    scored: list[tuple[float, Node]] = []
    for other_id in candidate_ids:
        other = graph.nodes[other_id]
        lexical = name_similarity(node, other)
        semantic = float(bert_embeddings[left_idx] @ bert_embeddings[cache.index_map[other_id]])
        if _has_similar_relation(cache, node.id, other_id) or _same_system_hint(node, other) or lexical >= config.candidate_name_threshold or semantic >= config.candidate_semantic_threshold:
            scored.append((0.65 * semantic + 0.35 * lexical, other))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [item[1] for item in scored[: config.top_k_candidates]]


def _merge_final_score(scores: dict[str, float], config: MLLinkConfig) -> float:
    return (
        config.name_weight * scores["name"]
        + config.semantic_weight * scores["semantic"]
        + config.attribute_weight * scores["attribute"]
        + config.structure_weight * scores["structure"]
        + config.graph_weight * scores["graph"]
    )


def _merge_kind_for_node(cache: GraphFeatureCache, node_id: str) -> str:
    if _is_equipment_node(cache, node_id):
        return "equipment"
    if _is_fault_mode_node(cache, node_id):
        return "fault_mode"
    return "generic"


def _classify_merge(left: Node, right: Node, scores: dict[str, float], final_score: float, cache: GraphFeatureCache, config: MLLinkConfig) -> str | None:
    if left.type != right.type:
        cross_level_kind: str | None = None
        has_context = False
        if _is_cross_level_equipment_pair(left, right):
            if _equipment_distinguishing_conflict(cache, left.id, right.id):
                return None
            function_score = text_similarity(cache.function_texts[left.id], cache.function_texts[right.id])
            cross_level_kind = "cross_level_equipment"
            has_context = _same_system_hint(left, right) or function_score >= config.cross_level_function_threshold or scores["name"] >= 0.98
        elif _is_cross_level_fault_mode_pair(left, right):
            phenomenon_score = text_similarity(cache.phenomenon_texts[left.id], cache.phenomenon_texts[right.id])
            cross_level_kind = "cross_level_fault_mode"
            has_context = _same_owner_hint(left, right) or phenomenon_score >= config.cross_level_phenomenon_threshold or scores["name"] >= 0.98

        if cross_level_kind and has_context and (
            scores["name"] >= config.cross_level_name_threshold
            and scores["semantic"] >= config.cross_level_semantic_threshold
            and scores["attribute"] >= config.cross_level_attribute_threshold
            and scores["structure"] >= config.cross_level_structure_threshold
            and scores["graph"] >= config.cross_level_graph_threshold
            and final_score >= config.cross_level_score_threshold
        ):
            return cross_level_kind
        return None
    left_name = cache.normalized_names[left.id]
    right_name = cache.normalized_names[right.id]
    same_name = bool(left_name) and left_name == right_name
    semantic = scores["semantic"]
    attribute = scores["attribute"]
    structure = scores["structure"]
    graph_score = scores["graph"]
    name_score = scores["name"]

    if same_name:
        return _merge_kind_for_node(cache, left.id)

    if _is_equipment_node(cache, left.id):
        if _equipment_distinguishing_conflict(cache, left.id, right.id):
            return None
        function_score = text_similarity(cache.function_texts[left.id], cache.function_texts[right.id])
        if name_score >= 0.9 and semantic >= 0.965 and attribute >= 0.65 and structure >= 0.35 and graph_score >= 0.82 and (_same_system_hint(left, right) or function_score >= 0.92 or name_score >= 0.95) and final_score >= config.merge_threshold:
            return "equipment"
        return None

    if _is_fault_mode_node(cache, left.id):
        phenomenon_score = text_similarity(cache.phenomenon_texts[left.id], cache.phenomenon_texts[right.id])
        if name_score >= 0.9 and semantic >= 0.965 and attribute >= 0.65 and structure >= 0.4 and graph_score >= 0.82 and phenomenon_score >= 0.9 and (_same_owner_hint(left, right) or name_score >= 0.95) and final_score >= config.merge_threshold:
            return "fault_mode"
        return None

    if name_score >= 0.92 and semantic >= 0.97 and attribute >= 0.68 and structure >= 0.45 and graph_score >= 0.85 and final_score >= max(config.merge_threshold, 0.92):
        return "generic"
    return None


def _upsert_similar_edge(additions: dict[tuple[str, str, str], Edge], existing: set[tuple[str, str, str]], source_id: str, target_id: str, similar_kind: str, attributes: dict[str, float | str]) -> None:
    source, target = sorted((source_id, target_id))
    key = (source, target, SIMILAR_RELATION)
    reverse_key = (target, source, SIMILAR_RELATION)
    if key in existing or reverse_key in existing:
        return
    edge = additions.get(key)
    if edge is None:
        edge = Edge(source=source, target=target, type=SIMILAR_RELATION, attributes={"similar_kinds": [similar_kind], "reasons": []})
        additions[key] = edge
    else:
        edge.attributes["similar_kinds"] = list(dict.fromkeys([*edge.attributes.get("similar_kinds", []), similar_kind]))

    reason = str(attributes.pop("reason", "")).strip()
    if reason:
        edge.attributes["reasons"] = list(dict.fromkeys([*edge.attributes.get("reasons", []), reason]))

    for attr_key, attr_value in attributes.items():
        if isinstance(attr_value, str):
            if attr_key not in edge.attributes:
                edge.attributes[attr_key] = attr_value
            continue
        rounded_value = round(float(attr_value), 4)
        previous = edge.attributes.get(attr_key)
        try:
            previous_value = float(previous) if previous is not None else None
        except (TypeError, ValueError):
            previous_value = None
        if previous_value is None or previous_value < rounded_value:
            edge.attributes[attr_key] = rounded_value


def _infer_focused_edges(
    graph: Graph,
    bert_embeddings: np.ndarray,
    graphsage_embeddings: np.ndarray,
    cache: GraphFeatureCache,
    config: MLLinkConfig,
    focus_node_ids: set[str] | None = None,
) -> list[Edge]:
    existing = {(edge.source, edge.target, edge.type) for edge in graph.edges}
    additions: dict[tuple[str, str, str], Edge] = {}
    checked_pairs: set[tuple[str, str]] = set()

    for left_id in _linkable_node_ids(cache):
        if focus_node_ids is not None and left_id not in focus_node_ids:
            continue
        left = graph.nodes[left_id]
        group_ids = _candidate_group_ids_for_node(cache, left)
        if len(group_ids) <= 1:
            continue
        candidate_ids = _top_semantic_candidate_ids(group_ids, left_id, bert_embeddings, cache, config.relation_candidate_top_k)
        for right_id in candidate_ids:
            if focus_node_ids is not None and left_id not in focus_node_ids and right_id not in focus_node_ids:
                continue
            pair = tuple(sorted((left_id, right_id)))
            if pair in checked_pairs:
                continue
            checked_pairs.add(pair)
            right = graph.nodes[right_id]
            left_idx = cache.index_map[left_id]
            right_idx = cache.index_map[right_id]
            semantic = float(bert_embeddings[left_idx] @ bert_embeddings[right_idx])
            graph_score = float(graphsage_embeddings[left_idx] @ graphsage_embeddings[right_idx])
            structure = _structural_similarity(cache, left_id, right_id)

            scores = {
                "name": name_similarity(left, right),
                "semantic": semantic,
                "attribute": attribute_similarity(left, right),
                "structure": structure,
                "graph": graph_score,
            }
            merge_score = _merge_final_score(scores, config)
            strong_kind = _classify_merge(left, right, scores, merge_score, cache, config)
            if strong_kind is None:
                continue

            same_primary_name = bool(cache.normalized_names[left_id]) and cache.normalized_names[left_id] == cache.normalized_names[right_id]
            attributes: dict[str, float | str] = {
                "reason": "same_name" if same_primary_name else "strong_similarity",
                "similarity_score": merge_score,
                "strong_similarity_score": merge_score,
                "strong_similarity_kind": strong_kind,
                "name_score": scores["name"],
                "semantic_score": semantic,
                "attribute_score": scores["attribute"],
                "structure_score": structure,
                "graph_score": graph_score,
                "evidence_count": 3.0 if same_primary_name else 4.0,
            }
            _upsert_similar_edge(
                additions,
                existing,
                left.id,
                right.id,
                "same_name" if same_primary_name else f"strong_{strong_kind}",
                attributes,
            )
    return list(additions.values())


def _clone_graph(graph: Graph) -> Graph:
    return Graph(
        nodes={
            node_id: Node(
                id=node.id,
                name=node.name,
                type=node.type,
                description=node.description,
                aliases=list(node.aliases),
                attributes=dict(node.attributes),
                sources=list(node.sources),
            )
            for node_id, node in graph.nodes.items()
        },
        edges=[
            Edge(
                source=edge.source,
                target=edge.target,
                type=_normalize_relation_type(edge.type),
                attributes=_normalize_relation_attributes(edge.type, edge.attributes),
            )
            for edge in graph.edges
        ],
    )


def connect_graph_with_ml(
    graph: Graph,
    config: MLLinkConfig | None = None,
    focus_node_ids: set[str] | None = None,
) -> MLLinkResult:
    if config is None:
        config = MLLinkConfig()

    working = _clone_graph(graph)
    active_focus_node_ids = None
    if focus_node_ids is not None:
        active_focus_node_ids = {node_id for node_id in focus_node_ids if node_id in working.nodes}
    node_order, node_texts = build_node_texts(working)
    bert_encoder = get_bert_text_encoder(model_name=config.bert_model_name, device=config.device, max_length=config.bert_max_length)
    bert_embeddings = bert_encoder.encode(node_texts, batch_size=config.bert_batch_size)
    initial_cache = _build_feature_cache(working, node_order)
    graphsage_embeddings, training = train_graphsage_embeddings(
        working,
        node_order=node_order,
        initial_features=bert_embeddings,
        config=GraphSAGEConfig(
            hidden_dim=config.graphsage_hidden_dim,
            output_dim=config.graphsage_output_dim,
            epochs=config.graphsage_epochs,
            device=config.device,
        ),
    )

    similarity_details: list[dict[str, Any]] = []
    compared_pairs: set[tuple[str, str]] = set()
    existing_edges = {(edge.source, edge.target, _normalize_relation_type(edge.type)) for edge in working.edges}
    strong_similarity_additions: dict[tuple[str, str, str], Edge] = {}

    for node_id in _linkable_node_ids(initial_cache):
        if active_focus_node_ids is not None and node_id not in active_focus_node_ids:
            continue
        if node_id not in working.nodes:
            continue
        node = working.nodes[node_id]
        for candidate in _recall_candidates(working, node, bert_embeddings, initial_cache, config):
            if candidate.id not in working.nodes:
                continue
            pair = _pair_key(node.id, candidate.id)
            if pair in compared_pairs:
                continue
            compared_pairs.add(pair)
            left_idx = initial_cache.index_map[node.id]
            right_idx = initial_cache.index_map[candidate.id]
            scores = {
                "name": name_similarity(node, candidate),
                "semantic": float(bert_embeddings[left_idx] @ bert_embeddings[right_idx]),
                "attribute": attribute_similarity(node, candidate),
                "structure": _structural_similarity(initial_cache, node.id, candidate.id),
                "graph": float(graphsage_embeddings[left_idx] @ graphsage_embeddings[right_idx]),
            }
            final_score = _merge_final_score(scores, config)
            if len(similarity_details) < config.max_similarity_details:
                similarity_details.append(
                    {
                        "left": node.id,
                        "right": candidate.id,
                        "score": round(final_score, 4),
                        "detail": {key: round(value, 4) for key, value in scores.items()},
                    }
                )
            merge_kind = _classify_merge(node, candidate, scores, final_score, initial_cache, config)
            if merge_kind is None:
                continue
            same_primary_name = bool(initial_cache.normalized_names[node.id]) and initial_cache.normalized_names[node.id] == initial_cache.normalized_names[candidate.id]
            _upsert_similar_edge(
                strong_similarity_additions,
                existing_edges,
                node.id,
                candidate.id,
                "same_name" if same_primary_name else f"strong_{merge_kind}",
                {
                    "reason": "same_name" if same_primary_name else "strong_similarity",
                    "similarity_score": final_score,
                    "strong_similarity_score": final_score,
                    "strong_similarity_kind": merge_kind,
                    "name_score": scores["name"],
                    "semantic_score": scores["semantic"],
                    "attribute_score": scores["attribute"],
                    "structure_score": scores["structure"],
                    "graph_score": scores["graph"],
                    "evidence_count": 3.0 if same_primary_name else 4.0,
                },
            )

    working.edges = redirect_edges(working.edges, {})
    strong_edges = list(strong_similarity_additions.values())
    edge_keys = {(edge.source, edge.target, edge.type) for edge in working.edges}
    for edge in strong_edges:
        key = (edge.source, edge.target, edge.type)
        reverse_key = (edge.target, edge.source, edge.type)
        if key in edge_keys or reverse_key in edge_keys:
            continue
        working.edges.append(edge)
        edge_keys.add(key)

    link_cache = _build_feature_cache(working, node_order)

    focused_edges = _infer_focused_edges(
        working,
        bert_embeddings,
        graphsage_embeddings,
        link_cache,
        config,
        focus_node_ids=active_focus_node_ids,
    )
    added_edges: list[Edge] = list(strong_edges)
    for edge in focused_edges:
        key = (edge.source, edge.target, edge.type)
        reverse_key = (edge.target, edge.source, edge.type)
        if key in edge_keys or reverse_key in edge_keys:
            continue
        working.edges.append(edge)
        edge_keys.add(key)
        added_edges.append(edge)

    return MLLinkResult(
        merged_graph=working,
        merge_map={},
        merge_edges=[],
        added_edges=added_edges,
        similarity_details=similarity_details,
        node_order=node_order,
        node_texts=node_texts,
        bert_embeddings=bert_embeddings,
        graphsage_embeddings=graphsage_embeddings,
        graphsage_training=training,
    )
