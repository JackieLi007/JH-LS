from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from xml.sax.saxutils import escape as xml_escape

from backend.offline_config import configure_offline_environment, offline_enabled, url_allowed_in_offline

configure_offline_environment()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
IMAGE_EXPORT_DIR = PROJECT_ROOT / '\u56fe\u7247\u62bd\u53d6\u7ed3\u679c'

SUPPORTED_IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff'}


def _file_suffix(file_name: str) -> str:
    return Path(file_name or '').suffix.lower()


def _safe_file_stem(file_name: str) -> str:
    stem = Path(file_name or 'image').stem.strip() or 'image'
    safe_chars = []
    for ch in stem:
        if ch.isalnum() or ch in ('-', '_'):
            safe_chars.append(ch)
        elif '\u4e00' <= ch <= '\u9fff':
            safe_chars.append(ch)
        else:
            safe_chars.append('_')
    normalized = ''.join(safe_chars).strip('_')
    return normalized or 'image'


def _xlsx_cell(value: object, column: str, row_index: int) -> str:
    text = xml_escape(str(value or ''))
    return f'<c r="{column}{row_index}" t="inlineStr"><is><t>{text}</t></is></c>'


def _export_image_excel(rows: list[dict], summary: dict, source_file_name: str) -> str:
    IMAGE_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    out_name = f'{_safe_file_stem(source_file_name)}_image_{timestamp}.xlsx'
    out_path = IMAGE_EXPORT_DIR / out_name
    headers = ['序号', '图片名称', '零件名称', '技术要求']
    body_rows = rows or [{
        'index': '',
        'imageName': summary.get('imageName') or Path(source_file_name).stem,
        'partName': summary.get('partName') or '',
        'technicalRequirement': '',
    }]
    sheet_rows = []
    sheet_rows.append(
        '<row r="1">'
        + ''.join(_xlsx_cell(header, chr(65 + index), 1) for index, header in enumerate(headers))
        + '</row>'
    )
    for row_number, item in enumerate(body_rows, start=2):
        values = [
            item.get('index') or row_number - 1,
            item.get('imageName') or summary.get('imageName') or Path(source_file_name).stem,
            item.get('partName') or summary.get('partName') or '',
            item.get('technicalRequirement') or item.get('imageText') or '',
        ]
        sheet_rows.append(
            f'<row r="{row_number}">'
            + ''.join(_xlsx_cell(value, chr(65 + index), row_number) for index, value in enumerate(values))
            + '</row>'
        )
    worksheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheetViews><sheetView workbookViewId="0"/></sheetViews>'
        '<sheetFormatPr defaultRowHeight="18"/>'
        '<cols><col min="1" max="1" width="10" customWidth="1"/>'
        '<col min="2" max="2" width="32" customWidth="1"/>'
        '<col min="3" max="3" width="28" customWidth="1"/>'
        '<col min="4" max="4" width="80" customWidth="1"/></cols>'
        '<sheetData>'
        + ''.join(sheet_rows)
        + '</sheetData></worksheet>'
    )
    with zipfile.ZipFile(out_path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '</Types>'
        ))
        archive.writestr('_rels/.rels', (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>'
        ))
        archive.writestr('xl/workbook.xml', (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="图片抽取结果" sheetId="1" r:id="rId1"/></sheets></workbook>'
        ))
        archive.writestr('xl/_rels/workbook.xml.rels', (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '</Relationships>'
        ))
        archive.writestr('xl/worksheets/sheet1.xml', worksheet)
    return str(out_path.relative_to(PROJECT_ROOT)).replace('\\', '/')


def _validate_image(file_name: str, content: bytes) -> dict:
    suffix = _file_suffix(file_name)
    if suffix not in SUPPORTED_IMAGE_EXTENSIONS:
        raise ValueError('暂仅支持 PNG、JPG、JPEG、WEBP、BMP、TIF 图片。')
    if not content:
        raise ValueError('上传图片为空。')
    mime_type = mimetypes.guess_type(file_name or '')[0] or 'image/png'
    return {
        'fileType': suffix.lstrip('.'),
        'mimeType': mime_type,
        'fileSize': len(content),
    }


def _image_dimensions(content: bytes) -> dict:
    try:
        from PIL import Image
        from io import BytesIO

        with Image.open(BytesIO(content)) as image:
            return {'width': image.width, 'height': image.height}
    except Exception:
        return {}


def _llm_config() -> tuple[str, str, str]:
    api_key = os.environ.get('LLM_API_KEY') or os.environ.get('OPENAI_API_KEY') or ''
    base_url = os.environ.get('LLM_BASE_URL') or os.environ.get('OPENAI_BASE_URL') or ''
    if not base_url and not offline_enabled():
        base_url = 'https://api.openai.com/v1'
    model = os.environ.get('LLM_VISION_MODEL') or 'qwen-vl-max'
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


