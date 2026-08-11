from __future__ import annotations

import json
import os
import re
import runpy
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

from backend.demo_data import ATTRIBUTE_VALUE, TYPE_PRIORITY, get_entity_relation_schema

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ROCKET_FAULT_SCRIPT_ENV = 'ROCKET_FAULT_SCRIPT'
ROCKET_FAULT_SCRIPT_CANDIDATES = (
    PROJECT_ROOT / 'import_fault_graph.py',
    PROJECT_ROOT / 'backend' / 'import_fault_graph.py',
    PROJECT_ROOT / 'parser' / 'import_fault_graph.py',
    PROJECT_ROOT / 'Rocket Fault' / 'import_fault_graph.py',
    PROJECT_ROOT / 'Rocket Fault' / 'release-package' / 'rocket-fault-release' / 'import_fault_graph.py',
)

_ROCKET_FAULT_NAMESPACE: dict | None = None
TRIPLE_EXPORT_DIR = PROJECT_ROOT / '\u4e09\u5143\u7ec4\u62bd\u53d6'
ENTITY_ID_PATTERN = re.compile(r'^E(\d+)$')
RELATION_ID_PATTERN = re.compile(r'^R(\d+)$')
TRIPLE_ID_PATTERN = re.compile(r'^T(\d+)$')

# Ontology-aligned entity labels.
MACHINE = '\u5355\u673a'
MACHINE_FUNCTION = '\u5355\u673a\u529f\u80fd'
COMPONENT = '\u96f6\u90e8\u7ec4\u4ef6'
COMPONENT_FAULT = '\u7ec4\u4ef6\u7ea7\u6545\u969c\u6a21\u5f0f'
SYSTEM = '\u7cfb\u7edf'
SYSTEM_FAULT = '\u7cfb\u7edf\u7ea7\u6545\u969c\u6a21\u5f0f'
GLOBAL_FAULT = '\u603b\u4f53\u7ea7\u6545\u969c\u6a21\u5f0f'
MACHINE_FAULT = '\u5355\u673a\u7ea7\u6545\u969c\u6a21\u5f0f'
GLOBAL = '\u603b\u4f53'
GLOBAL_FUNCTION = '\u603b\u4f53\u529f\u80fd'
COMPONENT_PHENOMENON = '\u7ec4\u4ef6\u7ea7\u6545\u969c\u73b0\u8c61'
MACHINE_PHENOMENON = '\u5355\u673a\u7ea7\u6545\u969c\u73b0\u8c61'
SYSTEM_PHENOMENON = '\u7cfb\u7edf\u7ea7\u6545\u969c\u73b0\u8c61'
GLOBAL_PHENOMENON = '\u603b\u4f53\u7ea7\u6545\u969c\u73b0\u8c61'

REQUIRED_ONTOLOGY_ENTITY_TYPES = (
    GLOBAL,
    GLOBAL_FUNCTION,
    MACHINE,
    MACHINE_FUNCTION,
    COMPONENT,
    COMPONENT_FAULT,
    COMPONENT_PHENOMENON,
    SYSTEM,
    SYSTEM_FAULT,
    SYSTEM_PHENOMENON,
    GLOBAL_FAULT,
    GLOBAL_PHENOMENON,
    MACHINE_PHENOMENON,
    ATTRIBUTE_VALUE,
)

ONTOLOGY_PLACEHOLDER_ENTITY_NAMES = {
    GLOBAL,
    GLOBAL_FUNCTION,
    MACHINE,
    MACHINE_FUNCTION,
    COMPONENT,
    COMPONENT_FAULT,
    COMPONENT_PHENOMENON,
    SYSTEM,
    SYSTEM_FAULT,
    SYSTEM_PHENOMENON,
    GLOBAL_FAULT,
    GLOBAL_PHENOMENON,
    MACHINE_FAULT,
    MACHINE_PHENOMENON,
}

# Ontology-aligned relation labels.
BASE_RELATIONS = {
    'has_function': '\u5177\u6709\u529f\u80fd',
    'include': '\u5305\u542b',
    'has_fault': '\u5b58\u5728\u6545\u969c',
    'causes': '\u5bfc\u81f4',
    'single_point': '\u662f\u5426\u5355\u70b9',
    'severity': '\u4e25\u9177\u5ea6\u7b49\u7ea7',
    'probability': '\u53d1\u751f\u6982\u7387',
    'phase': '\u53d1\u751f\u9636\u6bb5',
    'measure': '\u8bbe\u8ba1\u63aa\u65bd',
}

