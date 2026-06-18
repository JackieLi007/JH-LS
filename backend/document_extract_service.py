from __future__ import annotations

import json
import os
import re
from collections import Counter
from datetime import datetime
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from backend.offline_config import configure_offline_environment, offline_enabled, url_allowed_in_offline

configure_offline_environment()

DOCUMENT = '文档'
EQUIPMENT = '设备'
FUNCTION = '功能'
FEATURE = '特点'
MAINTENANCE = '维修维护'
FAULT = '故障类型'
FAULT_PHENOMENON = '故障现象'
FAULT_CAUSE = '故障原因'
HANDLING = '处理措施'
SAFETY = '安全注意事项'
SPECIFICATION = '技术参数'
ATTRIBUTE = '属性值'

MAX_LLM_TEXT_CHARS = 32000
MAX_PREVIEW_CHARS = 1800
DEFAULT_LLM_TIMEOUT_SECONDS = float(os.environ.get('DOCUMENT_LLM_TIMEOUT_SECONDS', '1800'))
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOCUMENT_EXPORT_DIR = PROJECT_ROOT / '\u6587\u6863\u62bd\u53d6\u7ed3\u679c'
DOCUMENT_TRIPLE_EXPORT_DIR = PROJECT_ROOT / '文档三元组抽取'

CATEGORY_CONFIG = {
    'functions': {
        'label': '功能',
        'keywords': ('功能', '用途', '用于', '作用', '实现', '适用于'),
    },
    'features': {
        'label': '特点',
        'keywords': ('特点', '特性', '优势', '性能', '结构', '采用', '配置'),
    },
    'maintenance': {
        'label': '维修维护',
        'keywords': ('维修', '维护', '保养', '检查', '更换', '调整', '润滑', '清洁', '拆卸', '安装'),
    },
    'faultTypes': {
        'label': '故障类型',
        'keywords': ('故障', '异常', '报警', '失效', '原因', '排除', '处理'),
    },
    'safetyNotes': {
        'label': '安全注意事项',
        'keywords': ('注意', '警告', '危险', '禁止', '安全', '不得', '严禁'),
    },
}

FAULT_CAUSE_MARKERS = ('使得', '引起', '导致', '造成', '致使', '引发', '诱发', '致')
FAULT_STATE_CAUSE_PATTERNS = (
    r'(?P<cause>[^，,。；;]{2,80}?(?:存在问题|存在异常|存在故障|存在缺陷|发生故障|发生异常|出现故障|出现异常))[,，:： ]*(?P<phenomenon>[^。；;]{2,80})',
)
FAULT_PHENOMENON_HINTS = (
    '异常', '偏差', '偏低', '偏高', '下降', '跌落', '积水', '泄漏', '漏气', '漏液', '无图像输出',
    '无输出', '失效', '损坏', '变形', '漂移', '晚', '无法', '未关闭', '跳变', '脱落', '断裂',
)
FAULT_CAUSE_HINTS = (
    '剪断', '断裂', '故障', '异常', '有问题', '存在问题', '存在异常', '未排空', '未完全关闭',
    '配置有偏差', '参数设置不合适', '输出异常', '塑性变形', '剪力', '拉力',
    '未终止', '超出超压保护阈值', '错误触发',
)
INVALID_FAULT_PHENOMENON_PATTERNS = (
    r'^其他[^，,。；;]{0,20}无异常$',
    r'^[^，,。；;]{0,20}无异常$',
    r'^[^，,。；;]{0,20}工作正常$',
    r'^[^，,。；;]{0,20}显示正常$',
)
INVALID_FAULT_PHENOMENON_PATTERNS = INVALID_FAULT_PHENOMENON_PATTERNS + (
    r'^(?:更换后|更换备件后|按(?:照)?测试流程).{0,80}(?:检查|复测|漏气量).*$',
    r'^(?:检查|复测).{0,80}(?:均)?满足设计要求$',
    r'^.{0,80}(?:均)?满足设计要求$',
)

FAULT_PHENOMENON_HINTS = FAULT_PHENOMENON_HINTS + ('突变', '漏率', '漏气量')
INVALID_FAULT_PHENOMENON_PATTERNS = INVALID_FAULT_PHENOMENON_PATTERNS + (
    r'^(?:\d{1,2}:\d{2}\s*左右)?手动[^。；;]{0,40}脱落[^。；;]{0,20}$',
    r'^(?:使用工装|测试发现|重复动作阀门)[^。；;]{0,60}$',
)

INVALID_FAULT_PHENOMENON_PATTERNS = INVALID_FAULT_PHENOMENON_PATTERNS + (
    r'^.{0,40}\u95ee\u9898\u5b9a\u4f4d\u4e8e[:\uff1a]?$',
    r'^.{0,40}\u5b9a\u4f4d\u4e8e[:\uff1a]?$',
)

DEVICE_SUFFIXES = (
    '模块', '芯片', '装置', '传感器', '阀门', '电箱', '组件', '系统', '设备', '单机',
    '总成', '壳体', '连接器', '活门', '相机', '摄像装置', '保持器', '转换器', '分机',
    '箭体', '火工拔销器', '解锁组件',
)
DEVICE_SUFFIXES = DEVICE_SUFFIXES + ('密封带',)

EXTRA_DEVICE_TERMS = (
    '\u6805\u683c\u8235',
    '\u8235\u673a\u6784\u652f\u8033',
    '\u652f\u8033',
    '\u6846\u67b6\u5b89\u88c5\u5185\u8154',
    '\u5185\u8154',
    '\u8235\u673a\u6784',
    '\u4f3a\u670d\u673a\u6784',
    '\u8235\u9ccd\u5916\u58f3',
    '\u5916\u58f3',
)

FAULT_LLM_MAX_PARAGRAPHS = 12
DEVICE_GLOSSARY_ENV_KEYS = ('DEVICE_GLOSSARY_PATH', 'KG_DEVICE_GLOSSARY_PATH')
DEFAULT_DEVICE_GLOSSARY_PATHS = (
    PROJECT_ROOT / '设备词库.txt',
    PROJECT_ROOT / 'static' / '设备词库.txt',
)
GENERIC_EQUIPMENT_TOKENS = (
    '过程', '任务', '情况', '问题', '输入', '检查', '现场', '厂房', '原文',
    '液态水', '水流', '时间', '地点', '阶段',
)
DATE_PREFIX_PATTERN = re.compile(
    r'^(?:\d{4}年\d{1,2}月\d{1,2}日|\d{1,2}月\d{1,2}日(?:前|后)?|\d{1,2}日(?:晚|上午|下午|凌晨|中午)?\d{0,2}(?:点|时)?(?:左右)?|近日|当天|当日)[，,、 ]*'
)
LOCATION_PREFIX_PATTERN = re.compile(
    r'^(?:在)?(?:海南|文昌|商发|测试总装厂房|江苏|北京|上海|西安|现场)[^，,。；;]{0,18}[，,、 ]*'
)

FRONTEND_RELATION_LABELS = {
    'has function': '具有功能',
    'Include': '包含',
    'has failure mode': '存在故障',
    'lead to': '导致',
    'has': '有',
    'Occurrence stage': '发生阶段',
    'yes/no': '是否单点',
    'Level Classification': '严酷度等级',
    'Probability': '发生概率',
    'Solution': '设计措施',
}

DOCUMENT_ONTOLOGY_FALLBACK = {
    'entityTypes': [
        '零部组件',
        '零部组件功能',
        '单机',
        '单机功能',
        '系统',
        '系统功能',
        '总体',
        '总体功能',
        '组件级故障模式',
        '单机级故障模式',
        '系统级故障模式',
        '总体级故障模式',
        '组件级故障现象',
        '单机级故障现象',
        '系统级故障现象',
        '总体级故障现象',
        '属性值',
    ],
    'relations': [
        '具有功能',
        '包含',
        '存在故障',
        '导致',
        '有',
        '发生阶段',
        '是否单点',
        '严酷度等级',
        '发生概率',
        '设计措施',
    ],
    'patterns': [
        ('零部组件', '具有功能', '零部组件功能'),
        ('单机', '包含', '零部组件'),
        ('系统', '包含', '单机'),
        ('单机', '具有功能', '单机功能'),
        ('零部组件', '存在故障', '组件级故障模式'),
        ('单机', '存在故障', '单机级故障模式'),
        ('组件级故障模式', '导致', '单机级故障模式'),
        ('系统', '具有功能', '系统功能'),
        ('总体', '具有功能', '总体功能'),
        ('系统', '存在故障', '系统级故障模式'),
        ('总体', '存在故障', '总体级故障模式'),
        ('总体', '包含', '系统'),
        ('单机级故障模式', '导致', '系统级故障模式'),
        ('系统级故障模式', '导致', '总体级故障模式'),
        ('组件级故障模式', '有', '组件级故障现象'),
        ('单机级故障模式', '有', '单机级故障现象'),
        ('系统级故障模式', '有', '系统级故障现象'),
        ('总体级故障模式', '有', '总体级故障现象'),
        ('单机级故障模式', '发生阶段', '属性值'),
        ('单机级故障模式', '是否单点', '属性值'),
        ('单机级故障模式', '严酷度等级', '属性值'),
        ('单机级故障模式', '发生概率', '属性值'),
        ('单机级故障模式', '设计措施', '属性值'),
    ],
    'source': 'fallback',
}


def _file_suffix(file_name: str) -> str:
    return Path(file_name or '').suffix.lower()


def _safe_file_stem(file_name: str) -> str:
    stem = Path(file_name or 'document').stem.strip() or 'document'
    safe_chars = []
    for ch in stem:
        if ch.isalnum() or ch in ('-', '_'):
            safe_chars.append(ch)
        elif '\u4e00' <= ch <= '\u9fff':
            safe_chars.append(ch)
        else:
            safe_chars.append('_')
    normalized = ''.join(safe_chars).strip('_')
    return normalized or 'document'


