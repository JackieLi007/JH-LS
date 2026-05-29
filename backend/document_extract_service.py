from __future__ import annotations

import json
import os
import re
from collections import Counter
from datetime import datetime
from io import BytesIO
from pathlib import Path
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
SAFETY = '安全注意事项'
SPECIFICATION = '技术参数'
ATTRIBUTE = '属性值'

MAX_LLM_TEXT_CHARS = 32000
MAX_PREVIEW_CHARS = 1800
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOCUMENT_EXPORT_DIR = PROJECT_ROOT / '\u6587\u6863\u62bd\u53d6\u7ed3\u679c'

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
    clean = str(text or '').strip()
    if clean.startswith('```'):
        clean = re.sub(r'^```(?:json)?', '', clean).strip()
        clean = re.sub(r'```$', '', clean).strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        start = clean.find('{')
        end = clean.rfind('}')
        if start >= 0 and end > start:
            return json.loads(clean[start:end + 1])
        raise


def _llm_extract(file_name: str, text: str) -> tuple[dict | None, str]:
    api_key, base_url, model = _llm_config()
    if not base_url:
        return None, '离线模式未配置本地 LLM_BASE_URL，已使用本地规则抽取。'
    if not url_allowed_in_offline(base_url):
        return None, f'离线模式禁止访问公网大模型接口：{base_url}，已使用本地规则抽取。'
    if not api_key and not offline_enabled():
        return None, '未配置 LLM_API_KEY 或 OPENAI_API_KEY，已使用本地规则抽取。'

    prompt = f"""请从机械设备使用说明书中抽取知识，输出严格 JSON，不要输出 Markdown。
文档名：{file_name}

JSON 字段要求：
{{
  "documentName": "文档名称",
  "equipment": "说明书对应设备或零件名称",
  "functions": [{{"name": "功能名称", "description": "功能说明", "evidence": "原文依据"}}],
  "features": [{{"name": "特点名称", "description": "特点说明", "evidence": "原文依据"}}],
  "maintenance": [{{"task": "维修/维护事项", "method": "维修方法", "cycle": "周期或条件", "tools": "工具", "warning": "注意事项"}}],
  "faultTypes": [{{"fault": "故障类型", "phenomenon": "故障现象", "cause": "可能原因", "handling": "处理方法"}}],
  "safetyNotes": [{{"note": "安全注意事项", "context": "适用场景"}}],
  "specifications": [{{"name": "参数名", "value": "数值或描述", "unit": "单位"}}]
}}

优先抽取与功能、结构特点、维修维护、故障类型、故障原因、处理方法、安全禁忌、关键技术参数有关的信息。
如果原文没有对应信息，请返回空数组。

文档内容：
{_relevant_text_for_llm(text)}
"""
    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': '你是机械工业知识图谱抽取专家，只输出可解析 JSON。'},
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
        with urlopen(request, timeout=90) as response:
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
        'functions': _as_list(raw.get('functions')) or fallback['functions'],
        'features': _as_list(raw.get('features')) or fallback['features'],
        'maintenance': _as_list(raw.get('maintenance')) or fallback['maintenance'],
        'faultTypes': _as_list(raw.get('faultTypes')) or fallback['faultTypes'],
        'safetyNotes': _as_list(raw.get('safetyNotes')) or fallback['safetyNotes'],
        'specifications': _as_list(raw.get('specifications')) or fallback['specifications'],
    }
    return summary


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

    doc_name = summary.get('documentName') or Path(file_name).stem
    equipment = summary.get('equipment') or doc_name
    add_triple(doc_name, DOCUMENT, '说明对象', equipment, EQUIPMENT)

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
            add_triple(fault, FAULT, '故障现象', phenomenon, ATTRIBUTE)
        if cause and cause != fault:
            add_triple(fault, FAULT, '故障原因', cause, ATTRIBUTE)
        if handling:
            add_triple(fault, FAULT, '处理方法', handling, ATTRIBUTE)

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


def get_document_extraction_result(file_name: str, content: bytes) -> dict:
    text, meta = extract_document_text(file_name, content)
    llm_payload, llm_message = _llm_extract(file_name, text)
    summary = _normalize_summary(file_name, text, llm_payload or {})
    graph_payload = _build_graph_payload(file_name, summary)
    result = {
        'fileName': file_name,
        'sourceType': 'document',
        'documentSummary': summary,
        'documentPreview': text[:MAX_PREVIEW_CHARS],
        'llmEnabled': bool(llm_payload),
        'llmMessage': llm_message,
        **meta,
        **graph_payload,
        'appliedMappings': [],
    }
    result['documentJsonPath'] = _export_document_json(result, file_name)
    return result