def _decode_jsonish_string(value: str) -> str:
    try:
        return json.loads(f'"{value}"')
    except json.JSONDecodeError:
        return value.replace('\\"', '"').replace('\\n', '\n').replace('\\\\', '\\').strip()


def _jsonish_field(text: str, field: str) -> str:
    match = re.search(rf'"{re.escape(field)}"\s*:\s*"((?:\\.|[^"\\])*)"', text, re.S)
    if not match:
        return ''
    return _decode_jsonish_string(match.group(1)).strip()


def _clean_requirement_text(value: str) -> str:
    text = str(value or '').strip()
    text = re.sub(r'^\s*["\'\[{,]+', '', text)
    text = re.sub(r'["\'\]},]+\s*$', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def _numbered_requirements_from_text(text: str) -> list[dict]:
    normalized = str(text or '').replace('\\n', '\n')
    normalized = re.sub(r'[ \t]+', ' ', normalized)
    matches = list(re.finditer(r'(?:^|\n)\s*(\d+)[\.、]\s*(.+?)(?=(?:\n\s*\d+[\.、])|\Z)', normalized, re.S))
    rows = []
    for match in matches:
        requirement = _clean_requirement_text(match.group(2))
        if requirement:
            rows.append({'index': match.group(1), 'requirement': requirement})
    return rows


def _fallback_extract_from_text(file_name: str, text: str) -> dict:
    clean = str(text or '').strip()
    if clean.startswith('```'):
        clean = re.sub(r'^```(?:json)?', '', clean).strip()
        clean = re.sub(r'```$', '', clean).strip()

    image_name = _jsonish_field(clean, 'imageName') or _jsonish_field(clean, 'drawingName') or _jsonish_field(clean, 'title') or Path(file_name).stem
    part_name = _jsonish_field(clean, 'partName') or _jsonish_field(clean, 'name')
    ocr_text = _jsonish_field(clean, 'ocrText') or _jsonish_field(clean, 'text') or clean

    requirements = []
    for item_match in re.finditer(r'\{[^{}]*(?:"requirement"|"text"|"content")[^{}]*\}', clean, re.S):
        item_text = item_match.group(0)
        requirement = (
            _jsonish_field(item_text, 'requirement')
            or _jsonish_field(item_text, 'text')
            or _jsonish_field(item_text, 'content')
        )
        requirement = _clean_requirement_text(requirement)
        if not requirement:
            continue
        item_index = _jsonish_field(item_text, 'index') or str(len(requirements) + 1)
        requirements.append({'index': item_index, 'requirement': requirement})

    if not requirements:
        tech_block = clean
        tech_match = re.search(r'技术要求[:：]?(.*)', clean, re.S)
        if tech_match:
            tech_block = tech_match.group(1)
        requirements = _numbered_requirements_from_text(tech_block)

    if not requirements:
        requirements = _numbered_requirements_from_text(ocr_text)

    return {
        'imageName': image_name,
        'partName': part_name,
        'technicalRequirements': requirements,
        'ocrText': ocr_text,
    }


def _image_data_url(file_name: str, content: bytes) -> str:
    mime_type = mimetypes.guess_type(file_name or '')[0] or 'image/png'
    encoded = base64.b64encode(content).decode('ascii')
    return f'data:{mime_type};base64,{encoded}'


def _llm_extract(file_name: str, content: bytes) -> tuple[dict | None, str]:
    api_key, base_url, model = _llm_config()
    if not base_url:
        return None, '离线模式未配置本地 LLM_BASE_URL，无法调用视觉大模型抽取图片。'
    if not url_allowed_in_offline(base_url):
        return None, f'离线模式禁止访问公网视觉大模型接口：{base_url}。'
    if not api_key and not offline_enabled():
        return None, '未配置 LLM_API_KEY 或 OPENAI_API_KEY，无法调用视觉大模型抽取图片。'

    prompt = f"""请从机械零件工艺文档、机械图纸或扫描图片中抽取结构化信息，输出严格 JSON，不要输出 Markdown。
文件名：{file_name}

重点识别：
1. 零件名称、部件名称或图纸标题。
2. 图片中的主体文字通常是“技术要求”，请优先抽取“技术要求”标题下的编号条目。
3. 如果没有明确“技术要求”标题，再抽取“技术条件”“说明”“备注”等同类条目。
4. 如果文字是编号列表，请保留编号。

JSON 字段要求：
{{
  "imageName": "图片或图纸标题，无法判断则使用文件名",
  "partName": "零件/部件名称，无法判断则为空字符串",
  "technicalRequirements": [
    {{"index": "1", "requirement": "技术要求原文"}}
  ],
  "ocrText": "图片中识别出的主要文字"
}}

必须返回单行、合法、可被 JSON.parse 直接解析的 JSON。字符串内部不要直接换行，必须使用 \\n；不要尾随逗号；不要输出解释文字。
只抽取图片中能看清的内容。看不清或无法判断时不要编造。
"""
    payload = {
        'model': model,
        'messages': [
            {
                'role': 'system',
                'content': '你是机械图纸 OCR 与工艺知识抽取专家，只输出可解析 JSON。',
            },
            {
                'role': 'user',
                'content': [
                    {'type': 'text', 'text': prompt},
                    {'type': 'image_url', 'image_url': {'url': _image_data_url(file_name, content)}},
                ],
            },
        ],
        'temperature': 0.1,
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
        with urlopen(request, timeout=120) as response:
            data = json.loads(response.read().decode('utf-8'))
    except HTTPError as exc:
        body = exc.read().decode('utf-8', errors='replace')
        return None, f'视觉大模型接口返回错误：{exc.code} {body[:300]}'
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        return None, f'视觉大模型调用失败：{exc}'

    content_text = data.get('choices', [{}])[0].get('message', {}).get('content', '')
    try:
        return _extract_json_object(content_text), ''
    except (json.JSONDecodeError, TypeError) as exc:
        fallback_payload = _fallback_extract_from_text(file_name, content_text)
        if fallback_payload.get('technicalRequirements') or fallback_payload.get('ocrText'):
            return fallback_payload, f'视觉大模型返回非严格 JSON，已自动从原文提取技术要求：{exc}'
        return None, f'视觉大模型返回不是有效 JSON：{exc}'


def _as_list(value) -> list:
    return value if isinstance(value, list) else []


def _normalize_image_summary(file_name: str, raw: dict | None) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    requirements = []
    raw_items = (
        _as_list(raw.get('technicalRequirements'))
        or _as_list(raw.get('textItems'))
        or _as_list(raw.get('requirements'))
        or _as_list(raw.get('texts'))
    )
    for index, item in enumerate(raw_items, start=1):
        if isinstance(item, str):
            requirement = item.strip()
            item_index = str(index)
        elif isinstance(item, dict):
            requirement = str(item.get('requirement') or item.get('text') or item.get('content') or '').strip()
            item_index = str(item.get('index') or index).strip()
        else:
            continue
        if not requirement:
            continue
        requirements.append({
            'index': item_index,
            'requirement': requirement,
        })

    ocr_text = str(raw.get('ocrText') or raw.get('text') or '').strip()
    if not requirements and ocr_text:
        lines = [line.strip() for line in re.split(r'[\r\n]+', ocr_text) if line.strip()]
        requirements = [{'index': str(index), 'requirement': line} for index, line in enumerate(lines, start=1)]

    return {
        'imageName': str(raw.get('imageName') or raw.get('drawingName') or raw.get('title') or Path(file_name).stem).strip(),
        'partName': str(raw.get('partName') or raw.get('name') or '').strip(),
        'technicalRequirements': requirements,
        'ocrText': ocr_text,
    }


def get_image_parse_configuration(file_name: str, content: bytes) -> dict:
    meta = _validate_image(file_name, content)
    meta.update(_image_dimensions(content))
    return {
        'fileName': file_name,
        'sourceType': 'image',
        'needsMapping': False,
        'headers': [],
        **meta,
    }


def get_image_extraction_result(file_name: str, content: bytes) -> dict:
    meta = _validate_image(file_name, content)
    meta.update(_image_dimensions(content))
    llm_payload, llm_message = _llm_extract(file_name, content)
    llm_enabled = bool(llm_payload)
    if not llm_payload:
        llm_payload = _fallback_extract_from_text(file_name, '')
        llm_message = llm_message or '视觉大模型未返回有效图片抽取结果，已保留图片基础信息。'
    summary = _normalize_image_summary(file_name, llm_payload)
    table_rows = [
        {
            'index': item.get('index', ''),
            'imageName': summary.get('imageName') or Path(file_name).stem,
            'partName': summary.get('partName') or summary.get('imageName') or '',
            'technicalRequirement': item.get('requirement', ''),
        }
        for item in summary.get('technicalRequirements', [])
    ]
    result = {
        'fileName': file_name,
        'sourceType': 'image',
        'imageSummary': summary,
        'imageTableRows': table_rows,
        'llmEnabled': llm_enabled,
        'llmMessage': llm_message,
        **meta,
        'entities': [],
        'relations': [],
        'tripleRows': [],
        'counts': {
            'entities': 0,
            'relations': 0,
            'triples': 0,
        },
        'appliedMappings': [],
    }
    result['imageExcelPath'] = _export_image_excel(table_rows, summary, file_name)
    return result