def _export_document_json(payload: dict, source_file_name: str) -> str:
    DOCUMENT_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    out_name = f'{_safe_file_stem(source_file_name)}_document_{timestamp}.json'
    out_path = DOCUMENT_EXPORT_DIR / out_name
    export_payload = {
        'generatedAt': datetime.now().isoformat(timespec='seconds'),
        **payload,
    }
    out_path.write_text(json.dumps(export_payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return str(out_path.relative_to(PROJECT_ROOT)).replace('\\', '/')


def _export_document_triples(payload: dict, source_file_name: str) -> str:
    DOCUMENT_TRIPLE_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    out_name = f'{_safe_file_stem(source_file_name)}_triples_{timestamp}.json'
    out_path = DOCUMENT_TRIPLE_EXPORT_DIR / out_name
    export_payload = payload
    out_path.write_text(json.dumps(export_payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return str(out_path.relative_to(PROJECT_ROOT)).replace('\\', '/')


def _llm_timeout_seconds() -> float:
    return DEFAULT_LLM_TIMEOUT_SECONDS


def _build_document_definition(ontology_constraints: dict[str, Any]) -> dict[str, Any]:
    entity_types = _unique_texts([str(item).strip() for item in (ontology_constraints.get('entityTypes') or []) if str(item).strip()])
    relation_types = _unique_texts([str(item).strip() for item in (ontology_constraints.get('relations') or []) if str(item).strip()])
    return {
        'entityDeclarations': [{'entityName': item} for item in entity_types],
        'relationDeclarations': [{'relationName': item} for item in relation_types],
        'missingOntologyPlaceholders': {
            'nodes': [],
            'relations': [],
        },
    }


def _build_structured_document_payload(
    graph_payload: dict[str, Any],
    source_file_name: str,
    declaration_payload: dict[str, Any],
) -> dict[str, Any]:
    entity_index: dict[tuple[str, str], dict[str, str]] = {}
    relation_index: dict[tuple[str, str, str], dict[str, str]] = {}
    triple_rows = list(graph_payload.get('tripleRows', []))
    structured_triples: list[dict[str, str]] = []
    entity_counter = 1
    relation_counter = 1
    triple_counter = 1

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
        predicate_id = ensure_relation(predicate, subject_type, object_type)
        object_id = ensure_entity(object_name, object_type)
        if not subject_id or not predicate_id or not object_id:
            continue

        structured_triples.append({
            'id': f'T{triple_counter:03d}',
            'subject_id': subject_id,
            'predicate_id': predicate_id,
            'object_id': object_id,
        })
        triple_counter += 1

    entities = list(entity_index.values())
    relations = list(relation_index.values())
    return {
        'fileName': source_file_name,
        'sourceType': 'document',
        'generatedAt': datetime.now().isoformat(timespec='seconds'),
        'definition': declaration_payload,
        'counts': {
            'entities': len(entities),
            'relations': len(relations),
            'triples': len(structured_triples),
        },
        'entities': entities,
        'relations': relations,
        'triples': structured_triples,
    }


def _extract_pdf_text(content: bytes) -> tuple[str, dict]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError('缺少 pypdf 依赖，无法解析 PDF 文档。') from exc

    reader = PdfReader(BytesIO(content))
    page_texts = []
    for page in reader.pages:
        page_texts.append(page.extract_text() or '')
    text = '\n\n'.join(page_texts)
    return text, {'pageCount': len(reader.pages)}


def _extract_docx_text(content: bytes) -> tuple[str, dict]:
    try:
        from docx import Document
    except ImportError as exc:
        raise RuntimeError('缺少 python-docx 依赖，无法解析 Word 文档。') from exc

    document = Document(BytesIO(content))
    paragraphs = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
    text = '\n'.join(paragraphs)
    return text, {'paragraphCount': len(paragraphs)}


def _extract_plain_text(content: bytes) -> tuple[str, dict]:
    for encoding in ('utf-8-sig', 'utf-8', 'gb18030'):
        try:
            return content.decode(encoding), {'encoding': encoding}
        except UnicodeDecodeError:
            continue
    return content.decode('utf-8', errors='replace'), {'encoding': 'utf-8-replace'}


def extract_document_text(file_name: str, content: bytes) -> tuple[str, dict]:
    suffix = _file_suffix(file_name)
    if suffix == '.pdf':
        text, meta = _extract_pdf_text(content)
    elif suffix == '.docx':
        text, meta = _extract_docx_text(content)
    elif suffix in {'.txt', '.md'}:
        text, meta = _extract_plain_text(content)
    else:
        raise ValueError('暂仅支持 PDF、DOCX、TXT、MD 文档。')

    normalized = _normalize_text(text)
    if not normalized:
        raise ValueError('未能从文档中提取到可分析文本，请确认文档不是纯扫描图片。')
    meta.update({
        'charCount': len(normalized),
        'fileType': suffix.lstrip('.') or 'unknown',
    })
    return normalized, meta


def _normalize_text(text: str) -> str:
    text = str(text or '').replace('\u3000', ' ')
    text = re.sub(r'/head\w*\s*', '', text, flags=re.IGNORECASE)
    text = _collapse_spaced_ascii(text)
    text = _collapse_repeated_fragments(text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _collapse_spaced_ascii(text: str) -> str:
    pattern = re.compile(r'(?<![A-Za-z0-9])(?:[A-Za-z0-9]\s+){2,}[A-Za-z0-9](?![A-Za-z0-9])')

    def replace(match: re.Match) -> str:
        return re.sub(r'\s+', '', match.group(0))

    return pattern.sub(replace, text)


def _collapse_repeated_fragments(text: str) -> str:
    previous = None
    current = text
    pattern = re.compile(r'([\u4e00-\u9fa5A-Za-z0-9]{2,18})(?:\1){1,}')
    while previous != current:
        previous = current
        current = pattern.sub(r'\1', current)
    return current


def _paragraphs(text: str) -> list[str]:
    raw_items = re.split(r'\n+|(?<=[。；;])', text)
    result = []
    for item in raw_items:
        clean = re.sub(r'\s+', ' ', item).strip()
        if len(clean) < 8:
            continue
        if re.search(r'\.{4,}', clean) or clean.count('.') > max(6, len(clean) // 8):
            continue
        if re.match(r'^\d+(?:\.\d+)*\s+[^。；;:：]{2,24}$', clean):
            continue
        result.append(clean)
    return result


def _unique_texts(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in values:
        text = str(item or '').strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _relation_text_zh(label: str) -> str:
    text = str(label or '').strip()
    return FRONTEND_RELATION_LABELS.get(text, text)


def _canonical_relation_label(label: str) -> str:
    text = str(label or '').strip()
    if not text:
        return ''
    for raw, zh in FRONTEND_RELATION_LABELS.items():
        if text == raw or text == zh:
            return zh
    return text


def _normalize_ontology_type(value: str) -> str:
    text = re.sub(r'\s+', '', str(value or ''))
    aliases = {
        '组件': '零部组件',
        '零部组件': '零部组件',
        '部件': '零部组件',
        '单机': '单机',
        '系统': '系统',
        '总体': '总体',
        '功能': '单机功能',
        '零部组件功能': '零部组件功能',
        '组件功能': '零部组件功能',
        '单机功能': '单机功能',
        '系统功能': '系统功能',
        '总体功能': '总体功能',
        '组件级故障模式': '组件级故障模式',
        '单机级故障模式': '单机级故障模式',
        '系统级故障模式': '系统级故障模式',
        '总体级故障模式': '总体级故障模式',
        '组件级故障现象': '组件级故障现象',
        '单机级故障现象': '单机级故障现象',
        '系统级故障现象': '系统级故障现象',
        '总体级故障现象': '总体级故障现象',
        '属性': '属性值',
        '属性值': '属性值',
        '发生阶段': '属性值',
        '是否单点': '属性值',
        '严酷度等级': '属性值',
        '发生概率': '属性值',
        '设计措施': '属性值',
    }
    return aliases.get(text, text)


def _build_ontology_constraints(ontology: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(ontology, dict):
        return dict(DOCUMENT_ONTOLOGY_FALLBACK)

    nodes = ontology.get('nodes')
    edges = ontology.get('edges')
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return dict(DOCUMENT_ONTOLOGY_FALLBACK)

    node_map: dict[str, dict[str, str]] = {}
    entity_types: list[str] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get('id') or '').strip()
        node_type = _normalize_ontology_type(str(node.get('type') or node.get('label') or '').strip())
        node_label = str(node.get('label') or node.get('name') or '').strip()
        if node_id:
            node_map[node_id] = {'type': node_type, 'label': node_label}
        if node_type:
            entity_types.append(node_type)

    relations: list[str] = []
    patterns: list[tuple[str, str, str]] = []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        source_id = str(edge.get('source') or edge.get('from') or '').strip()
        target_id = str(edge.get('target') or edge.get('to') or '').strip()
        source = node_map.get(source_id)
        target = node_map.get(target_id)
        relation = _canonical_relation_label(str(edge.get('label') or edge.get('relationType') or '').strip())
        if not source or not target or not relation:
            continue
        source_type = _normalize_ontology_type(source.get('type', ''))
        target_type = _normalize_ontology_type(target.get('type', ''))
        if not source_type or not target_type:
            continue
        relations.append(relation)
        patterns.append((source_type, relation, target_type))

    entity_types = _unique_texts(entity_types)
    relations = _unique_texts(relations)
    pattern_set = []
    seen_patterns: set[tuple[str, str, str]] = set()
    for item in patterns:
        if item in seen_patterns:
            continue
        seen_patterns.add(item)
        pattern_set.append(item)

    if not entity_types or not relations or not pattern_set:
        return dict(DOCUMENT_ONTOLOGY_FALLBACK)

    return {
        'entityTypes': entity_types,
        'relations': relations,
        'patterns': pattern_set,
        'source': 'ontology-builder',
    }


def _match_allowed_pattern(
    subject_type: str,
    predicate: str,
    object_type: str,
    constraints: dict[str, Any],
) -> tuple[str, str, str] | None:
    patterns = constraints.get('patterns') or []
    allowed_entity_types = set(constraints.get('entityTypes') or [])
    allowed_relations = set(constraints.get('relations') or [])
    subject_type = _normalize_ontology_type(subject_type)
    object_type = _normalize_ontology_type(object_type)
    predicate = _canonical_relation_label(predicate)

    if subject_type and predicate and object_type:
        candidate = (subject_type, predicate, object_type)
        if candidate in patterns:
            return candidate

    candidates = [item for item in patterns if item[1] == predicate] if predicate in allowed_relations else list(patterns)
    if subject_type in allowed_entity_types:
        exact_subject = [item for item in candidates if item[0] == subject_type]
        if exact_subject:
            candidates = exact_subject
    if object_type in allowed_entity_types:
        exact_object = [item for item in candidates if item[2] == object_type]
        if exact_object:
            candidates = exact_object

    return candidates[0] if len(candidates) == 1 else None


def _filter_triples_by_ontology(raw_triples: list[Any], constraints: dict[str, Any]) -> list[dict[str, str]]:
    triples: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for item in raw_triples:
        if not isinstance(item, dict):
            continue
        subject = _text_from_item(item, ('subject', 'head', 'source'))
        predicate = _text_from_item(item, ('predicate', 'relation'))
        obj = _text_from_item(item, ('object', 'target'))
        if not subject or not predicate or not obj:
            continue
        matched = _match_allowed_pattern(
            _text_from_item(item, ('subjectType', 'subject_type')),
            predicate,
            _text_from_item(item, ('objectType', 'object_type')),
            constraints,
        )
        if not matched:
            continue
        subject_type, predicate, object_type = matched
        key = (subject, subject_type, predicate, obj, object_type)
        if key in seen:
            continue
        seen.add(key)
        triples.append({
            'subject': subject,
            'subjectType': subject_type,
            'predicate': predicate,
            'object': obj,
            'objectType': object_type,
        })
    return triples


def _document_title(file_name: str, text: str) -> str:
    stem = Path(file_name or '').stem.strip()
    if stem:
        return stem[:80]
    for line in text.splitlines()[:12]:
        clean = re.sub(r'\s+', '', line).strip('•-— ')
        if len(clean) >= 4:
            return clean[:80]
    return Path(file_name or '文档').stem


def _infer_equipment(file_name: str, text: str) -> str:
    candidates = []
    title = _document_title(file_name, text)
    candidates.append(title)
    patterns = (
        r'([A-Za-z0-9-]+\s*系列[^，。\n]{0,16}(?:机|设备|装置|系统))',
        r'([A-Za-z0-9-]+\s*[^，。\n]{0,20}(?:机|设备|装置|系统))',
        r'([^，。\n]{2,24}(?:注塑机|设备|装置|系统))',
    )
    head = text[:5000]
    for pattern in patterns:
        for matched in re.findall(pattern, head):
            candidates.append(re.sub(r'\s+', '', matched))
    for item in candidates:
        clean = str(item or '').strip()
        if clean and '说明书' not in clean and len(clean) <= 50:
            return clean
    return Path(file_name or '设备').stem


def _summarize_by_keywords(paragraphs: list[str], keywords: tuple[str, ...], limit: int = 6) -> list[str]:
    scored = []
    for index, paragraph in enumerate(paragraphs):
        score = sum(paragraph.count(keyword) for keyword in keywords)
        if score <= 0:
            continue
        scored.append((score, -index, paragraph))
    scored.sort(reverse=True)
    return [item[2][:220] for item in scored[:limit]]


def _extract_specifications(text: str) -> list[dict]:
    specs = []
    seen = set()
    unit_pattern = r'(?:mm|cm|m|kg|g|N|kN|MPa|Pa|kW|W|V|A|Hz|℃|%|rpm|r/min)'
    for matched in re.finditer(r'([\u4e00-\u9fa5A-Za-z0-9 /_-]{2,24})[:：]?\s*([0-9]+(?:\.[0-9]+)?(?:\s*[~～-]\s*[0-9]+(?:\.[0-9]+)?)?)\s*(' + unit_pattern + r')', text):
        name = re.sub(r'\s+', '', matched.group(1)).strip('，。,;；')
        value = matched.group(2).replace(' ', '')
        unit = matched.group(3)
        key = (name, value, unit)
        if key in seen or len(name) > 24:
            continue
        seen.add(key)
        specs.append({'name': name, 'value': value, 'unit': unit})
        if len(specs) >= 8:
            break
    return specs


def _clean_fault_phrase(text: str, max_length: int = 80) -> str:
    clean = re.sub(r'\s+', ' ', str(text or '')).strip(' ，,。；;：:[]【】()（）')
    clean = re.sub(r'^(由于|因|因为|经排查|现场排查|初步判断是|判断为|发现|表明)', '', clean).strip()
    clean = re.sub(r'(最终|从而|并且|而且)$', '', clean).strip()
    if len(clean) > max_length:
        clean = clean[:max_length].rstrip(' ，,。；;：:')
    return clean


def _strip_prefix_noise(text: str) -> str:
    clean = str(text or '').strip()
    previous = None
    while previous != clean:
        previous = clean
        clean = DATE_PREFIX_PATTERN.sub('', clean)
        clean = LOCATION_PREFIX_PATTERN.sub('', clean)
        clean = re.sub(r'^(?:\d{1,2}月\d{1,2}日前|29日晚8点左右|[0-2]?\d[日号](?:晚|上午|下午|凌晨|中午)?\d{0,2}(?:点|时)?(?:左右)?)[，,、 ]*', '', clean)
        clean = re.sub(r'^(?:在)?[^，,。；;]{0,24}(?:进行|开展|完成|实施)[^，,。；;]{0,18}[，,、 ]*', '', clean)
    return clean.strip(' ，,。；;：:')


def _is_invalid_fault_phenomenon(text: str) -> bool:
    clean = _clean_fault_phrase(_strip_prefix_noise(text), max_length=120)
    if not clean:
        return True
    return any(re.fullmatch(pattern, clean) for pattern in INVALID_FAULT_PHENOMENON_PATTERNS)


def _normalize_phenomenon_text(text: str, max_length: int = 120) -> str:
    clean = _clean_fault_phrase(_strip_prefix_noise(text), max_length=max_length * 2)
    for marker in ('时发现', '后发现', '发现', '显示', '监测到'):
        if marker not in clean:
            continue
        left, right = clean.split(marker, 1)
        right = _clean_fault_phrase(right, max_length=max_length * 2)
        if right and any(hint in right for hint in FAULT_PHENOMENON_HINTS):
            clean = right
            break
    clean = re.sub(r'^该', '', clean).strip()
    parallel_devices, shared_phenomenon = _extract_parallel_devices_and_shared_phenomenon(clean, clean)
    if parallel_devices and shared_phenomenon:
        clean = shared_phenomenon
    return _clean_fault_phrase(clean, max_length=max_length)


def _normalize_cause_text(text: str, max_length: int = 180) -> str:
    clean = _clean_fault_phrase(_strip_prefix_noise(text), max_length=max_length * 2)
    if not clean:
        return ''
    parts = [_clean_fault_phrase(part, max_length=max_length) for part in re.split(r'[，,]', clean) if _clean_fault_phrase(part, max_length=max_length)]
    focused: list[str] = []
    for part in parts:
        normalized = re.sub(r'^(?:因此|所以|从而|进而|并|并且|且|而|则|会|将|导致)', '', part).strip()
        if not normalized:
            continue
        if any(hint in normalized for hint in FAULT_CAUSE_HINTS):
            focused.append(normalized)
    if focused:
        return _clean_fault_phrase('，'.join(_unique_texts(focused)), max_length=max_length)
    return _clean_fault_phrase(clean, max_length=max_length)


def _focus_cause_fragment(text: str, max_length: int = 180) -> str:
    clean = _clean_fault_phrase(_strip_prefix_noise(text), max_length=max_length * 2)
    if not clean:
        return ''
    clauses = [
        _clean_fault_phrase(part, max_length=max_length)
        for part in re.split(r'[\uFF0C,]', clean)
        if _clean_fault_phrase(part, max_length=max_length)
    ]
    if not clauses:
        return ''
    preferred_tokens = (
        '\u8d85\u8fc7',
        '\u8d85\u51fa',
        '\u672a\u7ec8\u6b62',
        '\u9519\u8bef\u89e6\u53d1',
        '\u5f15\u5165\u591a\u4f59\u7269',
        '\u526a\u65ad',
        '\u65ad\u88c2',
        '\u6cc4\u6f0f',
        '\u6545\u969c',
        '\u5f02\u5e38',
    )
    for clause in reversed(clauses):
        normalized = _normalize_cause_text(clause, max_length=max_length)
        if normalized and any(token in normalized for token in preferred_tokens):
            return normalized
    return _normalize_cause_text(clauses[-1], max_length=max_length) or _normalize_cause_text(clean, max_length=max_length)


def _build_device_alias_map(text: str) -> dict[str, str]:
    alias_map: dict[str, str] = {}
    code_pattern = r'[A-Z]{1,4}(?:-[A-Z0-9]+){1,4}|[A-Z]{1,3}\d{1,4}(?:-[A-Z0-9]+)?'
    alias_suffixes = ('电磁阀', '装置', '机构', '组件', '系统', '设备', '传感器', '模块', '摄像装置', '分机')
    grouped_pattern = re.compile(code_pattern + r'(?:[\s、，,和及与]+(?:' + code_pattern + r'))+')
    for match in grouped_pattern.finditer(text):
        codes = re.findall(code_pattern, match.group(0))
        if len(codes) < 2:
            continue
        prefix_window = text[max(0, match.start() - 40):match.start()]
        prefix = ''
        for suffix in sorted(alias_suffixes, key=len, reverse=True):
            suffix_pos = prefix_window.rfind(suffix)
            if suffix_pos == -1:
                continue
            raw_prefix = prefix_window[:suffix_pos + len(suffix)]
            raw_prefix = re.split(r'[，,。；;：:\(\)（）"]', raw_prefix)[-1]
            prefix = _normalize_equipment_name(raw_prefix)
            if prefix:
                break
        if not prefix:
            continue
        for code in codes:
            if code not in alias_map:
                alias_map[code] = _normalize_equipment_name(f'{prefix} {code}')
    return alias_map


def _extract_parallel_devices_and_shared_phenomenon(text: str, context_text: str = '') -> tuple[list[str], str]:
    clean = _clean_fault_phrase(_strip_prefix_noise(text), max_length=220)
    if not clean:
        return [], ''
    code_pattern = re.compile(r'\b[A-Z]{1,4}(?:-[A-Z0-9]+){1,4}\b|\b[A-Z]{1,3}\d{1,4}(?:-[A-Z0-9]+)?\b')
    codes = code_pattern.findall(clean)
    if len(codes) < 2:
        return [], ''
    prefix = clean.split(codes[0], 1)[0].strip(' ，,、和及与')
    last_code = codes[-1]
    tail = clean[clean.rfind(last_code) + len(last_code):].strip(' ，,、和及与·')
    phenomenon = _normalize_phenomenon_text(tail, max_length=120)
    if not phenomenon or not any(hint in phenomenon for hint in FAULT_PHENOMENON_HINTS):
        return [], ''
    alias_map = _build_device_alias_map(context_text or clean)
    devices: list[str] = []
    for code in codes:
        if prefix:
            devices.append(_normalize_equipment_name(f'{prefix} {code}'))
        else:
            devices.append(alias_map.get(code) or _normalize_equipment_name(code))
    devices = [item for item in _unique_texts(devices) if item]
    return devices if len(devices) >= 2 else [], phenomenon


def _sentence_left_bound(text: str, index: int) -> int:
    left_bound = 0
    for match in re.finditer(r'[。；;]', text):
        if match.start() < index:
            left_bound = match.end()
        else:
            break
    return left_bound


def _prefer_specific_device(current_device: str, phenomenon: str) -> str:
    current = _normalize_equipment_name(current_device)
    candidates = _extract_device_candidates(phenomenon)
    if not candidates:
        return current
    ranked = sorted(candidates, key=lambda item: (bool(re.search(r'\d', item)), len(item)), reverse=True)
    best = ranked[0]
    if not current:
        return best
    if re.fullmatch(r'[A-Z]{1,4}(?:-\d+[A-Z]?)?(?:\s+[A-Z0-9-]+)?', current) or current.startswith('CZ-'):
        return best
    if any('\u4e00' <= ch <= '\u9fff' for ch in current) and re.fullmatch(r'[A-Z]{1,4}(?:-[A-Z0-9]+){0,4}|[A-Z]{1,3}\d{1,4}', best):
        return current
    if re.search(r'\d', best) and not re.search(r'\d', current):
        return best
    return best if len(best) > len(current) + 4 else current


def _normalize_equipment_name(text: str) -> str:
    clean = _strip_prefix_noise(_clean_fault_phrase(text, max_length=80))
    clean = re.sub(r'^该', '', clean).strip()
    if '发现' in clean:
        right = clean.split('发现')[-1].strip()
        device_matches = re.findall(
            r'([A-Za-z]{1,8}[0-9][A-Za-z0-9-]*[\u4e00-\u9fa5]{0,20}(?:' + '|'.join(DEVICE_SUFFIXES) + r')|[\u4e00-\u9fa5A-Za-z0-9-]{2,30}(?:' + '|'.join(DEVICE_SUFFIXES) + r')|\b[A-Z]{1,3}\d{1,3}(?:-[A-Z0-9]+)?\b)',
            right,
        )
        if device_matches:
            clean = device_matches[-1]
    clean = re.sub(r'^(?:前期|后续|本次|该次|此次)', '', clean).strip()
    clean = re.sub(r'(?:输入|输出|异常|有问题|存在问题|进行检查)$', '', clean).strip()
    for token in GENERIC_EQUIPMENT_TOKENS:
        if token in clean and not clean.endswith(token):
            tail = clean.split(token)[-1].strip()
            if tail:
                clean = tail
    for term in sorted(EXTRA_DEVICE_TERMS, key=len, reverse=True):
        if term in clean:
            clean = term
            break
    return _clean_fault_phrase(clean, max_length=48)


def _is_invalid_equipment_phrase(text: str) -> bool:
    clean = _normalize_equipment_name(text)
    if not clean:
        return True
    invalid_tokens = (
        '\u6d4b\u8bd5',
        '\u8bd5\u9a8c',
        '\u68c0\u67e5',
        '\u56de\u653e',
        '\u53d1\u73b0',
        '\u5f00\u5c55',
        '\u8fdb\u884c',
        '\u6267\u884c',
        '\u53c2\u6570',
        '\u6570\u636e',
        '\u6d41\u7a0b',
        '\u5de5\u5e8f',
        '\u6280\u672f\u533a',
    )
    invalid_suffixes = (
        '\u6d4b\u8bd5',
        '\u8bd5\u9a8c',
        '\u68c0\u67e5',
        '\u56de\u653e',
        '\u6d41\u7a0b',
        '\u5de5\u5e8f',
    )
    if '\u6280\u672f\u533a' in clean:
        return True
    if clean.endswith(invalid_suffixes):
        return True
    return any(token in clean for token in invalid_tokens) and not any(suffix in clean for suffix in DEVICE_SUFFIXES)


def _is_specific_equipment(text: str) -> bool:
    clean = _normalize_equipment_name(text)
    if len(clean) < 2:
        return False
    if any(token in clean for token in ('手动', '测试', '检查', '工装', '重复动作', '左右')):
        return False
    if _is_invalid_equipment_phrase(clean):
        return False
    if any(token in clean for token in GENERIC_EQUIPMENT_TOKENS):
        return False
    if re.search(r'(?:年|月|日|km|MPa|℃)$', clean):
        return False
    if clean.endswith(('有问题', '异常', '情况', '任务', '过程', '检查', '输入', '输出')):
        return False
    return bool(
        any(suffix in clean for suffix in DEVICE_SUFFIXES)
        or clean in EXTRA_DEVICE_TERMS
        or re.fullmatch(r'[A-Z]{1,4}\d{1,3}(?:-[A-Z0-9]+)?', clean)
        or clean in {'RTK', 'GNSS', 'GPS', 'B1', 'B2', 'B3', 'B4'}
    )


def _normalize_fault_chain_summary(file_name: str, text: str, raw: dict | None = None) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    return {
        'documentName': str(raw.get('documentName') or _document_title(file_name, text)).strip(),
        'equipment': str(raw.get('equipment') or '').strip(),
        'equipmentItems': _as_list(raw.get('equipmentItems')),
        'phenomena': _as_list(raw.get('phenomena')),
        'causes': _as_list(raw.get('causes')),
        'functions': [],
        'features': [],
        'maintenance': [],
        'faultTypes': _as_list(raw.get('faultTypes')),
        'safetyNotes': [],
        'specifications': [],
        'triples': _as_list(raw.get('triples')),
    }


def _normalize_match_text(value: Any) -> str:
    text = str(value or '').strip()
    if not text:
        return ''
    text = re.sub(r'\s+', '', text)
    return re.sub(r'[^0-9A-Za-z\u4e00-\u9fff]+', '', text).upper()


def _device_glossary_paths() -> list[Path]:
    candidates: list[Path] = []
    for key in DEVICE_GLOSSARY_ENV_KEYS:
        raw = os.environ.get(key, '').strip()
        if raw:
            candidates.append(Path(raw))
    candidates.extend(DEFAULT_DEVICE_GLOSSARY_PATHS)
    seen: set[str] = set()
    unique: list[Path] = []
    for path in candidates:
        identity = str(path).strip().lower()
        if not identity or identity in seen:
            continue
        seen.add(identity)
        unique.append(path)
    return unique


def _decode_text_with_fallback(raw: bytes) -> str:
    for encoding in ('utf-8-sig', 'utf-8', 'gb18030', 'gbk', 'utf-16'):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode('utf-8', errors='ignore')


@lru_cache(maxsize=1)
def _load_device_glossary() -> tuple[str, ...]:
    for path in _device_glossary_paths():
        try:
            if not path.exists():
                continue
            raw = path.read_bytes()
        except OSError:
            continue
        lines = [
            str(item).strip()
            for item in _decode_text_with_fallback(raw).splitlines()
            if str(item).strip()
        ]
        if lines:
            return tuple(lines)
    return ()


def _extract_device_codes(text: str) -> list[str]:
    code_pattern = re.compile(r'\b(?:[A-Z]{1,4}(?:-[A-Z0-9]+){1,4}|[A-Z]{1,4}\d{1,4}(?:-[A-Z0-9]+)?)\b')
    return [code.upper() for code in code_pattern.findall(str(text or '').upper())]


def _choose_glossary_match(device_name: str, glossary: tuple[str, ...]) -> str:
    clean_name = str(device_name or '').strip()
    if not clean_name or not glossary:
        return ''

    normalized_name = _normalize_match_text(clean_name)
    codes = _extract_device_codes(clean_name)
    if codes:
        exact_code_matches = []
        for entry in glossary:
            normalized_entry = _normalize_match_text(entry)
            if not normalized_entry:
                continue
            if all(code in normalized_entry for code in codes):
                exact_code_matches.append(entry)
        if len(exact_code_matches) == 1:
            return exact_code_matches[0]
        if len(exact_code_matches) > 1 and len(codes) == 1 and normalized_name == codes[0]:
            return clean_name

    scored: list[tuple[int, int, int, str]] = []
    for entry in glossary:
        normalized_entry = _normalize_match_text(entry)
        if not normalized_entry:
            continue

        score = 0
        if normalized_entry == normalized_name:
            score += 1000
        if normalized_name and normalized_name in normalized_entry:
            score += 300
        if normalized_entry and normalized_entry in normalized_name:
            score += 220

        for code in codes:
            if code in normalized_entry:
                score += 260
                if normalized_entry.endswith(code):
                    score += 80

        if clean_name in entry:
            score += 120
        if not score:
            continue
        scored.append((score, len(entry), -len(clean_name), entry))

    if not scored:
        return ''
    scored.sort(reverse=True)
    return scored[0][3]


def _apply_device_glossary_mapping(summary: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    glossary = _load_device_glossary()
    if not glossary:
        return summary, []

    mapped = _normalize_fault_chain_summary('', '', summary)
    applied_mappings: list[dict[str, str]] = []
    mapping_index: dict[str, str] = {}

    def map_device(name: Any) -> str:
        clean_name = _normalize_equipment_name(name)
        if not clean_name:
            return ''
        if clean_name in mapping_index:
            return mapping_index[clean_name]
        matched = _choose_glossary_match(clean_name, glossary) or clean_name
        mapping_index[clean_name] = matched
        if matched != clean_name:
            applied_mappings.append({'source': clean_name, 'target': matched})
        return matched

    mapped['equipment'] = map_device(summary.get('equipment'))

    equipment_items: list[dict[str, str]] = []
    seen_equipment: set[str] = set()
    for item in _as_list(summary.get('equipmentItems')):
        name = map_device(item.get('name') if isinstance(item, dict) else item)
        if not name or name in seen_equipment:
            continue
        seen_equipment.add(name)
        equipment_items.append({
            'name': name,
            'evidence': _text_from_item(item, ('evidence', 'name')),
        })
    mapped['equipmentItems'] = equipment_items

    phenomena: list[dict[str, str]] = []
    for item in _as_list(summary.get('phenomena')):
        if not isinstance(item, dict):
            continue
        phenomena.append({
            'name': _clean_fault_phrase(item.get('name') or item.get('phenomenon'), max_length=80),
            'device': map_device(item.get('device')),
            'evidence': _text_from_item(item, ('evidence', 'name', 'phenomenon')),
        })
    mapped['phenomena'] = phenomena

    causes: list[dict[str, str]] = []
    for item in _as_list(summary.get('causes')):
        if not isinstance(item, dict):
            continue
        causes.append({
            'name': _clean_fault_phrase(item.get('name') or item.get('cause'), max_length=80),
            'phenomenon': _clean_fault_phrase(item.get('phenomenon'), max_length=80),
            'evidence': _text_from_item(item, ('evidence', 'name', 'cause')),
        })
    mapped['causes'] = causes

    fault_types: list[dict[str, str]] = []
    for item in _as_list(summary.get('faultTypes')):
        if not isinstance(item, dict):
            continue
        fault_types.append({
            'device': map_device(item.get('device') or item.get('equipment')),
            'fault': _clean_fault_phrase(item.get('phenomenon') or item.get('fault'), max_length=80),
            'phenomenon': _clean_fault_phrase(item.get('phenomenon') or item.get('fault'), max_length=80),
            'cause': _clean_fault_phrase(item.get('cause') or item.get('reason'), max_length=80),
            'handling': _text_from_item(item, ('handling',)),
            'evidence': _text_from_item(item, ('evidence', 'fault', 'phenomenon')),
        })
    mapped['faultTypes'] = fault_types

    if not mapped.get('equipment') and mapped['equipmentItems']:
        mapped['equipment'] = mapped['equipmentItems'][0]['name']
    return mapped, applied_mappings


def _choose_shorter_text(left: str, right: str) -> str:
    left = _clean_fault_phrase(left, max_length=80)
    right = _clean_fault_phrase(right, max_length=80)
    if not left:
        return right
    if not right:
        return left
    return left if len(left) <= len(right) else right


def _build_merged_display_text(canonical: str, variants: list[str]) -> str:
    canonical = _clean_fault_phrase(canonical, max_length=80)
    clean_variants = _unique_texts([
        _clean_fault_phrase(item, max_length=80)
        for item in variants
        if _clean_fault_phrase(item, max_length=80)
    ])
    if not canonical:
        return clean_variants[0] if clean_variants else ''
    explanations = [item for item in clean_variants if item and item != canonical]
    if not explanations:
        return canonical
    return f"{canonical}（{'、'.join(explanations)}）"


def _normalize_semantic_compare_text(value: str) -> str:
    text = _clean_fault_phrase(value, max_length=80)
    if not text:
        return ''
    replacements = (
        ('内部存在较多液态水', '内部积水'),
        ('存在较多液态水', '积水'),
        ('液态水', '积水'),
        ('有水流出', '漏水'),
        ('存在问题', '有问题'),
        ('出现问题', '有问题'),
        ('发生问题', '有问题'),
        ('未可靠锁定', '锁定异常'),
        ('无法可靠锁定', '锁定异常'),
    )
    for source, target in replacements:
        text = text.replace(source, target)
    text = re.sub(r'(?:内部存在|内部有|内部出现)', '内部', text)
    text = re.sub(r'(?:存在|出现|发生|较多|明显|一定程度的?)', '', text)
    text = re.sub(r'\s+', '', text)
    return text


def _heuristic_semantic_alias_map(values: list[str]) -> dict[str, str]:
    clean_values = [_clean_fault_phrase(item, max_length=80) for item in values if _clean_fault_phrase(item, max_length=80)]
    alias_map = {item: item for item in clean_values}
    for i, left in enumerate(clean_values):
        normalized_left = _normalize_match_text(_normalize_semantic_compare_text(left))
        for right in clean_values[i + 1:]:
            normalized_right = _normalize_match_text(_normalize_semantic_compare_text(right))
            if not normalized_left or not normalized_right:
                continue
            if normalized_left == normalized_right or normalized_left in normalized_right or normalized_right in normalized_left:
                keep = _choose_shorter_text(left, right)
                alias_map[left] = keep
                alias_map[right] = keep
    return alias_map


def _build_group_display_map(values: list[str], alias_map: dict[str, str]) -> dict[str, str]:
    clean_values = _unique_texts([
        _clean_fault_phrase(item, max_length=80)
        for item in values
        if _clean_fault_phrase(item, max_length=80)
    ])
    grouped_variants: dict[str, list[str]] = {}
    for item in clean_values:
        canonical = _clean_fault_phrase(alias_map.get(item, item), max_length=80) or item
        grouped_variants.setdefault(canonical, []).append(item)
    display_map: dict[str, str] = {}
    for canonical, variants in grouped_variants.items():
        display = _build_merged_display_text(canonical, variants)
        display_map[canonical] = display
        for variant in variants:
            display_map[variant] = display
    return display_map


def _find_matching_group_alias_maps(
    evidence: str,
    phrase: str,
    grouped_aliases: dict[tuple[str, str], dict[str, str]],
    grouped_displays: dict[tuple[str, str], dict[str, str]],
) -> tuple[dict[str, str], dict[str, str]]:
    normalized_phrase = _normalize_match_text(_normalize_semantic_compare_text(phrase))
    for (group_evidence, group_phrase), alias_map in grouped_aliases.items():
        if group_evidence != evidence:
            continue
        if phrase == group_phrase:
            return alias_map, grouped_displays.get((group_evidence, group_phrase), {})
        normalized_group = _normalize_match_text(_normalize_semantic_compare_text(group_phrase))
        if normalized_phrase and normalized_group and normalized_phrase == normalized_group:
            return alias_map, grouped_displays.get((group_evidence, group_phrase), {})
    return {}, {}


def _llm_merge_same_meaning_terms(
    file_name: str,
    category: str,
    group_key: str,
    candidates: list[str],
) -> tuple[dict[str, str], str]:
    api_key, base_url, model = _llm_config()
    clean_candidates = [_clean_fault_phrase(item, max_length=80) for item in candidates if _clean_fault_phrase(item, max_length=80)]
    unique_candidates = _unique_texts(clean_candidates)
    if len(unique_candidates) < 2:
        return {item: item for item in unique_candidates}, ''
    if not base_url:
        return _heuristic_semantic_alias_map(unique_candidates), '未配置 LLM_BASE_URL，已使用启发式语义合并。'
    if not url_allowed_in_offline(base_url):
        return _heuristic_semantic_alias_map(unique_candidates), f'离线模式禁止访问大模型接口：{base_url}'
    if not api_key and not offline_enabled():
        return _heuristic_semantic_alias_map(unique_candidates), '未配置 LLM_API_KEY 或 OPENAI_API_KEY，已使用启发式语义合并。'

    prompt = f"""你是故障知识抽取清洗助手。
下面这些{category}都来自同一段文字、同一上下文，请判断哪些表达语义一致。
要求：
1. 只有在语义明确一致时才合并，不一致必须保留。
2. 如果语义一致，优先保留更短、更直接的表达。
3. 输出单个 JSON 对象，不要解释。

文档名：{file_name}
上下文键：{group_key}
候选列表：{json.dumps(unique_candidates, ensure_ascii=False)}

输出格式：
{{
  "mappings": [
    {{"source": "原始短语", "target": "保留短语"}}
  ]
}}
"""
    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': '你只能输出单个合法 JSON 对象。'},
            {'role': 'user', 'content': prompt},
        ],
        'temperature': 0,
        'response_format': {'type': 'json_object'},
    }
    data, error_message = _post_llm_chat_completion(api_key, base_url, payload)
    if error_message:
        return _heuristic_semantic_alias_map(unique_candidates), error_message
    content = _extract_message_content(data or {})
    try:
        parsed = _extract_json_object(content)
    except (json.JSONDecodeError, TypeError) as exc:
        return _heuristic_semantic_alias_map(unique_candidates), f'语义合并结果解析失败：{exc}'

    alias_map = {item: item for item in unique_candidates}
    for item in _as_list(parsed.get('mappings')):
        if not isinstance(item, dict):
            continue
        source = _clean_fault_phrase(item.get('source'), max_length=80)
        target = _clean_fault_phrase(item.get('target'), max_length=80)
        if source in alias_map and target:
            alias_map[source] = target if target in alias_map else _choose_shorter_text(source, target)
    for item in unique_candidates:
        alias_map[item] = _choose_shorter_text(item, alias_map.get(item, item))
    return alias_map, ''


def _merge_same_paragraph_fault_terms(file_name: str, summary: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    merged = _normalize_fault_chain_summary(file_name, '', summary)
    messages: list[str] = []

    phenomenon_aliases: dict[tuple[str, str], dict[str, str]] = {}
    phenomenon_displays: dict[tuple[str, str], dict[str, str]] = {}
    phenomenon_groups: dict[tuple[str, str], list[str]] = {}
    for item in _as_list(summary.get('phenomena')):
        if not isinstance(item, dict):
            continue
        evidence = _text_from_item(item, ('evidence',))
        device = _normalize_equipment_name(item.get('device'))
        name = _clean_fault_phrase(item.get('name') or item.get('phenomenon'), max_length=80)
        if evidence and device and name:
            phenomenon_groups.setdefault((evidence, device), []).append(name)
    for key, names in phenomenon_groups.items():
        if len(_unique_texts(names)) < 2:
            continue
        alias_map, message = _llm_merge_same_meaning_terms(file_name, '故障现象', f'设备={key[1]}', names)
        phenomenon_aliases[key] = alias_map
        phenomenon_displays[key] = _build_group_display_map(names, alias_map)
        if message:
            messages.append(message)

    cause_aliases: dict[tuple[str, str], dict[str, str]] = {}
    cause_displays: dict[tuple[str, str], dict[str, str]] = {}
    cause_groups: dict[tuple[str, str], list[str]] = {}
    for item in _as_list(summary.get('causes')):
        if not isinstance(item, dict):
            continue
        evidence = _text_from_item(item, ('evidence',))
        phenomenon = _clean_fault_phrase(item.get('phenomenon'), max_length=80)
        name = _clean_fault_phrase(item.get('name') or item.get('cause'), max_length=80)
        if evidence and phenomenon and name:
            cause_groups.setdefault((evidence, phenomenon), []).append(name)
    for key, names in cause_groups.items():
        if len(_unique_texts(names)) < 2:
            continue
        alias_map, message = _llm_merge_same_meaning_terms(file_name, '故障原因', f'现象={key[1]}', names)
        cause_aliases[key] = alias_map
        cause_displays[key] = _build_group_display_map(names, alias_map)
        if message:
            messages.append(message)

    merged_phenomena: list[dict[str, str]] = []
    seen_phenomena: set[tuple[str, str]] = set()
    for item in _as_list(summary.get('phenomena')):
        if not isinstance(item, dict):
            continue
        evidence = _text_from_item(item, ('evidence',))
        device = _normalize_equipment_name(item.get('device'))
        raw_name = _clean_fault_phrase(item.get('name') or item.get('phenomenon'), max_length=80)
        alias_map = phenomenon_aliases.get((evidence, device), {})
        display_map = phenomenon_displays.get((evidence, device), {})
        canonical_name = alias_map.get(raw_name, raw_name)
        name = display_map.get(raw_name) or display_map.get(canonical_name) or canonical_name
        key = (device, name)
        if not device or not name or key in seen_phenomena:
            continue
        seen_phenomena.add(key)
        merged_phenomena.append({'name': name, 'device': device, 'evidence': evidence})
    merged['phenomena'] = merged_phenomena

    merged_causes: list[dict[str, str]] = []
    seen_causes: set[tuple[str, str]] = set()
    for item in _as_list(summary.get('causes')):
        if not isinstance(item, dict):
            continue
        evidence = _text_from_item(item, ('evidence',))
        raw_phenomenon = _clean_fault_phrase(item.get('phenomenon'), max_length=80)
        phenomenon = raw_phenomenon
        if evidence:
            for (group_evidence, group_device), alias_map in phenomenon_aliases.items():
                if group_evidence != evidence:
                    continue
                canonical_phenomenon = alias_map.get(phenomenon, phenomenon)
                display_map = phenomenon_displays.get((group_evidence, group_device), {})
                phenomenon = display_map.get(phenomenon) or display_map.get(canonical_phenomenon) or canonical_phenomenon
        name = _clean_fault_phrase(item.get('name') or item.get('cause'), max_length=80)
        cause_alias_map, cause_display_map = _find_matching_group_alias_maps(
            evidence,
            raw_phenomenon,
            cause_aliases,
            cause_displays,
        )
        canonical_name = cause_alias_map.get(name, name)
        name = cause_display_map.get(name) or cause_display_map.get(canonical_name) or canonical_name
        key = (phenomenon, name)
        if not phenomenon or not name or key in seen_causes:
            continue
        seen_causes.add(key)
        merged_causes.append({'name': name, 'phenomenon': phenomenon, 'evidence': evidence})
    merged['causes'] = merged_causes

    merged_fault_types: list[dict[str, str]] = []
    seen_fault_types: set[tuple[str, str, str]] = set()
    for item in _as_list(summary.get('faultTypes')):
        if not isinstance(item, dict):
            continue
        evidence = _text_from_item(item, ('evidence',))
        device = _normalize_equipment_name(item.get('device') or item.get('equipment'))
        raw_phenomenon = _clean_fault_phrase(item.get('phenomenon') or item.get('fault'), max_length=80)
        phenomenon_alias_map = phenomenon_aliases.get((evidence, device), {})
        phenomenon_display_map = phenomenon_displays.get((evidence, device), {})
        canonical_phenomenon = phenomenon_alias_map.get(raw_phenomenon, raw_phenomenon)
        phenomenon = phenomenon_display_map.get(raw_phenomenon) or phenomenon_display_map.get(canonical_phenomenon) or canonical_phenomenon
        raw_cause = _clean_fault_phrase(item.get('cause') or item.get('reason'), max_length=80)
        cause_alias_map, cause_display_map = _find_matching_group_alias_maps(
            evidence,
            raw_phenomenon,
            cause_aliases,
            cause_displays,
        )
        canonical_cause = cause_alias_map.get(raw_cause, raw_cause)
        cause = cause_display_map.get(raw_cause) or cause_display_map.get(canonical_cause) or canonical_cause
        key = (device, phenomenon, cause)
        if not device or not phenomenon or key in seen_fault_types:
            continue
        seen_fault_types.add(key)
        merged_fault_types.append({
            'device': device,
            'fault': phenomenon,
            'phenomenon': phenomenon,
            'cause': cause,
            'handling': _text_from_item(item, ('handling',)),
            'evidence': evidence,
        })
    merged['faultTypes'] = merged_fault_types
    return merged, _unique_texts([message for message in messages if message])


def _extract_leading_device(clause: str) -> tuple[str, str]:
    text = _clean_fault_phrase(clause, max_length=120)
    if not text:
        return '', ''
    candidates = _extract_device_candidates(text)
    if candidates:
        for candidate in sorted(candidates, key=len, reverse=True):
            if text.startswith(candidate):
                rest = _clean_fault_phrase(text[len(candidate):], max_length=80)
                return candidate, rest or text
    for token in ('RTK', 'GNSS', 'GPS', 'B1', 'B2', 'B3', 'B4'):
        if text.startswith(token):
            rest = _clean_fault_phrase(text[len(token):], max_length=80)
            return token, rest or text
    return '', text


def _extract_device_candidates(paragraph: str) -> list[str]:
    candidates: list[str] = []
    for term in sorted(EXTRA_DEVICE_TERMS, key=len, reverse=True):
        if term in paragraph and term not in candidates:
            candidates.append(term)
    for suffix in sorted(DEVICE_SUFFIXES, key=len, reverse=True):
        search_from = 0
        while True:
            index = paragraph.find(suffix, search_from)
            if index == -1:
                break
            left_bound = max(
                paragraph.rfind('，', 0, index),
                paragraph.rfind(',', 0, index),
                paragraph.rfind('。', 0, index),
                paragraph.rfind('；', 0, index),
                paragraph.rfind(';', 0, index),
            ) + 1
            snippet = paragraph[left_bound:index + len(suffix)]
            snippet = re.split(r'[\uff08(]', snippet, maxsplit=1)[0]
            snippet_matches = re.findall(r'[\u4e00-\u9fa5A-Za-z0-9-]{2,40}$', snippet)
            if snippet_matches:
                item = _normalize_equipment_name(snippet_matches[-1])
                if item and item not in candidates and not _is_invalid_equipment_phrase(item):
                    candidates.append(item)
            search_from = index + len(suffix)
    discovery_patterns = (
        r'发现(?P<device>[^，,。；;（）()]{2,60}?(?:传感器|阀门|活门|装置|机构|组件|电箱|系统|设备|连接器|密封带))',
        r'(?P<device>[^，,。；;（）()]{2,60}?(?:传感器|阀门|活门|装置|机构|组件|电箱|系统|设备|连接器|密封带))的参数',
    )
    for pattern in discovery_patterns:
        for match in re.finditer(pattern, paragraph):
            item = _normalize_equipment_name(match.group('device'))
            if not item or item in candidates or _is_invalid_equipment_phrase(item):
                continue
            candidates.append(item)
    patterns = [
        r'([A-Za-z]{1,8}[0-9][A-Za-z0-9-]*[\u4e00-\u9fa5]{0,20}(?:' + '|'.join(DEVICE_SUFFIXES) + r'))',
        r'([\u4e00-\u9fa5A-Za-z0-9-]{2,30}(?:' + '|'.join(DEVICE_SUFFIXES) + r'))',
        r'\b([A-Z]{1,4}(?:-[A-Z0-9]+){1,4}|[A-Z]{1,4}\d{1,4}(?:-[A-Z0-9]+)?)\b',
    ]
    for pattern in patterns:
        for match in re.findall(pattern, paragraph):
            item = _normalize_equipment_name(match)
            if not item or item in candidates:
                continue
            if item in {'RTK', 'CZ', 'X1'}:
                continue
            candidates.append(item)
    filtered: list[str] = []
    for item in candidates:
        if any(token in item for token in ('手动', '测试', '检查', '工装', '重复动作', '左右')):
            continue
        if _is_invalid_equipment_phrase(item):
            continue
        if any(item != other and item in other for other in candidates):
            continue
        filtered.append(item)
    return filtered


def _pick_primary_device(paragraph: str, candidates: list[str]) -> str:
    if not candidates:
        return ''
    for candidate in candidates:
        if candidate in paragraph and any(suffix in candidate for suffix in DEVICE_SUFFIXES):
            return candidate
    return candidates[0]


def _split_fault_cause_and_phenomenon(paragraph: str) -> tuple[str, str]:
    text = str(paragraph or '').strip()
    for marker in FAULT_CAUSE_MARKERS:
        if marker not in text:
            continue
        left, right = text.split(marker, 1)
        cause = _focus_cause_fragment(left)
        phenomenon = _clean_fault_phrase(re.split(r'[。；;]', right, maxsplit=1)[0])
        if cause and phenomenon:
            return cause, phenomenon
    return '', ''


def _extract_direct_phenomenon(paragraph: str) -> str:
    clauses = [item.strip() for item in re.split(r'[，,。；;]', paragraph) if item.strip()]
    for clause in clauses:
        normalized = _normalize_phenomenon_text(clause)
        if any(hint in normalized for hint in FAULT_PHENOMENON_HINTS) and not _is_invalid_fault_phenomenon(normalized):
            return normalized
    return ''


def _prefer_result_like_phenomenon(paragraph: str, current: str) -> str:
    current_text = _normalize_phenomenon_text(current, max_length=120) if current else ''
    clauses = [item.strip() for item in re.split(r'[锛?銆傦紱;]', str(paragraph or '')) if item.strip()]
    best = current_text
    best_score = -10**9 if not current_text else 0
    for index, clause in enumerate(clauses):
        normalized = _normalize_phenomenon_text(clause, max_length=120)
        if not normalized or _is_invalid_fault_phenomenon(normalized):
            continue
        if not any(hint in normalized for hint in FAULT_PHENOMENON_HINTS):
            continue
        candidate = normalized
        score = index * 2
        if index > 0 and '突变' in normalized:
            previous = _normalize_phenomenon_text(clauses[index - 1], max_length=120)
            if previous and any(token in previous for token in ('漏率', '漏气量', '设计要求')):
                candidate = f'{previous}，{normalized}'
                score += 8
        if '突变' in normalized:
            score += 20
        if '漏率' in normalized or '漏气量' in normalized:
            score += 12
        if '满足设计要求' in normalized and '突变' in normalized:
            score += 10
        if '检查' in normalized and '漏气量' in normalized:
            score -= 30
        if any(token in normalized for token in ('手动', '检查', '测试发现', '重复动作', '工装', '合格后', '开展')):
            score -= 18
        if score > best_score:
            best = candidate
            best_score = score
    return best


def _extract_fault_links_from_paragraph(paragraph: str) -> list[dict[str, str]]:
    text = str(paragraph or '').strip()
    if not text:
        return []

    links: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    def append_link(device: str, cause: str, phenomenon: str, marker: str) -> None:
        clean_device = _clean_fault_phrase(device, max_length=48)
        clean_cause = _clean_fault_phrase(_strip_prefix_noise(cause), max_length=120)
        clean_phenomenon = _normalize_phenomenon_text(phenomenon, max_length=120)
        if not clean_cause or not clean_phenomenon or _is_invalid_fault_phenomenon(clean_phenomenon):
            return
        key = (clean_device, clean_cause, clean_phenomenon)
        if key in seen:
            return
        seen.add(key)
        links.append({
            'device': clean_device,
            'cause': clean_cause,
            'phenomenon': clean_phenomenon,
            'marker': marker,
        })

    for pattern in FAULT_STATE_CAUSE_PATTERNS:
        for match in re.finditer(pattern, text):
            cause_clause = _clean_fault_phrase(match.group('cause'), max_length=120)
            phenomenon_clause = _clean_fault_phrase(match.group('phenomenon'), max_length=120)
            if not cause_clause or not phenomenon_clause:
                continue
            if not any(hint in phenomenon_clause for hint in FAULT_PHENOMENON_HINTS):
                continue
            device, cause = _extract_leading_device(cause_clause)
            if not cause:
                cause = cause_clause
            append_link(device, cause, phenomenon_clause, 'state-pattern')

    clauses = [item.strip() for item in re.split(r'[，,。；;]', text) if item.strip()]
    if len(clauses) >= 2:
        for idx in range(len(clauses) - 1):
            cause_clause = _clean_fault_phrase(_strip_prefix_noise(clauses[idx]), max_length=120)
            phenomenon_clause = _normalize_phenomenon_text(clauses[idx + 1], max_length=120)
            if not cause_clause or not phenomenon_clause:
                continue
            if _is_invalid_fault_phenomenon(phenomenon_clause):
                continue
            if not any(hint in cause_clause for hint in FAULT_CAUSE_HINTS):
                continue
            if not any(hint in phenomenon_clause for hint in FAULT_PHENOMENON_HINTS):
                continue
            if any(marker in phenomenon_clause[:4] for marker in FAULT_CAUSE_MARKERS):
                continue
            device, _ = _extract_leading_device(cause_clause)
            if not device:
                next_devices = _extract_device_candidates(clauses[idx + 1])
                if next_devices:
                    device = sorted(next_devices, key=len, reverse=True)[0]
            append_link(device, cause_clause, phenomenon_clause, 'sequential')

    marker_pattern = re.compile('|'.join(map(re.escape, FAULT_CAUSE_MARKERS)))
    matches = list(marker_pattern.finditer(text))
    if not matches:
        return links

    punctuation_positions = sorted({match.start() for match in re.finditer(r'[，,。；;]', text)})

    for idx, match in enumerate(matches):
        start = match.start()
        end = match.end()
        sentence_left = _sentence_left_bound(text, start)

        left_bound = 0
        for pos in punctuation_positions:
            if pos < start:
                left_bound = pos + 1
            else:
                break

        right_bound = len(text)
        for pos in punctuation_positions:
            if pos > end:
                right_bound = pos
                break
        if idx + 1 < len(matches):
            right_bound = min(right_bound, matches[idx + 1].start())
        sentence_right = len(text)
        sentence_end_match = re.search(r'[銆傦紱;]', text[end:])
        if sentence_end_match:
            sentence_right = end + sentence_end_match.start()

        cause_clause = _focus_cause_fragment(text[left_bound:start], max_length=120)
        sentence_cause_clause = _focus_cause_fragment(text[sentence_left:start], max_length=180)
        phenomenon_clause = _clean_fault_phrase(text[end:right_bound], max_length=120)
        sentence_phenomenon_clause = _clean_fault_phrase(text[end:sentence_right], max_length=160)
        cause_clause = re.sub(r'^(而|并|并且|且|最终|从而|由于)', '', cause_clause).strip()
        phenomenon_clause = re.sub(r'^(而|并|并且|且|则|将|会|最终)', '', phenomenon_clause).strip()
        sentence_phenomenon_clause = re.sub(r'^[,，、\s]+', '', sentence_phenomenon_clause).strip()
        if not cause_clause:
            previous_marks = [pos for pos in punctuation_positions if pos < left_bound - 1]
            previous_left = (previous_marks[-1] + 1) if previous_marks else 0
            cause_clause = _focus_cause_fragment(text[previous_left:start], max_length=120)
            cause_clause = re.sub(r'^(而|并|并且|且|最终|从而|由于)', '', cause_clause).strip()
        if sentence_phenomenon_clause and any(
            token in sentence_phenomenon_clause for token in ('出现', '最终', '锁定在', '未可靠锁定', '安全阀开启')
        ):
            phenomenon_clause = sentence_phenomenon_clause
        if not cause_clause or not phenomenon_clause:
            continue

        parallel_devices, shared_phenomenon = _extract_parallel_devices_and_shared_phenomenon(phenomenon_clause, text)
        if parallel_devices and shared_phenomenon:
            shared_cause = sentence_cause_clause or _normalize_cause_text(cause_clause, max_length=180)
            if not shared_cause or any(marker in shared_cause for marker in FAULT_CAUSE_MARKERS):
                continue
            for parallel_device in parallel_devices:
                append_link(parallel_device, shared_cause, shared_phenomenon, f'{match.group(0)}-parallel')
            continue

        device, cause = _extract_leading_device(cause_clause)
        if device and cause and len(cause) < len(cause_clause) and any(token in cause_clause for token in ('超过', '超出', '未终止', '错误触发')):
            cause = cause_clause
        if not device:
            nearby_devices = _extract_device_candidates(text[left_bound:right_bound])
            if nearby_devices:
                device = sorted(nearby_devices, key=len, reverse=True)[0]
                if cause_clause.startswith(device):
                    cause = _normalize_cause_text(cause_clause.replace(device, '', 1), max_length=180)
                else:
                    cause = _normalize_cause_text(cause_clause, max_length=180)
            else:
                cause = sentence_cause_clause or cause_clause

        if not cause:
            cause = sentence_cause_clause or cause_clause
        if any(marker in cause for marker in FAULT_CAUSE_MARKERS):
            continue

        append_link(device, cause, phenomenon_clause, match.group(0))

    return links


def _extract_inspection_fault_links_from_paragraph(paragraph: str) -> list[dict[str, str]]:
    text = str(paragraph or '').strip()
    if not text:
        return []

    links: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    cause = ''
    cause_match = re.search(
        r'(?:\u521d\u6b65\u5224\u65ad\u662f|\u5224\u65ad\u4e3a|\u539f\u56e0\u4e3a|\u7531\u4e8e|\u56e0\u4e3a)([^。；;]+)',
        text,
    )
    if cause_match:
        cause = _clean_fault_phrase(cause_match.group(1), max_length=100)

    affected_devices: list[str] = []

    def add_link(device: str, phenomenon: str) -> None:
        normalized_device = _normalize_equipment_name(device)
        normalized_phenomenon = _clean_fault_phrase(phenomenon, max_length=80)
        if not _is_specific_equipment(normalized_device) or not normalized_phenomenon:
            return
        key = (normalized_device, normalized_phenomenon, cause)
        if key in seen:
            return
        seen.add(key)
        if normalized_device not in affected_devices:
            affected_devices.append(normalized_device)
        links.append({
            'device': normalized_device,
            'cause': cause,
            'phenomenon': normalized_phenomenon,
            'marker': 'inspection',
        })

    leak_match = re.search(
        r'\u4ece(?P<devices>[^，,。；;]+?)\u7f1d\u9699\u4e2d\u6709[^，,。；;]{0,12}\u6c34\u6d41\u51fa',
        text,
    )
    if leak_match:
        raw_devices = re.split(r'[\u4e0e\u548c\u53ca/]', leak_match.group('devices'))
        for raw_device in raw_devices:
            device = _clean_fault_phrase(raw_device, max_length=48)
            if device:
                add_link(device, '\u7f1d\u9699\u6f0f\u6c34')

    cavity_match = re.search(
        r'\u68c0\u67e5(?P<devices>[^，,。；;]+?)\u7684\u79ef\u6c34\u60c5\u51b5',
        text,
    )
    if cavity_match:
        raw_devices = re.split(r'[\u4e0e\u548c\u53ca/]', cavity_match.group('devices'))
        for raw_device in raw_devices:
            device = _clean_fault_phrase(raw_device, max_length=48)
            if device:
                add_link(device, '\u5185\u90e8\u79ef\u6c34')

    if '\u6db2\u6001\u6c34' in text:
        candidate_devices = affected_devices or _extract_device_candidates(text)
        for device in candidate_devices:
            if device in {'\u59ff\u6001\u4fdd\u6301\u5668', '\u5916\u58f3'}:
                continue
            add_link(device, '\u5185\u90e8\u5b58\u5728\u8f83\u591a\u6db2\u6001\u6c34')

    return links


def _extract_positioning_fault_links(paragraphs: list[str]) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    pending_causes: list[str] = []
    in_positioning_section = False

    for paragraph in paragraphs:
        text = str(paragraph or '').strip()
        if not text:
            continue

        if '\u95ee\u9898\u5b9a\u4f4d\u4e8e' in text:
            pending_causes = []
            in_positioning_section = True
            continue

        if in_positioning_section and re.match(r'^\d+\)', text):
            cause_text = re.sub(r'^\d+\)\s*', '', text).strip()
            cause_text = _clean_fault_phrase(cause_text, max_length=120)
            if cause_text:
                pending_causes.append(cause_text)
            continue

        if in_positioning_section and '\u5f15\u8d77' in text:
            match = re.search(
                r'\u8fdb\u5165(?P<device>[^，。；;]{2,40}?)\u5f15\u8d77(?P<phenomenon>[^，。；;]{2,20})',
                text,
            )
            if match and pending_causes:
                device = _normalize_equipment_name(match.group('device')) or _clean_fault_phrase(match.group('device'), max_length=48)
                phenomenon = _normalize_phenomenon_text(f'\u5f15\u8d77{match.group("phenomenon")}', max_length=80)
                if device and phenomenon and not _is_invalid_fault_phenomenon(phenomenon):
                    for cause in pending_causes:
                        links.append({
                            'device': device,
                            'cause': cause,
                            'phenomenon': phenomenon,
                            'marker': 'positioning',
                            'evidence': text[:200],
                        })
            pending_causes = []
            in_positioning_section = False
            continue

        if in_positioning_section and not re.match(r'^\d+\)', text):
            pending_causes = []
            in_positioning_section = False

    return links


def _extract_fault_chain_by_rules(file_name: str, text: str) -> dict[str, Any]:
    paragraphs = _paragraphs(text)
    positioning_links = _extract_positioning_fault_links(paragraphs)
    equipment_items: list[dict[str, str]] = []
    phenomena: list[dict[str, str]] = []
    causes: list[dict[str, str]] = []
    fault_types: list[dict[str, str]] = []
    triples: list[dict[str, str]] = []
    matched_paragraphs: list[str] = []
    unmatched_paragraphs: list[str] = []
    seen_equipment: set[str] = set()
    seen_phenomena: set[tuple[str, str]] = set()
    seen_causes: set[tuple[str, str]] = set()
    seen_triples: set[tuple[str, str, str, str, str]] = set()
    last_specific_device = ''
    positioning_link_keys = {
        (
            _normalize_equipment_name(item.get('device', '')),
            _clean_fault_phrase(
                item.get('cause', '') if item.get('marker') == 'positioning' else _strip_prefix_noise(item.get('cause', '')),
                max_length=120,
            ),
            _normalize_phenomenon_text(item.get('phenomenon', ''), max_length=120),
        )
        for item in positioning_links
        if isinstance(item, dict)
    }

    def add_triple(subject: str, subject_type: str, predicate: str, obj: str, object_type: str) -> None:
        subject = _clean_fault_phrase(subject, max_length=48)
        if object_type == '故障现象':
            obj = _normalize_phenomenon_text(obj, max_length=120)
        else:
            stripped_obj = _strip_prefix_noise(obj)
            obj = _clean_fault_phrase(stripped_obj or obj, max_length=120)
        if not subject or not obj:
            return
        if object_type == '故障现象' and _is_invalid_fault_phenomenon(obj):
            return
        key = (subject, subject_type, predicate, obj, object_type)
        if key in seen_triples:
            return
        seen_triples.add(key)
        triples.append({
            'subject': subject,
            'subjectType': subject_type,
            'predicate': predicate,
            'object': obj,
            'objectType': object_type,
        })

    for paragraph in paragraphs:
        paragraph_matched = False
        device_candidates = _extract_device_candidates(paragraph)
        primary_device = _pick_primary_device(paragraph, device_candidates)
        if primary_device and _is_specific_equipment(primary_device):
            last_specific_device = primary_device
        for device in device_candidates:
            if '\u8fdb\u5165' in device:
                continue
            if device in seen_equipment:
                continue
            seen_equipment.add(device)
            equipment_items.append({'name': device, 'evidence': paragraph[:160]})

        links = [
            item for item in positioning_links
            if _text_from_item(item, ('evidence',)) == paragraph
        ]
        links.extend(_extract_inspection_fault_links_from_paragraph(paragraph))
        if not links:
            links.extend(_extract_fault_links_from_paragraph(paragraph))
        filtered_links: list[dict[str, str]] = []
        for link in links:
            key = (
                _normalize_equipment_name(link.get('device', '')),
                _clean_fault_phrase(
                    link.get('cause', '') if link.get('marker') == 'positioning' else _strip_prefix_noise(link.get('cause', '')),
                    max_length=120,
                ),
                _normalize_phenomenon_text(link.get('phenomenon', ''), max_length=120),
            )
            if key in positioning_link_keys and link.get('marker') != 'positioning':
                continue
            filtered_links.append(link)
        links = filtered_links
        if links:
            for link in links:
                device = link.get('device') or primary_device
                cause = _clean_fault_phrase(
                    link.get('cause', '') if link.get('marker') == 'positioning' else _strip_prefix_noise(link.get('cause', '')),
                    max_length=120,
                )
                phenomenon = _normalize_phenomenon_text(link.get('phenomenon', ''), max_length=120)
                if not device or not cause or not phenomenon:
                    continue
                device = _prefer_specific_device(device, phenomenon)
                if _is_invalid_fault_phenomenon(phenomenon):
                    continue

                if device not in seen_equipment:
                    seen_equipment.add(device)
                    equipment_items.append({'name': device, 'evidence': paragraph[:160]})

                phenomenon_key = (device, phenomenon)
                if phenomenon_key not in seen_phenomena:
                    seen_phenomena.add(phenomenon_key)
                    phenomena.append({
                        'name': phenomenon,
                        'device': device,
                        'evidence': paragraph[:200],
                    })

                cause_key = (phenomenon, cause)
                if cause_key not in seen_causes:
                    seen_causes.add(cause_key)
                    causes.append({
                        'name': cause,
                        'phenomenon': phenomenon,
                        'evidence': paragraph[:200],
                    })

                add_triple(device, '设备', '具有故障现象', phenomenon, '故障现象')
                add_triple(phenomenon, '故障现象', '原因为', cause, '故障原因')
                fault_types.append({
                    'device': device,
                    'fault': phenomenon,
                    'phenomenon': phenomenon,
                    'cause': cause,
                    'handling': '',
                    'evidence': paragraph[:200],
                })
                paragraph_matched = True
            if paragraph_matched:
                matched_paragraphs.append(paragraph)
            else:
                unmatched_paragraphs.append(paragraph)
            continue

        cause, phenomenon = _split_fault_cause_and_phenomenon(paragraph)
        if not phenomenon:
            phenomenon = _extract_direct_phenomenon(paragraph)
        phenomenon = _prefer_result_like_phenomenon(paragraph, phenomenon)
        phenomenon = _normalize_phenomenon_text(phenomenon, max_length=120) if phenomenon else ''
        cause = _clean_fault_phrase(_strip_prefix_noise(cause), max_length=120) if cause else ''
        if not primary_device and phenomenon and any(token in phenomenon for token in ('突变', '漏率', '漏气量')):
            primary_device = last_specific_device

        if primary_device and phenomenon:
            primary_device = _prefer_specific_device(primary_device, phenomenon)
            key = (primary_device, phenomenon)
            if key not in seen_phenomena:
                seen_phenomena.add(key)
                phenomena.append({
                    'name': phenomenon,
                    'device': primary_device,
                    'evidence': paragraph[:200],
                })
            add_triple(primary_device, '设备', '具有故障现象', phenomenon, '故障现象')
            paragraph_matched = True

        if phenomenon and cause:
            key = (phenomenon, cause)
            if key not in seen_causes:
                seen_causes.add(key)
                causes.append({
                    'name': cause,
                    'phenomenon': phenomenon,
                    'evidence': paragraph[:200],
                })
            add_triple(phenomenon, '故障现象', '原因为', cause, '故障原因')
            paragraph_matched = True

        if primary_device and (phenomenon or cause):
            fault_types.append({
                'device': primary_device,
                'fault': phenomenon or cause,
                'phenomenon': phenomenon,
                'cause': cause,
                'handling': '',
                'evidence': paragraph[:200],
            })
        if paragraph_matched:
            matched_paragraphs.append(paragraph)
        else:
            unmatched_paragraphs.append(paragraph)

    main_equipment = ''
    if equipment_items:
        counts = Counter(item['name'] for item in equipment_items)
        main_equipment = counts.most_common(1)[0][0]
    else:
        main_equipment = _infer_equipment(file_name, text)

    preferred_phenomena_by_device = {
        item['device']
        for item in phenomena
        if isinstance(item, dict) and '突变' in str(item.get('name') or '')
    }
    if preferred_phenomena_by_device:
        phenomena = [
            item for item in phenomena
            if item.get('device') not in preferred_phenomena_by_device
            or '突变' in str(item.get('name') or '')
        ]
        preferred_names = {
            (item.get('device'), item.get('name'))
            for item in phenomena
            if isinstance(item, dict)
        }
        fault_types = [
            item for item in fault_types
            if (item.get('device'), item.get('phenomenon') or item.get('fault')) in preferred_names
        ]
        triples = [
            item for item in triples
            if item.get('predicate') != '具有故障现象'
            or (item.get('subject'), item.get('object')) in preferred_names
        ]

    return {
        'documentName': _document_title(file_name, text),
        'equipment': main_equipment,
        'equipmentItems': equipment_items,
        'phenomena': phenomena,
        'causes': causes,
        'functions': [],
        'features': [],
        'maintenance': [],
        'faultTypes': fault_types,
        'safetyNotes': [],
        'specifications': _extract_specifications(text),
        'triples': triples,
        '_matchedParagraphs': matched_paragraphs,
        '_unmatchedParagraphs': unmatched_paragraphs,
    }


def _merge_fault_chain_summaries(file_name: str, text: str, *summaries: dict[str, Any]) -> dict[str, Any]:
    merged = _normalize_fault_chain_summary(file_name, text, {})
    equipment_seen: set[str] = set()
    phenomenon_seen: set[tuple[str, str]] = set()
    cause_seen: set[tuple[str, str]] = set()
    fault_seen: set[tuple[str, str, str]] = set()

    for summary in summaries:
        if not isinstance(summary, dict):
            continue
        if not merged['documentName'] and summary.get('documentName'):
            merged['documentName'] = str(summary.get('documentName')).strip()
        if not merged['equipment'] and summary.get('equipment'):
            merged['equipment'] = str(summary.get('equipment')).strip()

        for item in _as_list(summary.get('equipmentItems')):
            name = _normalize_equipment_name(item.get('name') if isinstance(item, dict) else item)
            if not _is_specific_equipment(name) or name in equipment_seen:
                continue
            equipment_seen.add(name)
            merged['equipmentItems'].append({
                'name': name,
                'evidence': _text_from_item(item, ('evidence', 'name')),
            })

        for item in _as_list(summary.get('phenomena')):
            if not isinstance(item, dict):
                continue
            device = _normalize_equipment_name(item.get('device'))
            phenomenon = _clean_fault_phrase(_strip_prefix_noise(item.get('name') or item.get('phenomenon')), max_length=80)
            if not _is_specific_equipment(device) or not phenomenon:
                continue
            key = (device, phenomenon)
            if key in phenomenon_seen:
                continue
            phenomenon_seen.add(key)
            merged['phenomena'].append({
                'name': phenomenon,
                'device': device,
                'evidence': _text_from_item(item, ('evidence', 'name', 'phenomenon')),
            })

        for item in _as_list(summary.get('causes')):
            if not isinstance(item, dict):
                continue
            phenomenon = _clean_fault_phrase(_strip_prefix_noise(item.get('phenomenon')), max_length=80)
            cause = _clean_fault_phrase(_strip_prefix_noise(item.get('name') or item.get('cause')), max_length=80)
            if not phenomenon or not cause:
                continue
            key = (phenomenon, cause)
            if key in cause_seen:
                continue
            cause_seen.add(key)
            merged['causes'].append({
                'name': cause,
                'phenomenon': phenomenon,
                'evidence': _text_from_item(item, ('evidence', 'name', 'cause')),
            })

        for item in _as_list(summary.get('faultTypes')):
            if not isinstance(item, dict):
                continue
            device = _normalize_equipment_name(item.get('device') or item.get('equipment'))
            phenomenon = _clean_fault_phrase(_strip_prefix_noise(item.get('phenomenon') or item.get('fault')), max_length=80)
            cause = _clean_fault_phrase(_strip_prefix_noise(item.get('cause') or item.get('reason')), max_length=80)
            if not _is_specific_equipment(device) or not phenomenon:
                continue
            key = (device, phenomenon, cause)
            if key in fault_seen:
                continue
            fault_seen.add(key)
            merged['faultTypes'].append({
                'device': device,
                'fault': phenomenon,
                'phenomenon': phenomenon,
                'cause': cause,
                'handling': '',
                'evidence': _text_from_item(item, ('evidence', 'fault', 'phenomenon')),
            })

    if not merged['equipment'] and merged['equipmentItems']:
        merged['equipment'] = merged['equipmentItems'][0]['name']
    merged['triples'] = _derive_fault_chain_triples(merged)
    return merged


def _llm_extract_fault_chain_from_paragraphs(file_name: str, paragraphs: list[str]) -> tuple[dict | None, str]:
    api_key, base_url, model = _llm_config()
    if not paragraphs:
        return None, ''
    if not base_url:
        return None, '未配置 LLM_BASE_URL，跳过未命中段落补抽。'
    if not url_allowed_in_offline(base_url):
        return None, f'离线模式禁止访问公网大模型接口：{base_url}'
    if not api_key and not offline_enabled():
        return None, '未配置 LLM_API_KEY 或 OPENAI_API_KEY。'

    excerpt = '\n\n'.join(
        f'段落{i + 1}: {item}'
        for i, item in enumerate(paragraphs[:FAULT_LLM_MAX_PARAGRAPHS])
    )
    prompt = f"""你是机械故障文本抽取助手。

请只根据下面这些“规则没有抽到”的段落，补充抽取：
1. 设备
2. 故障现象
3. 故障原因

要求：
1. 删除时间、地点、任务背景、过程描述，不要把这些内容当设备。
2. 设备必须尽量具体，例如“栅格舵”“舵机构支耳”“框架安装内腔”。
3. 故障现象必须是异常表现，例如“内部积水”“缝隙漏水”“存在较多液态水”。
4. 故障原因必须与对应故障现象匹配，例如“姿态保持器输入有问题，水未排空”。
5. 一个段落可以抽多条。
6. 只输出单个 JSON 对象，不要输出解释。

输出格式：
{{
  "equipmentItems": [{{"name": "设备", "evidence": "原文依据"}}],
  "phenomena": [{{"name": "故障现象", "device": "设备", "evidence": "原文依据"}}],
  "causes": [{{"name": "故障原因", "phenomenon": "故障现象", "evidence": "原文依据"}}],
  "faultTypes": [{{"device": "设备", "phenomenon": "故障现象", "cause": "故障原因", "evidence": "原文依据"}}]
}}

文档名：{file_name}

待补抽段落：
{excerpt}
"""
    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': '你只能输出单个合法 JSON 对象。'},
            {'role': 'user', 'content': prompt},
        ],
        'temperature': 0,
        'response_format': {'type': 'json_object'},
    }
    data, error_message = _post_llm_chat_completion(api_key, base_url, payload)
    if error_message:
        return None, error_message
    content = _extract_message_content(data or {})
    try:
        return _normalize_fault_chain_summary(file_name, excerpt, _extract_json_object(content)), ''
    except (json.JSONDecodeError, TypeError) as exc:
        return None, f'未命中段落补抽失败：{exc}'


def _llm_refine_fault_chain_summary(file_name: str, summary: dict[str, Any]) -> tuple[dict | None, str]:
    api_key, base_url, model = _llm_config()
    if not base_url:
        return None, '未配置 LLM_BASE_URL，跳过设备清洗。'
    if not url_allowed_in_offline(base_url):
        return None, f'离线模式禁止访问公网大模型接口：{base_url}'
    if not api_key and not offline_enabled():
        return None, '未配置 LLM_API_KEY 或 OPENAI_API_KEY。'

    raw_payload = {
        'equipmentItems': summary.get('equipmentItems') or [],
        'phenomena': summary.get('phenomena') or [],
        'causes': summary.get('causes') or [],
        'faultTypes': summary.get('faultTypes') or [],
    }
    prompt = f"""请清洗下面已经抽取出的故障结果。

要求：
1. 删除设备里的时间、地点、任务背景、过程性描述。
2. 删除不具体的设备，比如“过程”“任务”“情况”“问题”“输入”等泛化对象。
3. 尽量保留具体设备，例如模块、芯片、支耳、栅格舵、内腔、装置、阀门、组件、系统。
4. 保持设备、故障现象、故障原因之间的对应关系。
5. 只输出单个 JSON 对象，不要输出解释。

输出格式：
{{
  "equipmentItems": [{{"name": "设备", "evidence": "原文依据"}}],
  "phenomena": [{{"name": "故障现象", "device": "设备", "evidence": "原文依据"}}],
  "causes": [{{"name": "故障原因", "phenomenon": "故障现象", "evidence": "原文依据"}}],
  "faultTypes": [{{"device": "设备", "phenomenon": "故障现象", "cause": "故障原因", "evidence": "原文依据"}}]
}}

文档名：{file_name}
当前抽取结果：
{json.dumps(raw_payload, ensure_ascii=False, indent=2)}
"""
    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': '你只能输出单个合法 JSON 对象。'},
            {'role': 'user', 'content': prompt},
        ],
        'temperature': 0,
        'response_format': {'type': 'json_object'},
    }
    data, error_message = _post_llm_chat_completion(api_key, base_url, payload)
    if error_message:
        return None, error_message
    content = _extract_message_content(data or {})
    try:
        return _normalize_fault_chain_summary(file_name, '', _extract_json_object(content)), ''
    except (json.JSONDecodeError, TypeError) as exc:
        return None, f'设备清洗失败：{exc}'


def _heuristic_extract(file_name: str, text: str) -> dict:
    items = _paragraphs(text)
    summary = {
        'documentName': _document_title(file_name, text),
        'equipment': _infer_equipment(file_name, text),
        'functions': [],
        'features': [],
        'maintenance': [],
        'faultTypes': [],
        'safetyNotes': [],
        'specifications': _extract_specifications(text),
    }

    for key, config in CATEGORY_CONFIG.items():
        matches = _summarize_by_keywords(items, config['keywords'])
        if key == 'maintenance':
            summary[key] = [{'task': item[:48], 'method': item, 'cycle': '', 'tools': '', 'warning': ''} for item in matches]
        elif key == 'faultTypes':
            summary[key] = [{'fault': item[:48], 'phenomenon': '', 'cause': item, 'handling': ''} for item in matches]
        elif key == 'safetyNotes':
            summary[key] = [{'note': item, 'context': ''} for item in matches]
        else:
            summary[key] = [{'name': item[:48], 'description': item, 'evidence': ''} for item in matches]
    return summary


def _relevant_text_for_llm(text: str) -> str:
    paragraphs = _paragraphs(text)
    selected = paragraphs[:30]
    seen = set(selected)
    for config in CATEGORY_CONFIG.values():
        for item in _summarize_by_keywords(paragraphs, config['keywords'], limit=18):
            if item not in seen:
                selected.append(item)
                seen.add(item)
    compact = '\n'.join(selected)
    return compact[:MAX_LLM_TEXT_CHARS]


def _llm_config() -> tuple[str, str, str]:
    api_key = os.environ.get('LLM_API_KEY') or os.environ.get('OPENAI_API_KEY') or ''
    base_url = os.environ.get('LLM_BASE_URL') or os.environ.get('OPENAI_BASE_URL') or ''
    if not base_url and not offline_enabled():
        base_url = 'https://api.openai.com/v1'
    model = os.environ.get('LLM_MODEL') or 'gpt-4o-mini'
    return api_key.strip(), base_url.rstrip('/'), model.strip()


def _extract_json_object(text: str) -> dict:
    clean = str(text or '').replace('\ufeff', '').strip()
    candidates: list[str] = []
    if clean:
        candidates.append(clean)
    fenced_blocks = re.findall(r'```(?:json)?\s*(.*?)```', clean, flags=re.IGNORECASE | re.DOTALL)
    for block in fenced_blocks:
        block = str(block or '').strip()
        if block:
            candidates.append(block)
    start = clean.find('{')
    end = clean.rfind('}')
    if start >= 0 and end > start:
        candidates.append(clean[start:end + 1])
    seen: set[str] = set()
    for candidate in candidates:
        normalized = candidate.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        try:
            value = json.loads(normalized)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise json.JSONDecodeError('No valid JSON object found in model output', clean, 0)


def _document_summary_json_schema() -> dict[str, Any]:
    return {
        'type': 'object',
        'required': [
            'documentName',
            'equipment',
            'equipmentItems',
            'phenomena',
            'causes',
            'functions',
            'features',
            'maintenance',
            'faultTypes',
            'safetyNotes',
            'specifications',
            'triples',
        ],
        'properties': {
            'documentName': {'type': 'string'},
            'equipment': {'type': 'string'},
            'equipmentItems': {'type': 'array'},
            'phenomena': {'type': 'array'},
            'causes': {'type': 'array'},
            'functions': {'type': 'array'},
            'features': {'type': 'array'},
            'maintenance': {'type': 'array'},
            'faultTypes': {'type': 'array'},
            'safetyNotes': {'type': 'array'},
            'specifications': {'type': 'array'},
            'triples': {'type': 'array'},
        },
        'additionalProperties': True,
    }


def _fault_chain_constraints() -> dict[str, Any]:
    return {
        'entityTypes': ['设备', '故障现象', '故障原因'],
        'relations': ['具有故障现象', '原因为'],
        'patterns': [
            ('设备', '具有故障现象', '故障现象'),
            ('故障现象', '原因为', '故障原因'),
        ],
        'source': 'fault-chain',
    }


def _canonical_fault_text(value: Any, max_length: int = 120) -> str:
    text = re.sub(r'\s+', ' ', str(value or '')).strip(' ，,。；;：:[]【】()（）')
    if not text:
        return ''
    return text[:max_length].strip()


def _derive_fault_chain_triples(summary: dict[str, Any]) -> list[dict[str, str]]:
    triples: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str, str]] = set()

    def add(subject: str, subject_type: str, predicate: str, obj: str, object_type: str) -> None:
        subject = _canonical_fault_text(subject)
        obj = _canonical_fault_text(obj)
        if not subject or not obj or not predicate:
            return
        key = (subject, subject_type, predicate, obj, object_type)
        if key in seen:
            return
        seen.add(key)
        triples.append({
            'subject': subject,
            'subjectType': subject_type,
            'predicate': predicate,
            'object': obj,
            'objectType': object_type,
        })

    default_device = _canonical_fault_text(summary.get('equipment'))
    equipment_names = [
        _canonical_fault_text(item.get('name') if isinstance(item, dict) else item)
        for item in _as_list(summary.get('equipmentItems'))
    ]
    equipment_names = [item for item in equipment_names if item]
    if not default_device and equipment_names:
        default_device = equipment_names[0]

    for item in _as_list(summary.get('phenomena')):
        if not isinstance(item, dict):
            continue
        device = _canonical_fault_text(item.get('device')) or default_device
        phenomenon = _canonical_fault_text(item.get('name') or item.get('phenomenon'))
        add(device, '设备', '具有故障现象', phenomenon, '故障现象')

    for item in _as_list(summary.get('causes')):
        if not isinstance(item, dict):
            continue
        phenomenon = _canonical_fault_text(item.get('phenomenon'))
        cause = _canonical_fault_text(item.get('name') or item.get('cause'))
        add(phenomenon, '故障现象', '原因为', cause, '故障原因')

    for item in _as_list(summary.get('faultTypes')):
        if not isinstance(item, dict):
            continue
        device = _canonical_fault_text(
            item.get('device') or item.get('equipment') or item.get('targetDevice')
        ) or default_device
        phenomenon = _canonical_fault_text(
            item.get('phenomenon') or item.get('fault') or item.get('name')
        )
        cause = _canonical_fault_text(item.get('cause') or item.get('reason'))
        add(device, '设备', '具有故障现象', phenomenon, '故障现象')
        add(phenomenon, '故障现象', '原因为', cause, '故障原因')

    return triples


def _extract_message_content(payload: dict[str, Any]) -> str:
    message = ((payload or {}).get('choices') or [{}])[0].get('message', {}) or {}
    content = message.get('content', '')
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get('text') or item.get('content') or ''
                if text:
                    chunks.append(str(text))
            elif item:
                chunks.append(str(item))
        return ''.join(chunks).strip()
    return str(content or '').strip()


def _post_llm_chat_completion(
    api_key: str,
    base_url: str,
    payload: dict[str, Any],
) -> tuple[dict[str, Any] | None, str]:
    headers = {'Content-Type': 'application/json'}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    request = Request(
        f'{base_url}/chat/completions',
        data=json.dumps(payload).encode('utf-8'),
        headers=headers,
        method='POST',
    )
    try:
        with urlopen(request, timeout=_llm_timeout_seconds()) as response:
            data = json.loads(response.read().decode('utf-8'))
    except HTTPError as exc:
        body = exc.read().decode('utf-8', errors='replace')
        return None, f'澶фā鍨嬫帴鍙ｈ繑鍥為敊璇細{exc.code} {body[:300]}'
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        return None, f'澶фā鍨嬭皟鐢ㄥけ璐ワ細{exc}'
    return data, ''


def _repair_json_with_llm(
    api_key: str,
    base_url: str,
    model: str,
    broken_content: str,
) -> tuple[dict[str, Any] | None, str]:
    schema_text = json.dumps(_document_summary_json_schema(), ensure_ascii=False, indent=2)
    repair_prompt = f"""你上一次返回的内容不是合法 JSON。现在你只能做一件事：把下面这段内容修复成一个合法的 JSON 对象。

强制要求：
1. 只输出一个 JSON 对象。
2. 第一字符必须是 {{ ，最后字符必须是 }} 。
3. 不要输出 Markdown，不要输出 ```json，不要解释，不要道歉，不要补充任何额外文字。
4. 如果某个字段无法确定，就保留空字符串 "" 或空数组 []。
5. 必须保留以下顶层字段：
documentName, equipment, functions, features, maintenance, faultTypes, safetyNotes, specifications, triples

目标 JSON Schema：
{schema_text}

待修复内容：
{broken_content}
"""
    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': '你是严格的 JSON 修复器。你只能输出单个合法 JSON 对象。'},
            {'role': 'user', 'content': repair_prompt},
        ],
        'temperature': 0,
        'response_format': {'type': 'json_object'},
    }
    data, error_message = _post_llm_chat_completion(api_key, base_url, payload)
    if error_message:
        return None, error_message
    try:
        return _extract_json_object(_extract_message_content(data or {})), ''
    except (json.JSONDecodeError, TypeError) as exc:
        return None, f'JSON repair failed: {exc}'