ONTOLOGY_RELATION_TYPES = (
    '\u5177\u6709\u529f\u80fd',
    '\u5305\u542b',
    '\u5b58\u5728\u6545\u969c',
    '\u5bfc\u81f4',
    '\u6709',
    '\u53d1\u751f\u9636\u6bb5',
    '\u662f\u5426\u5355\u70b9',
    '\u4e25\u9177\u5ea6\u7b49\u7ea7',
    '\u53d1\u751f\u6982\u7387',
    '\u8bbe\u8ba1\u63aa\u65bd',
)

# Table header names (same meaning, possibly different wording across sheets).
HEADER_MACHINE = '\u7cfb\u7edf\u6811\u8282\u70b9'
HEADER_FUNCTION = '\u529f\u80fd'
HEADER_UNIT_FAULT = '\u6545\u969c\u6a21\u5f0f\u540d\u79f0'
HEADER_COMPONENT_REASON = '\u6545\u969c\u539f\u56e0'
HEADER_HIGHER_IMPACT = '\u9ad8\u4e00\u5c42\u7ea7\u5f71\u54cd'
HEADER_FINAL_IMPACT = '\u6700\u7ec8\u5f71\u54cd'
HEADER_SINGLE_POINT = '\u662f\u5426\u5355\u70b9'
HEADER_SEVERITY = '\u4e25\u9177\u5ea6\u7b49\u7ea7'
HEADER_PROBABILITY = '\u53d1\u751f\u6982\u7387\u7b49\u7ea7'
HEADER_PHASE = '\u4efb\u52a1\u9636\u6bb5'
HEADER_MEASURE = '\u8bbe\u8ba1\u63aa\u65bd'

_HEADER_DEFAULT_TYPE_MAP = {
    HEADER_MACHINE: MACHINE,
    HEADER_FUNCTION: MACHINE_FUNCTION,
    HEADER_UNIT_FAULT: MACHINE_FAULT,
    HEADER_COMPONENT_REASON: COMPONENT_FAULT,
    HEADER_HIGHER_IMPACT: SYSTEM_FAULT,
    HEADER_FINAL_IMPACT: GLOBAL_FAULT,
    HEADER_SINGLE_POINT: ATTRIBUTE_VALUE,
    HEADER_SEVERITY: ATTRIBUTE_VALUE,
    HEADER_PROBABILITY: ATTRIBUTE_VALUE,
    HEADER_PHASE: ATTRIBUTE_VALUE,
    HEADER_MEASURE: ATTRIBUTE_VALUE,
}

# Compatibility aliases for older column wording.
_HEADER_ALIASES = {
    '\u53d1\u751f\u6982\u7387': HEADER_PROBABILITY,
    '\u4e25\u91cd\u5ea6': HEADER_SEVERITY,
    '\u4e25\u91cd\u5ea6\u7b49\u7ea7': HEADER_SEVERITY,
    '\u9ad8\u4e00\u5c42\u5f71\u54cd': HEADER_HIGHER_IMPACT,
}


def _normalize_header_key(value: str) -> str:
    return ''.join(str(value or '').strip().replace('\u3000', ' ').split()).lower()


def _canonical_header_name(header: str) -> str:
    normalized = _normalize_header_key(header)
    for raw, canonical in _HEADER_ALIASES.items():
        if _normalize_header_key(raw) == normalized:
            return canonical
    return header.strip()


BASE_HEADERS = {_normalize_header_key(name) for name in _HEADER_DEFAULT_TYPE_MAP.keys()}


def _unique_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in values:
        text = str(item or '').strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _split_numbered_segments(value: str) -> list[str]:
    normalized = str(value or '').strip().replace('：', ':')
    if not normalized:
        return []
    matches = list(re.finditer(r'\d+\s*:', normalized))
    if not matches:
        return []

    segments: list[str] = []
    current_start = matches[0].end() if matches[0].start() == 0 else 0
    iter_matches = matches[1:] if matches[0].start() == 0 else matches
    for match in iter_matches:
        segment = normalized[current_start:match.start()].strip(' ;；,，、')
        if segment:
            segments.append(segment)
        current_start = match.end()
    tail = normalized[current_start:].strip(' ;；,，、')
    if tail:
        segments.append(tail)
    return segments if len(segments) > 1 else []