def _llm_extract(file_name: str, text: str) -> tuple[dict | None, str]:
    api_key, base_url, model = _llm_config()
    if not base_url:
        return None, '离线模式未配置本地 LLM_BASE_URL，已使用本地规则抽取。'
    if not url_allowed_in_offline(base_url):
        return None, f'离线模式禁止访问公网大模型接口：{base_url}，已使用本地规则抽取。'
    if not api_key and not offline_enabled():
        return None, '未配置 LLM_API_KEY 或 OPENAI_API_KEY，已使用本地规则抽取。'

    prompt = f"""你是一个机械故障追溯领域的大师。
请根据文档内容抽取与机械故障追溯相关的知识，重点识别设备、功能、故障类型、故障现象、故障原因、处理措施、安全要求、技术参数，并形成可直接入库的三元组。
输出必须是严格 JSON，不要输出 Markdown，不要解释，不要补充 JSON 之外的任何内容。
文档名：{file_name}

JSON 字段要求：
{{
  "documentName": "文档名称",
  "equipment": "说明书对应设备、系统或部件名称",
  "functions": [{{"name": "功能名称", "description": "功能说明", "evidence": "原文依据"}}],
  "features": [{{"name": "结构/特点名称", "description": "特点说明", "evidence": "原文依据"}}],
  "maintenance": [{{"task": "维修/维护事项", "method": "维修方法", "cycle": "周期或条件", "tools": "工具", "warning": "注意事项"}}],
  "faultTypes": [{{"fault": "故障类型", "phenomenon": "故障现象", "cause": "故障原因", "handling": "处理措施", "evidence": "原文依据"}}],
  "safetyNotes": [{{"note": "安全注意事项", "context": "适用场景"}}],
  "specifications": [{{"name": "参数名", "value": "数值或描述", "unit": "单位"}}],
  "triples": [
    {{
      "subject": "节点名称",
      "subjectType": "节点类型，如设备/功能/故障类型/故障现象/故障原因/处理措施/安全要求/技术参数/属性值",
      "predicate": "关系名称",
      "object": "节点名称",
      "objectType": "节点类型"
    }}
  ]
}}

抽取规则：
1. 优先抽取和机械故障追溯直接相关的信息。
2. 能形成清晰三元组时，尽量写入 triples。
3. “故障现象”“故障原因”“处理措施”优先单独作为节点，不要只合并进长句描述。
4. 如果原文没有明确提到，不要臆造。
5. triples 中每一项都必须是单条、明确、可直接用于知识图谱的关系。
6. 同义或重复内容尽量合并。

文档内容：
{_relevant_text_for_llm(text)}
"""
    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': '你是机械故障追溯与知识图谱构建专家，只输出合法 JSON。'},
            {'role': 'user', 'content': prompt},
        ],
        'temperature': 0.1,
        'response_format': {'type': 'json_object'},
    }
    headers = {'Content-Type': 'application/json'}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    request = Request(
        f'{base_url}/chat/completions',
        data=json.dumps(payload).encode('utf-8'),
        headers=headers,
        method='POST',
    )
    try:
        with urlopen(request, timeout=_llm_timeout_seconds()) as response:
            data = json.loads(response.read().decode('utf-8'))
    except HTTPError as exc:
        body = exc.read().decode('utf-8', errors='replace')
        return None, f'大模型接口返回错误：{exc.code} {body[:300]}'
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        return None, f'大模型调用失败：{exc}'

    content = data.get('choices', [{}])[0].get('message', {}).get('content', '')
    try:
        return _extract_json_object(content), ''
    except (json.JSONDecodeError, TypeError) as exc:
        return None, f'大模型返回不是有效 JSON：{exc}'