def _split_prefixed_pairs(value: str) -> list[tuple[str, str]]:
    text = str(value or '').strip()
    if not text:
        return []
    normalized = text.replace('：', ':')
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    numbered_segments = _split_numbered_segments(normalized)
    if numbered_segments:
        segments = numbered_segments
    else:
        segments = [segment.strip() for segment in re.split(r'[。；;\n]+', normalized) if segment.strip()]

    # 先按句号/分号/换行拆，再按并列逗号拆，最后按冒号配对。
    for segment in segments:
        subsegments = [sub.strip() for sub in re.split(r'[，,、]+', segment) if sub.strip()]
        for sub in subsegments:
            if ':' not in sub:
                continue
            left, right = sub.split(':', 1)
            pair = (left.strip(), right.strip())
            if not pair[0] or not pair[1]:
                continue
            if pair in seen:
                continue
            seen.add(pair)
            pairs.append(pair)
    return pairs


def _safe_file_stem(file_name: str) -> str:
    stem = Path(file_name or 'table').stem.strip() or 'table'
    safe_chars = []
    for ch in stem:
        if ch.isalnum() or ch in ('-', '_'):
            safe_chars.append(ch)
        elif '\u4e00' <= ch <= '\u9fff':
            safe_chars.append(ch)
        else:
            safe_chars.append('_')
    normalized = ''.join(safe_chars).strip('_')
    return normalized or 'table'


def _build_ontology_declarations(graph_payload: dict) -> dict:
    declared_entity_types = _unique_preserve_order(list(REQUIRED_ONTOLOGY_ENTITY_TYPES))
    declared_relation_names = _unique_preserve_order(list(ONTOLOGY_RELATION_TYPES))
    found_entity_types = {str(item.get('type', '')).strip() for item in graph_payload.get('entities', [])}
    found_relation_names = {str(item.get('name', '')).strip() for item in graph_payload.get('relations', [])}
    entity_declarations = [{'entityName': entity_type} for entity_type in declared_entity_types]
    relation_declarations = [{'relationName': relation_name} for relation_name in declared_relation_names]
    missing_entities = [entity_type for entity_type in declared_entity_types if entity_type not in found_entity_types]
    missing_relations = [relation_name for relation_name in declared_relation_names if relation_name not in found_relation_names]
    return {
        'entityDeclarations': [
            *entity_declarations
        ],
        'relationDeclarations': [
            *relation_declarations
        ],
        'missingOntologyPlaceholders': {
            'nodes': missing_entities,
            'relations': missing_relations,
        },
    }


def _export_triple_json(payload: dict, source_file_name: str) -> str:
    TRIPLE_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    out_name = f'{_safe_file_stem(source_file_name)}_triples_{timestamp}.json'
    out_path = TRIPLE_EXPORT_DIR / out_name
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return str(out_path.relative_to(PROJECT_ROOT)).replace('\\', '/')


def _max_existing_id_number(collection_key: str, id_pattern: re.Pattern, export_dir: Path = TRIPLE_EXPORT_DIR) -> int:
    if not export_dir.exists():
        return 0

    max_number = 0
    for path in export_dir.glob('*.json'):
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(payload, dict):
            continue

        for item in payload.get(collection_key, []):
            if not isinstance(item, dict):
                continue
            match = id_pattern.fullmatch(str(item.get('id', '')).strip())
            if match:
                max_number = max(max_number, int(match.group(1)))
    return max_number


def _max_existing_entity_number(export_dir: Path = TRIPLE_EXPORT_DIR) -> int:
    return _max_existing_id_number('entities', ENTITY_ID_PATTERN, export_dir)


def _max_existing_relation_number(export_dir: Path = TRIPLE_EXPORT_DIR) -> int:
    return _max_existing_id_number('relations', RELATION_ID_PATTERN, export_dir)


def _max_existing_triple_number(export_dir: Path = TRIPLE_EXPORT_DIR) -> int:
    return _max_existing_id_number('triples', TRIPLE_ID_PATTERN, export_dir)


def _next_entity_number() -> int:
    return _max_existing_entity_number() + 1


def _next_relation_number() -> int:
    return _max_existing_relation_number() + 1


def _next_triple_number() -> int:
    return _max_existing_triple_number() + 1


def _append_property(properties: dict[str, object], key: str, value: str) -> None:
    prop_name = HEADER_PHASE if key == BASE_RELATIONS['phase'] else key
    text = str(value or '').strip()
    if not prop_name or not text:
        return
    existing = properties.get(prop_name)
    if existing is None:
        properties[prop_name] = text
        return
    if isinstance(existing, list):
        if text not in existing:
            existing.append(text)
        return
    if existing != text:
        properties[prop_name] = [existing, text]


def _build_structured_triple_definition(
    graph_payload: dict,
    source_file_name: str,
    declaration_payload: dict,
    entity_start: int | None = None,
    relation_start: int | None = None,
    triple_start: int | None = None,
) -> dict:
    entity_index: dict[tuple[str, str], dict] = {}
    relation_index: dict[tuple[str, str, str], dict] = {}
    triple_rows = list(graph_payload.get('tripleRows', []))
    structured_triples: list[dict] = []
    entity_counter = entity_start if entity_start is not None else _next_entity_number()
    relation_counter = relation_start if relation_start is not None else _next_relation_number()
    triple_counter = triple_start if triple_start is not None else _next_triple_number()

    def ensure_entity(name: str, entity_type: str) -> str:
        nonlocal entity_counter
        key = (str(name or '').strip(), str(entity_type or '').strip())
        if not key[0] or not key[1]:
            return ''
        if key not in entity_index:
            entity_id = f'E{entity_counter:03d}'
            entity_counter += 1
            entity_index[key] = {
                'id': entity_id,
                'name': key[0],
                'type': key[1],
                'properties': {},
            }
        return entity_index[key]['id']

    def ensure_relation(name: str, subject_type: str, object_type: str) -> str:
        nonlocal relation_counter
        key = (str(name or '').strip(), str(subject_type or '').strip(), str(object_type or '').strip())
        if not key[0] or not key[1] or not key[2]:
            return ''
        if key not in relation_index:
            relation_id = f'R{relation_counter:03d}'
            relation_counter += 1
            relation_index[key] = {
                'id': relation_id,
                'name': key[0],
                'subject_type': key[1],
                'object_type': key[2],
            }
        return relation_index[key]['id']

    for row in triple_rows:
        subject = str(row.get('subject', '')).strip()
        predicate = str(row.get('predicate', '')).strip()
        object_name = str(row.get('object', '')).strip()
        subject_type = str(row.get('subjectType', '')).strip()
        object_type = str(row.get('objectType', '')).strip()
        if not subject or not predicate or not object_name or not subject_type or not object_type:
            continue

        subject_id = ensure_entity(subject, subject_type)
        object_id = ensure_entity(object_name, object_type)
        predicate_id = ensure_relation(predicate, subject_type, object_type)
        if not subject_id or not object_id or not predicate_id:
            continue
        structured_triples.append(
            {
                'id': f'T{triple_counter:03d}',
                'subject_id': subject_id,
                'predicate_id': predicate_id,
                'object_id': object_id,
            }
        )
        triple_counter += 1

    entities = []
    for entity in entity_index.values():
        payload = {
            'id': entity['id'],
            'name': entity['name'],
            'type': entity['type'],
        }
        if entity['properties']:
            payload['properties'] = entity['properties']
        entities.append(payload)

    return {
        'fileName': source_file_name,
        'sourceType': 'table',
        'generatedAt': datetime.now().isoformat(timespec='seconds'),
        'definition': declaration_payload,
        'counts': {
            'entities': len(entities),
            'relations': len(relation_index),
            'triples': len(structured_triples),
        },
        'entities': entities,
        'relations': list(relation_index.values()),
        'triples': structured_triples,
    }


def _load_rocket_fault_namespace() -> dict:
    global _ROCKET_FAULT_NAMESPACE
    if _ROCKET_FAULT_NAMESPACE is None:
        script_path = _resolve_rocket_fault_script()
        _ROCKET_FAULT_NAMESPACE = runpy.run_path(str(script_path))
    return _ROCKET_FAULT_NAMESPACE