def _as_list(value) -> list:
    return value if isinstance(value, list) else []


def _llm_extract_constrained(file_name: str, text: str, ontology_constraints: dict[str, Any]) -> tuple[dict | None, str]:
    api_key, base_url, model = _llm_config()
    if not base_url:
        return None, '未配置 LLM_BASE_URL，已使用本地规则抽取。'
    if not url_allowed_in_offline(base_url):
        return None, f'离线模式禁止访问公网大模型接口：{base_url}，已使用本地规则抽取。'
    if not api_key and not offline_enabled():
        return None, '未配置 LLM_API_KEY 或 OPENAI_API_KEY，已使用本地规则抽取。'

    allowed_types = '、'.join(ontology_constraints.get('entityTypes') or [])
    allowed_relations = '、'.join(ontology_constraints.get('relations') or [])
    allowed_patterns = '\n'.join(
        f'- {subject_type} --{predicate}--> {object_type}'
        for subject_type, predicate, object_type in (ontology_constraints.get('patterns') or [])
    )
    schema_text = json.dumps(_document_summary_json_schema(), ensure_ascii=False, indent=2)
    prompt = f"""你是一个机械故障追溯领域的知识抽取专家。请严格依据当前本体构建的结构抽取文档知识。

本次抽取必须遵守以下本体约束，不允许新增本体中没有的实体类型，不允许新增关系类型，不允许输出不符合关系骨架的三元组。

允许的实体类型：
{allowed_types}

允许的关系类型：
{allowed_relations}

允许的关系骨架：
{allowed_patterns}

如果文档里的内容无法落到上述本体结构里，就跳过，不要臆造新条目、新关系、新类型。
实例文本必须来自文档原文，但实例所属类型和关系必须严格取自上面的本体。

输出必须是严格 JSON，不要输出 Markdown，不要解释，不要补充 JSON 之外的任何内容。
第一字符必须是 {{，最后字符必须是 }}。
文档名：{file_name}

目标 JSON Schema：
{schema_text}

JSON 字段要求：{{
  "documentName": "文档名称",
  "equipment": "文档对应设备/系统/部件名称",
  "functions": [{{"name": "功能名称", "description": "功能说明", "evidence": "原文依据"}}],
  "features": [{{"name": "特点名称", "description": "特点说明", "evidence": "原文依据"}}],
  "maintenance": [{{"task": "维护事项", "method": "处理方法", "cycle": "周期或条件", "tools": "工具", "warning": "注意事项"}}],
  "faultTypes": [{{"fault": "故障模式", "phenomenon": "故障现象", "cause": "原因", "handling": "措施", "evidence": "原文依据"}}],
  "safetyNotes": [{{"note": "安全要求", "context": "适用场景"}}],
  "specifications": [{{"name": "参数名", "value": "参数值", "unit": "单位"}}],
  "triples": [
    {{
      "subject": "节点名称",
      "subjectType": "实体类型",
      "predicate": "关系名称",
      "object": "节点名称",
      "objectType": "实体类型"
    }}
  ]
}}

抽取规则：
1. 优先输出 triples，并让 triples 严格匹配给定本体结构。
2. subjectType 和 objectType 只能从允许的实体类型里选。
3. predicate 只能从允许的关系类型里选。
4. 每条 triples 都必须能在允许的关系骨架里找到对应类型组合。
5. 如果原文没有明确信息，不要补造。
6. 如果某段内容不属于本体结构，就不要输出。

文档内容：
{_relevant_text_for_llm(text)}
"""
    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': '你是严格的 JSON 输出器。你只能输出单个合法 JSON 对象。禁止输出 Markdown、解释、前后缀文本、代码围栏。'},
            {'role': 'user', 'content': prompt},
        ],
        'temperature': 0,
        'response_format': {'type': 'json_object'},
    }
    data, error_message = _post_llm_chat_completion(api_key, base_url, payload)
    if error_message:
        return None, error_message

    content = _extract_message_content(data or {})
    try:
        return _extract_json_object(content), ''
    except (json.JSONDecodeError, TypeError) as exc:
        repaired, repair_message = _repair_json_with_llm(api_key, base_url, model, content)
        if repaired is not None:
            return repaired, '大模型首次返回格式不符合要求，已自动执行 JSON 修复。'
        return None, f'大模型返回不是有效 JSON：{exc}；无法自动修复：{repair_message}'


def _llm_generate_triples_only(
    file_name: str,
    text: str,
    summary: dict[str, Any],
    ontology_constraints: dict[str, Any],
) -> tuple[list[dict[str, str]], str]:
    api_key, base_url, model = _llm_config()
    if not base_url:
        return [], '未配置 LLM_BASE_URL，无法补充三元组。'
    if not url_allowed_in_offline(base_url):
        return [], f'离线模式禁止访问公网大模型接口：{base_url}，无法补充三元组。'
    if not api_key and not offline_enabled():
        return [], '未配置 LLM_API_KEY 或 OPENAI_API_KEY，无法补充三元组。'

    allowed_types = '、'.join(ontology_constraints.get('entityTypes') or [])
    allowed_relations = '、'.join(ontology_constraints.get('relations') or [])
    allowed_patterns = '\n'.join(
        f'- {subject_type} --{predicate}--> {object_type}'
        for subject_type, predicate, object_type in (ontology_constraints.get('patterns') or [])
    )
    summary_text = json.dumps(
        {
            'documentName': summary.get('documentName', ''),
            'equipment': summary.get('equipment', ''),
            'functions': summary.get('functions', []),
            'features': summary.get('features', []),
            'maintenance': summary.get('maintenance', []),
            'faultTypes': summary.get('faultTypes', []),
            'safetyNotes': summary.get('safetyNotes', []),
            'specifications': summary.get('specifications', []),
        },
        ensure_ascii=False,
        indent=2,
    )
    prompt = f"""你现在只做一件事：基于文档摘要和原文，严格按照给定本体，补全 triples。

强制要求：
1. 只允许输出一个 JSON 对象，格式必须是 {{"triples":[...]}}。
2. 不要输出 Markdown，不要解释，不要前后缀，不要代码块。
3. triples 里的每一项都必须包含：
subject, subjectType, predicate, object, objectType
4. subjectType 和 objectType 只能从下面允许的实体类型中选择：
{allowed_types}
5. predicate 只能从下面允许的关系类型中选择：
{allowed_relations}
6. 每条 triples 都必须符合下面允许的关系骨架：
{allowed_patterns}
7. 如果无法形成合法三元组，就返回 {{"triples":[]}}，不要瞎编。
8. 尽量从摘要中补出“故障模式-故障现象-原因-措施”和“层级对象-功能”关系。

文档摘要：
{summary_text}

文档原文：
{_relevant_text_for_llm(text)}
"""
    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': '你是严格的三元组 JSON 输出器。你只能输出单个 JSON 对象，且顶层只能有 triples 字段。'},
            {'role': 'user', 'content': prompt},
        ],
        'temperature': 0,
        'response_format': {'type': 'json_object'},
    }
    data, error_message = _post_llm_chat_completion(api_key, base_url, payload)
    if error_message:
        return [], error_message

    content = _extract_message_content(data or {})
    try:
        parsed = _extract_json_object(content)
    except (json.JSONDecodeError, TypeError) as exc:
        repaired, repair_message = _repair_json_with_llm(api_key, base_url, model, content)
        if repaired is None:
            return [], f'三元组补充失败：{exc}；无法自动修复：{repair_message}'
        parsed = repaired

    triples = _filter_triples_by_ontology(_as_list((parsed or {}).get('triples')), ontology_constraints)
    return triples, ''