def _resolve_rocket_fault_script() -> Path:
    configured_path = os.environ.get(ROCKET_FAULT_SCRIPT_ENV, '').strip()
    if configured_path:
        script_path = Path(configured_path).expanduser()
        if not script_path.is_absolute():
            script_path = (PROJECT_ROOT / script_path).resolve()
        if script_path.exists():
            return script_path
        raise FileNotFoundError(
            f'Rocket Fault parser not found via {ROCKET_FAULT_SCRIPT_ENV}: {script_path}'
        )

    for candidate in ROCKET_FAULT_SCRIPT_CANDIDATES:
        if candidate.exists():
            return candidate

    candidate_text = ', '.join(str(path) for path in ROCKET_FAULT_SCRIPT_CANDIDATES)
    raise FileNotFoundError(
        'Rocket Fault parser not found. '
        f'Set {ROCKET_FAULT_SCRIPT_ENV} or place import_fault_graph.py in one of: {candidate_text}'
    )


def _temporary_upload(file_name: str, content: bytes) -> Path:
    suffix = Path(file_name or 'upload.xlsx').suffix or '.xlsx'
    with NamedTemporaryFile(delete=False, suffix=suffix) as handle:
        handle.write(content)
        return Path(handle.name)


def _table_header_default_type(header: str) -> str:
    canonical = _canonical_header_name(header)
    return _HEADER_DEFAULT_TYPE_MAP.get(canonical, ATTRIBUTE_VALUE)


def _load_table_records(
    primary_file_name: str,
    primary_file_content: bytes,
    extra_file_name: str | None = None,
    extra_file_content: bytes | None = None,
) -> tuple[list[dict], list[str], dict[str, str]]:
    namespace = _load_rocket_fault_namespace()
    load_records = namespace['load_records']
    merge_records = namespace['merge_records']

    primary_path = _temporary_upload(primary_file_name, primary_file_content)
    extra_path = (
        _temporary_upload(extra_file_name or 'extra.xlsx', extra_file_content)
        if extra_file_name and extra_file_content is not None
        else None
    )

    def load_records_safe(path: Path, is_primary: bool, file_name: str) -> list[dict]:
        try:
            return load_records(path, None, is_primary)
        except Exception as exc:
            lower_name = str(file_name or '').lower()
            if 'sheet1.xml' in str(exc).lower():
                raise ValueError(
                    f'表格文件“{file_name}”不是可解析的标准 Excel 工作簿，请重新用 Excel 另存为 .xlsx 后再上传。原始错误：{exc}'
                ) from exc
            if lower_name.endswith('.xlsx') or lower_name.endswith('.xls') or lower_name.endswith('.csv'):
                raise ValueError(f'表格文件“{file_name}”解析失败：{exc}') from exc
            raise

    try:
        records = load_records_safe(primary_path, True, primary_file_name)
        primary_headers = list(records[0].keys()) if records else []
        extra_headers: list[str] = []
        if extra_path is not None:
            extra_records = load_records_safe(extra_path, False, extra_file_name or 'extra.xlsx')
            extra_headers = list(extra_records[0].keys()) if extra_records else []
            records = merge_records(records, extra_records)
        headers = list(records[0].keys()) if records else []
        header_sources: dict[str, str] = {}
        primary_header_set = set(primary_headers)
        extra_header_set = set(extra_headers)
        for header in headers:
            if header in extra_header_set and header not in primary_header_set:
                header_sources[header] = 'extra'
            else:
                header_sources[header] = 'primary'
        return records, headers, header_sources
    finally:
        primary_path.unlink(missing_ok=True)
        if extra_path is not None:
            extra_path.unlink(missing_ok=True)


def get_table_parse_configuration(
    primary_file_name: str,
    primary_file_content: bytes,
    extra_file_name: str | None = None,
    extra_file_content: bytes | None = None,
) -> dict:
    schema = get_entity_relation_schema()
    entity_types = _unique_preserve_order(
        list(schema.get('entityTypes', [])) + list(REQUIRED_ONTOLOGY_ENTITY_TYPES)
    )
    records, headers, header_sources = _load_table_records(
        primary_file_name,
        primary_file_content,
        extra_file_name,
        extra_file_content,
    )
    return {
        'fileName': primary_file_name,
        'extraFileName': extra_file_name or '',
        'sourceType': 'table',
        'needsMapping': True,
        'headers': [
            {
                'header': header,
                'defaultType': _table_header_default_type(header),
                'source': header_sources.get(header, 'primary'),
            }
            for header in headers
        ],
        'entityTypes': entity_types,
        'rowCount': len(records),
    }