def _llm_extract_fault_chain(file_name: str, text: str) -> tuple[dict | None, str]:
    api_key, base_url, model = _llm_config()
    if not base_url:
        return None, '未配置 LLM_BASE_URL，已使用本地规则抽取。'
    if not url_allowed_in_offline(base_url):
        return None, f'离线模式禁止访问公网大模型接口：{base_url}，已使用本地规则抽取。'
    if not api_key and not offline_enabled():
        return None, '未配置 LLM_API_KEY 或 OPENAI_API_KEY，已使用本地规则抽取。'

    schema_text = json.dumps(_document_summary_json_schema(), ensure_ascii=False, indent=2)
    prompt = f"""你是机械故障追溯信息抽取专家。

本次任务不是按本体层级建图，也不是抽整句描述，而是先抽“名词级对象”，再抽关系。

你必须按照下面顺序理解并输出：
1. 先抽设备名词：只保留设备、分系统、组件、传感器、阀门、模块、装置等名词，不要时间、地点、过程句。
2. 再抽故障现象：只保留能表示异常表现的短语，不要长句。
3. 再抽故障原因：只保留导致该故障现象的原因短语，不要长句。
4. 最后组装 triples，只允许两种关系：
   - 设备 --具有故障现象--> 故障现象
   - 故障现象 --原因为--> 故障原因

强制要求：
1. 只输出单个合法 JSON 对象。
2. 第一字符必须是 {{，最后字符必须是 }}。
3. 不要输出 Markdown、解释、代码块、说明文字。
4. 所有 name / phenomenon / cause / subject / object 尽量是名词或短语，避免完整长句。
5. 如果某项无法确定，返回空数组，不要编造。
6. triples 必须和 equipmentItems、phenomena、causes 保持一致。

目标 JSON Schema：
{schema_text}

输出格式要求：
{{
  "documentName": "文档名称",
  "equipment": "主设备名称，没有就留空",
  "equipmentItems": [
    {{"name": "设备名词", "evidence": "原文依据"}}
  ],
  "phenomena": [
    {{"name": "故障现象短语", "device": "对应设备名词", "evidence": "原文依据"}}
  ],
  "causes": [
    {{"name": "故障原因短语", "phenomenon": "对应故障现象短语", "evidence": "原文依据"}}
  ],
  "functions": [],
  "features": [],
  "maintenance": [],
  "faultTypes": [
    {{"device": "设备名词", "phenomenon": "故障现象短语", "cause": "故障原因短语", "evidence": "原文依据"}}
  ],
  "safetyNotes": [],
  "specifications": [],
  "triples": [
    {{"subject": "设备名词", "subjectType": "设备", "predicate": "具有故障现象", "object": "故障现象短语", "objectType": "故障现象"}},
    {{"subject": "故障现象短语", "subjectType": "故障现象", "predicate": "原因为", "object": "故障原因短语", "objectType": "故障原因"}}
  ]
}}

文档名：{file_name}

文档内容：
{_relevant_text_for_llm(text)}
"""
    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': '你是严格的故障名词链 JSON 输出器。你只能输出单个合法 JSON 对象。'},
            {'role': 'user', 'content': prompt},
        ],
        'temperature': 0,
        'response_format': {'type': 'json_object'},
    }
    data, error_message = _post_llm_chat_completion(api_key, base_url, payload)
    if error_message:
        return None, error_message

    content = _extract_message_content(data or {})
    try:
        return _extract_json_object(content), ''
    except (json.JSONDecodeError, TypeError) as exc:
        repaired, repair_message = _repair_json_with_llm(api_key, base_url, model, content)
        if repaired is not None:
            return repaired, '大模型首次返回格式不符合要求，已自动执行 JSON 修复。'
        return None, f'大模型返回不是有效 JSON：{exc}；无法自动修复：{repair_message}'


def _text_from_item(item, keys: tuple[str, ...]) -> str:
    if isinstance(item, str):
        return item.strip()
    if not isinstance(item, dict):
        return ''
    for key in keys:
        text = str(item.get(key, '') or '').strip()
        if text:
            return text
    return ''


def _normalize_summary(file_name: str, text: str, raw: dict) -> dict:
    fallback = _heuristic_extract(file_name, text)
    raw = raw if isinstance(raw, dict) else {}
    summary = {
        'documentName': str(raw.get('documentName') or fallback['documentName']).strip(),
        'equipment': str(raw.get('equipment') or fallback['equipment']).strip(),
        'equipmentItems': _as_list(raw.get('equipmentItems')),
        'phenomena': _as_list(raw.get('phenomena')),
        'causes': _as_list(raw.get('causes')),
        'functions': _as_list(raw.get('functions')) or fallback['functions'],
        'features': _as_list(raw.get('features')) or fallback['features'],
        'maintenance': _as_list(raw.get('maintenance')) or fallback['maintenance'],
        'faultTypes': _as_list(raw.get('faultTypes')) or fallback['faultTypes'],
        'safetyNotes': _as_list(raw.get('safetyNotes')) or fallback['safetyNotes'],
        'specifications': _as_list(raw.get('specifications')) or fallback['specifications'],
        'triples': _as_list(raw.get('triples')),
    }
    return summary