def _collect_table_graph(serialized_rows: list[dict], mappings: list[dict] | None = None) -> dict:
    entity_rows: list[dict] = []
    triple_rows: list[dict] = []
    relation_count: dict[str, int] = {}
    entity_seen: set[tuple[str, str]] = set()

    def add_entity(name: str, entity_type: str) -> None:
        key = (name, entity_type)
        if not name or key in entity_seen or _is_ontology_placeholder_entity(name, entity_type):
            return
        entity_seen.add(key)
        entity_rows.append({'name': name, 'type': entity_type})

    def add_triple(
        subject: str,
        subject_type: str,
        predicate: str,
        object_name: str,
        object_type: str,
    ) -> None:
        subject_text = str(subject or '').strip()
        object_text = str(object_name or '').strip()
        if not subject_text or not object_text:
            return
        if _is_ontology_placeholder_entity(subject_text, subject_type) or _is_ontology_placeholder_entity(object_text, object_type):
            return
        add_entity(subject_text, subject_type)
        add_entity(object_text, object_type)
        triple_rows.append(
            {
                'subject': subject_text,
                'predicate': predicate,
                'object': object_text,
                'subjectType': subject_type,
                'objectType': object_type,
            }
        )
        relation_count[predicate] = relation_count.get(predicate, 0) + 1

    for row in serialized_rows:
        machine_name = str(row.get('machine_name', '')).strip()
        function_name = str(row.get('function_name', '')).strip()
        unit_failure_mode = str(row.get('unit_failure_mode', '')).strip()
        component_name = str(row.get('component_name', '')).strip()
        component_failure_mode = str(row.get('component_failure_mode', '')).strip()
        system_name = str(row.get('system_name', '')).strip()
        system_failure_mode = str(row.get('system_failure_mode', '')).strip()
        overall_failure_mode = str(row.get('overall_failure_mode', '')).strip()
        component_reason_raw = str(row.get('component_reason_raw', '')).strip()
        system_effect_raw = str(row.get('system_effect_raw', '')).strip()

        component_pairs = _split_prefixed_pairs(component_reason_raw)
        if not component_pairs and component_name and component_failure_mode:
            component_pairs = [(component_name, component_failure_mode)]

        system_pairs = _split_prefixed_pairs(system_effect_raw)
        if not system_pairs and system_name and system_failure_mode:
            system_pairs = [(system_name, system_failure_mode)]

        component_names = _unique_preserve_order([component_name] + [name for name, _ in component_pairs])
        system_names = _unique_preserve_order([system_name] + [name for name, _ in system_pairs])

        # 系统 / 单机 / 零部组件 包含关系
        add_triple(system_name, SYSTEM, BASE_RELATIONS['include'], machine_name, MACHINE)
        for comp_name in component_names:
            add_triple(machine_name, MACHINE, BASE_RELATIONS['include'], comp_name, COMPONENT)
            for sys_name in system_names:
                add_triple(sys_name, SYSTEM, BASE_RELATIONS['include'], comp_name, COMPONENT)

        # 单机基础关系
        add_triple(machine_name, MACHINE, BASE_RELATIONS['has_function'], function_name, MACHINE_FUNCTION)
        add_triple(machine_name, MACHINE, BASE_RELATIONS['has_fault'], unit_failure_mode, MACHINE_FAULT)

        # 故障原因：支持多个冒号配对
        for comp_name, comp_mode in component_pairs:
            add_triple(comp_name, COMPONENT, BASE_RELATIONS['has_fault'], comp_mode, COMPONENT_FAULT)
            add_triple(comp_mode, COMPONENT_FAULT, BASE_RELATIONS['causes'], unit_failure_mode, MACHINE_FAULT)

        # 高一层级影响：支持多个冒号配对
        for sys_name, sys_mode in system_pairs:
            add_triple(sys_name, SYSTEM, BASE_RELATIONS['has_fault'], sys_mode, SYSTEM_FAULT)
            add_triple(unit_failure_mode, MACHINE_FAULT, BASE_RELATIONS['causes'], sys_mode, SYSTEM_FAULT)
            add_triple(sys_mode, SYSTEM_FAULT, BASE_RELATIONS['causes'], overall_failure_mode, GLOBAL_FAULT)

        add_triple(
            unit_failure_mode,
            MACHINE_FAULT,
            BASE_RELATIONS['single_point'],
            str(row.get('is_single_point', '')).strip() or '\u672a\u6807\u6ce8',
            ATTRIBUTE_VALUE,
        )
        add_triple(
            unit_failure_mode,
            MACHINE_FAULT,
            BASE_RELATIONS['severity'],
            str(row.get('severity_level', '')).strip() or '\u672a\u6807\u6ce8',
            ATTRIBUTE_VALUE,
        )
        add_triple(
            unit_failure_mode,
            MACHINE_FAULT,
            BASE_RELATIONS['probability'],
            str(row.get('probability_level', '')).strip() or '\u672a\u6807\u6ce8',
            ATTRIBUTE_VALUE,
        )
        add_triple(
            unit_failure_mode,
            MACHINE_FAULT,
            BASE_RELATIONS['phase'],
            str(row.get('mission_phase', '')).strip() or '\u672a\u6807\u6ce8',
            ATTRIBUTE_VALUE,
        )
        add_triple(
            unit_failure_mode,
            MACHINE_FAULT,
            BASE_RELATIONS['measure'],
            str(row.get('design_measure', '')).strip() or '\u672a\u6807\u6ce8',
            ATTRIBUTE_VALUE,
        )

        extra_columns = row.get('extra_columns', {})
        if not isinstance(extra_columns, dict):
            continue
        for item in mappings or []:
            header = str(item.get('header', '')).strip()
            entity_type = str(item.get('entityType', '')).strip() or ATTRIBUTE_VALUE
            if not header or _normalize_header_key(_canonical_header_name(header)) in BASE_HEADERS:
                continue
            value = str(extra_columns.get(header, '')).strip()
            if value:
                add_triple(unit_failure_mode, MACHINE_FAULT, header, value, entity_type)

    priority_map = {
        GLOBAL_FAULT: 0,
        SYSTEM: 1,
        SYSTEM_FAULT: 2,
        MACHINE: 3,
        MACHINE_FAULT: 4,
        COMPONENT: 5,
        COMPONENT_FAULT: 6,
        MACHINE_FUNCTION: 7,
        ATTRIBUTE_VALUE: 8,
        **TYPE_PRIORITY,
    }

    return {
        'tripleRows': triple_rows,
        'entities': sorted(entity_rows, key=lambda item: (priority_map.get(item['type'], 99), item['name'])),
        'relations': [{'name': name, 'count': count} for name, count in relation_count.items()],
        'counts': {
            'triples': len(triple_rows),
            'entities': len(entity_rows),
            'relations': len(relation_count),
        },
    }


def _is_ontology_placeholder_entity(name: str, entity_type: str) -> bool:
    name_text = str(name or '').strip()
    type_text = str(entity_type or '').strip()
    return bool(name_text and name_text == type_text and name_text in ONTOLOGY_PLACEHOLDER_ENTITY_NAMES)



def get_table_extraction_result(
    primary_file_name: str,
    primary_file_content: bytes,
    mappings: list[dict] | None = None,
    extra_file_name: str | None = None,
    extra_file_content: bytes | None = None,
) -> dict:
    namespace = _load_rocket_fault_namespace()
    build_graph_rows = namespace['build_graph_rows']
    serialize_rows = namespace['serialize_rows']

    records, _headers, header_sources = _load_table_records(
        primary_file_name,
        primary_file_content,
        extra_file_name,
        extra_file_content,
    )
    graph_rows = build_graph_rows(records)
    serialized_rows = serialize_rows(graph_rows)
    graph_payload = _collect_table_graph(serialized_rows, mappings)
    applied_mappings = []
    for item in mappings or []:
        header = str(item.get('header', '')).strip()
        applied_mappings.append(
            {
                **item,
                'source': header_sources.get(header, item.get('source', 'primary')),
            }
        )

    result = {
        'fileName': primary_file_name,
        'extraFileName': extra_file_name or '',
        'sourceType': 'table',
        'appliedMappings': applied_mappings,
        **graph_payload,
    }
    declaration_payload = _build_ontology_declarations(graph_payload)
    triple_definition = _build_structured_triple_definition(
        graph_payload,
        primary_file_name,
        declaration_payload,
    )
    result['definition'] = declaration_payload
    result['tripleJsonPath'] = _export_triple_json(triple_definition, primary_file_name)
    return result