def _apply_ontology_constraints_to_summary(summary: dict[str, Any], ontology_constraints: dict[str, Any]) -> dict[str, Any]:
    next_summary = dict(summary or {})
    next_summary['triples'] = _filter_triples_by_ontology(_as_list(next_summary.get('triples')), ontology_constraints)
    next_summary['ontologySource'] = ontology_constraints.get('source', 'fallback')
    next_summary['ontologyEntityTypes'] = list(ontology_constraints.get('entityTypes') or [])
    next_summary['ontologyRelations'] = list(ontology_constraints.get('relations') or [])
    return next_summary


def _build_graph_payload(file_name: str, summary: dict) -> dict:
    entity_map: dict[tuple[str, str], dict] = {}
    triple_rows: list[dict] = []

    def add_entity(name: str, entity_type: str) -> str:
        clean_name = re.sub(r'\s+', ' ', str(name or '')).strip()
        if not clean_name:
            return ''
        key = (clean_name, entity_type)
        if key not in entity_map:
            entity_map[key] = {'name': clean_name, 'type': entity_type}
        return clean_name

    def add_triple(subject: str, subject_type: str, predicate: str, obj: str, object_type: str) -> None:
        subject = add_entity(subject, subject_type)
        obj = add_entity(obj, object_type)
        if not subject or not obj or not predicate:
            return
        triple_rows.append({
            'subject': subject,
            'predicate': predicate,
            'object': obj,
            'subjectType': subject_type,
            'objectType': object_type,
        })

    type_aliases = {
        '设备': EQUIPMENT,
        '系统': EQUIPMENT,
        '部件': EQUIPMENT,
        '组件': EQUIPMENT,
        '功能': FUNCTION,
        '特点': FEATURE,
        '结构特点': FEATURE,
        '维修维护': MAINTENANCE,
        '维修': MAINTENANCE,
        '维护': MAINTENANCE,
        '故障': FAULT,
        '故障类型': FAULT,
        '故障现象': FAULT_PHENOMENON,
        '故障原因': FAULT_CAUSE,
        '处理措施': HANDLING,
        '处理方法': HANDLING,
        '安全要求': SAFETY,
        '安全注意事项': SAFETY,
        '技术参数': SPECIFICATION,
        '参数': SPECIFICATION,
        '属性': ATTRIBUTE,
        '属性值': ATTRIBUTE,
    }

    def normalize_entity_type(raw_type: str, fallback_type: str) -> str:
        clean = re.sub(r'\s+', '', str(raw_type or ''))
        return type_aliases.get(clean, clean or fallback_type)

    doc_name = summary.get('documentName') or Path(file_name).stem
    equipment = summary.get('equipment') or doc_name
    add_triple(doc_name, DOCUMENT, '说明对象', equipment, EQUIPMENT)

    for item in _as_list(summary.get('triples'))[:48]:
        if not isinstance(item, dict):
            continue
        subject = _text_from_item(item, ('subject', 'head', 'source'))
        predicate = _text_from_item(item, ('predicate', 'relation'))
        obj = _text_from_item(item, ('object', 'target'))
        subject_type = normalize_entity_type(_text_from_item(item, ('subjectType', 'subject_type')), ATTRIBUTE)
        object_type = normalize_entity_type(_text_from_item(item, ('objectType', 'object_type')), ATTRIBUTE)
        add_triple(subject, subject_type, predicate, obj, object_type)

    for item in _as_list(summary.get('functions'))[:12]:
        name = _text_from_item(item, ('name', 'function', 'title', 'description'))
        description = _text_from_item(item, ('description', 'evidence'))
        add_triple(equipment, EQUIPMENT, '具有功能', name, FUNCTION)
        if description and description != name:
            add_triple(name, FUNCTION, '功能说明', description, ATTRIBUTE)

    for item in _as_list(summary.get('features'))[:12]:
        name = _text_from_item(item, ('name', 'feature', 'title', 'description'))
        description = _text_from_item(item, ('description', 'evidence'))
        add_triple(equipment, EQUIPMENT, '具有特点', name, FEATURE)
        if description and description != name:
            add_triple(name, FEATURE, '特点说明', description, ATTRIBUTE)

    for item in _as_list(summary.get('maintenance'))[:12]:
        task = _text_from_item(item, ('task', 'name', 'title', 'method'))
        method = _text_from_item(item, ('method', 'description'))
        cycle = _text_from_item(item, ('cycle', 'condition'))
        warning = _text_from_item(item, ('warning', 'note'))
        add_triple(equipment, EQUIPMENT, '维修维护', task, MAINTENANCE)
        if method and method != task:
            add_triple(task, MAINTENANCE, '处理方法', method, ATTRIBUTE)
        if cycle:
            add_triple(task, MAINTENANCE, '维护周期', cycle, ATTRIBUTE)
        if warning:
            add_triple(task, MAINTENANCE, '注意事项', warning, SAFETY)

    for item in _as_list(summary.get('faultTypes'))[:12]:
        fault = _text_from_item(item, ('fault', 'name', 'title', 'phenomenon'))
        phenomenon = _text_from_item(item, ('phenomenon', 'description'))
        cause = _text_from_item(item, ('cause', 'reason'))
        handling = _text_from_item(item, ('handling', 'method', 'solution'))
        add_triple(equipment, EQUIPMENT, '可能故障', fault, FAULT)
        if phenomenon and phenomenon != fault:
            add_triple(fault, FAULT, '故障现象', phenomenon, FAULT_PHENOMENON)
        if cause and cause != fault:
            add_triple(fault, FAULT, '故障原因', cause, FAULT_CAUSE)
        if handling:
            add_triple(fault, FAULT, '处理方法', handling, HANDLING)

    for item in _as_list(summary.get('safetyNotes'))[:10]:
        note = _text_from_item(item, ('note', 'name', 'description'))
        context = _text_from_item(item, ('context', 'scene'))
        add_triple(equipment, EQUIPMENT, '安全要求', note, SAFETY)
        if context:
            add_triple(note, SAFETY, '适用场景', context, ATTRIBUTE)

    for item in _as_list(summary.get('specifications'))[:12]:
        if isinstance(item, str):
            spec_name = item
            value = ''
        elif isinstance(item, dict):
            spec_name = str(item.get('name') or '').strip()
            value = ' '.join(str(item.get(key) or '').strip() for key in ('value', 'unit') if str(item.get(key) or '').strip())
        else:
            continue
        add_triple(equipment, EQUIPMENT, '技术参数', spec_name, SPECIFICATION)
        if value:
            add_triple(spec_name, SPECIFICATION, '参数值', value, ATTRIBUTE)

    relation_count = Counter(row['predicate'] for row in triple_rows)
    return {
        'entities': sorted(entity_map.values(), key=lambda item: (item['type'], item['name'])),
        'relations': [{'name': name, 'count': count} for name, count in relation_count.items()],
        'tripleRows': triple_rows,
        'counts': {
            'entities': len(entity_map),
            'relations': len(relation_count),
            'triples': len(triple_rows),
        },
    }


def _build_graph_payload_from_ontology(summary: dict[str, Any], ontology_constraints: dict[str, Any]) -> dict[str, Any]:
    entity_map: dict[tuple[str, str], dict[str, str]] = {}
    triple_rows: list[dict[str, str]] = []

    def ensure_entity(name: str, entity_type: str) -> str:
        clean_name = re.sub(r'\s+', ' ', str(name or '')).strip()
        clean_type = _normalize_ontology_type(entity_type)
        if not clean_name or not clean_type:
            return ''
        key = (clean_name, clean_type)
        if key not in entity_map:
            entity_map[key] = {'name': clean_name, 'type': clean_type}
        return clean_name

    for item in _filter_triples_by_ontology(_as_list(summary.get('triples')), ontology_constraints):
        subject = ensure_entity(item.get('subject', ''), item.get('subjectType', ''))
        obj = ensure_entity(item.get('object', ''), item.get('objectType', ''))
        predicate = _canonical_relation_label(item.get('predicate', ''))
        if not subject or not obj or not predicate:
            continue
        triple_rows.append({
            'subject': subject,
            'predicate': predicate,
            'object': obj,
            'subjectType': _normalize_ontology_type(item.get('subjectType', '')),
            'objectType': _normalize_ontology_type(item.get('objectType', '')),
        })

    relation_count = Counter(row['predicate'] for row in triple_rows)
    return {
        'entities': sorted(entity_map.values(), key=lambda item: (item['type'], item['name'])),
        'relations': [{'name': name, 'count': count} for name, count in relation_count.items()],
        'tripleRows': triple_rows,
        'counts': {
            'entities': len(entity_map),
            'relations': len(relation_count),
            'triples': len(triple_rows),
        },
    }


def get_document_parse_configuration(file_name: str, content: bytes) -> dict:
    text, meta = extract_document_text(file_name, content)
    return {
        'fileName': file_name,
        'sourceType': 'document',
        'needsMapping': False,
        'headers': [],
        'documentPreview': text[:MAX_PREVIEW_CHARS],
        **meta,
    }


def get_document_extraction_result(file_name: str, content: bytes, ontology: dict[str, Any] | None = None) -> dict:
    text, meta = extract_document_text(file_name, content)
    ontology_constraints = _fault_chain_constraints()
    rule_summary = _extract_fault_chain_by_rules(file_name, text)
    unmatched_paragraphs = list(rule_summary.pop('_unmatchedParagraphs', []) or [])
    rule_summary.pop('_matchedParagraphs', None)
    summary = _merge_fault_chain_summaries(file_name, text, rule_summary)
    llm_enabled = False
    llm_message = ''

    llm_payload, llm_error = _llm_extract_fault_chain_from_paragraphs(file_name, unmatched_paragraphs)
    if llm_payload:
        llm_enabled = True
        summary = _merge_fault_chain_summaries(file_name, text, summary, llm_payload)
        llm_message = '存在规则未命中段落，已使用大模型补充抽取。'
    elif llm_error:
        llm_message = llm_error

    if summary.get('equipmentItems') or summary.get('phenomena') or summary.get('causes'):
        cleaned_summary, cleanup_error = _llm_refine_fault_chain_summary(file_name, summary)
        if cleaned_summary:
            llm_enabled = True
            summary = _merge_fault_chain_summaries(file_name, text, cleaned_summary)
            llm_message = (llm_message + ' 已完成设备名称清洗。').strip()
        elif cleanup_error:
            llm_message = (llm_message + f' {cleanup_error}').strip()

    summary, applied_mappings = _apply_device_glossary_mapping(summary)
    if applied_mappings:
        llm_message = (llm_message + ' 已按设备词库完成设备名称归一化。').strip()

    summary, merge_messages = _merge_same_paragraph_fault_terms(file_name, summary)
    if merge_messages:
        llm_message = (llm_message + ' ' + ' '.join(merge_messages)).strip()
    elif summary.get('phenomena') or summary.get('causes'):
        llm_message = (llm_message + ' 已完成同段故障现象/原因的语义归并。').strip()

    summary['triples'] = _derive_fault_chain_triples(summary)
    summary = _apply_ontology_constraints_to_summary(summary, ontology_constraints)

    graph_payload = _build_graph_payload_from_ontology(summary, ontology_constraints)
    declaration_payload = _build_document_definition(ontology_constraints)
    structured_payload = _build_structured_document_payload(graph_payload, file_name, declaration_payload)
    result = {
        'fileName': file_name,
        'sourceType': 'document',
        'documentSummary': summary,
        'documentPreview': text[:MAX_PREVIEW_CHARS],
        'llmEnabled': llm_enabled,
        'llmMessage': llm_message,
        'ontologyConstraintSource': ontology_constraints.get('source', 'fallback'),
        'ontologyConstraintCounts': {
            'entityTypes': len(ontology_constraints.get('entityTypes') or []),
            'relations': len(ontology_constraints.get('relations') or []),
            'patterns': len(ontology_constraints.get('patterns') or []),
        },
        'definition': declaration_payload,
        'entitySummaries': graph_payload.get('entities', []),
        'relationStats': graph_payload.get('relations', []),
        **meta,
        **structured_payload,
        'tripleRows': graph_payload.get('tripleRows', []),
        'appliedMappings': applied_mappings,
    }
    result['documentJsonPath'] = _export_document_json(result, file_name)
    result['documentTripleJsonPath'] = _export_document_triples(structured_payload, file_name)
    return result
