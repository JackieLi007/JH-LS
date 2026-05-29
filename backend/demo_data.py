from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from copy import deepcopy
from pathlib import Path
from zipfile import ZipFile

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / 'static'
TRIPLES_FILE = STATIC_DIR / 'fault_knowledge_graph_triples.json'
ENTITY_RELATION_FILE = STATIC_DIR / '\u5b9e\u4f53\u4e0e\u5173\u7cfb.json'
MAPPING_XLSX_FILE = STATIC_DIR / '\u5bf9\u5e94.xlsx'

ENTITY_TYPES_KEY = '\u5b9e\u4f53\u7c7b\u578b'
RELATION_TYPES_KEY = '\u5173\u7cfb\u7c7b\u578b'
ATTRIBUTE_VALUE = '\u5c5e\u6027\u503c'
SYSTEM = '\u7cfb\u7edf'
MACHINE = '\u5355\u673a'
COMPONENT = '\u7ec4\u4ef6'
FUNCTION = '\u529f\u80fd'
COMPONENT_FAULT = '\u7ec4\u4ef6\u7ea7\u6545\u969c\u6a21\u5f0f'
MACHINE_FAULT = '\u5355\u673a\u7ea7\u6545\u969c\u6a21\u5f0f'
SYSTEM_FAULT = '\u7cfb\u7edf\u7ea7\u6545\u969c\u6a21\u5f0f'
GLOBAL_FAULT = '\u603b\u4f53\u7ea7\u6545\u969c\u6a21\u5f0f'
EXISTS_FAULT = '\u5b58\u5728\u6545\u969c'

TYPE_PRIORITY = {
    GLOBAL_FAULT: 0,
    SYSTEM: 1,
    SYSTEM_FAULT: 2,
    MACHINE: 3,
    MACHINE_FAULT: 4,
    COMPONENT: 5,
    COMPONENT_FAULT: 6,
    FUNCTION: 7,
    ATTRIBUTE_VALUE: 8,
}

NS = {
    'main': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
    'rel': 'http://schemas.openxmlformats.org/package/2006/relationships',
}


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding='utf-8'))


ENTITY_RELATION_DATA = _load_json(ENTITY_RELATION_FILE)
TRIPLES_DATA = _load_json(TRIPLES_FILE)
ENTITIES = TRIPLES_DATA.get('entities', [])
TRIPLES = TRIPLES_DATA.get('triples', [])
ENTITY_BY_ID = {entity['id']: entity for entity in ENTITIES}


def _read_shared_strings(archive: ZipFile) -> list[str]:
    if 'xl/sharedStrings.xml' not in archive.namelist():
        return []
    root = ET.fromstring(archive.read('xl/sharedStrings.xml'))
    values = []
    for item in root.findall('main:si', NS):
        text_parts = [node.text or '' for node in item.findall('.//main:t', NS)]
        values.append(''.join(text_parts))
    return values


def _worksheet_path(archive: ZipFile) -> str | None:
    workbook = ET.fromstring(archive.read('xl/workbook.xml'))
    first_sheet = workbook.find('main:sheets/main:sheet', NS)
    if first_sheet is None:
        return None

    rel_id = first_sheet.attrib.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
    rels = ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))
    for rel in rels.findall('rel:Relationship', NS):
        if rel.attrib.get('Id') == rel_id:
            target = rel.attrib['Target'].lstrip('/')
            return target if target.startswith('xl/') else f'xl/{target}'
    return None


def _column_index(cell_ref: str) -> int:
    letters = ''.join(char for char in cell_ref if char.isalpha())
    index = 0
    for letter in letters:
        index = index * 26 + (ord(letter.upper()) - 64)
    return max(index - 1, 0)


def _cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get('t')
    value_node = cell.find('main:v', NS)

    if cell_type == 'inlineStr':
        inline = cell.find('main:is', NS)
        if inline is None:
            return ''
        return ''.join(node.text or '' for node in inline.findall('.//main:t', NS))

    if value_node is None:
        return ''

    value = value_node.text or ''
    if cell_type == 's' and value.isdigit():
        idx = int(value)
        return shared_strings[idx] if idx < len(shared_strings) else ''
    return value


def _read_first_two_rows_from_xlsx(path: Path) -> list[list[str]]:
    if not path.exists():
        return []

    with ZipFile(path, 'r') as archive:
        shared_strings = _read_shared_strings(archive)
        sheet_path = _worksheet_path(archive)
        if not sheet_path or sheet_path not in archive.namelist():
            return []

        root = ET.fromstring(archive.read(sheet_path))
        rows = []
        for row in root.findall('main:sheetData/main:row', NS):
            values: list[str] = []
            for cell in row.findall('main:c', NS):
                index = _column_index(cell.attrib.get('r', 'A1'))
                while len(values) <= index:
                    values.append('')
                values[index] = _cell_value(cell, shared_strings)
            rows.append(values)
            if len(rows) >= 2:
                break
        return rows


def _load_mapping_template() -> list[dict]:
    rows = _read_first_two_rows_from_xlsx(MAPPING_XLSX_FILE)
    if len(rows) < 2:
        return []

    headers = [value.strip() for value in rows[0][1:] if value and value.strip()]
    defaults = [value.strip() for value in rows[1][1:] if value and value.strip()]

    return [
        {
            'header': header,
            'defaultType': defaults[index] if index < len(defaults) else '',
        }
        for index, header in enumerate(headers)
    ]


MAPPING_TEMPLATE = _load_mapping_template()


def get_entity_relation_schema() -> dict:
    return {
        'entityTypes': ENTITY_RELATION_DATA.get(ENTITY_TYPES_KEY, []),
        'relationTypes': ENTITY_RELATION_DATA.get(RELATION_TYPES_KEY, []),
    }


def _chunk_for_source(source_type: str) -> tuple[int, int]:
    mapping = {'document': (0, 12), 'table': (12, 24), 'image': (24, 36)}
    start, end = mapping.get(source_type, (0, 12))
    return start, min(end, len(TRIPLES))


def _resolve_name(value):
    if isinstance(value, dict):
        return value.get('value', '')
    entity = ENTITY_BY_ID.get(value)
    return entity.get('name', value) if entity else value


def _resolve_type(value):
    if isinstance(value, dict):
        return ATTRIBUTE_VALUE
    entity = ENTITY_BY_ID.get(value)
    return entity.get('type', MACHINE) if entity else MACHINE


def get_parse_configuration(source_type: str, file_name: str) -> dict:
    schema = get_entity_relation_schema()
    default_names = {
        'document': '????_A08.docx',
        'table': 'FMEA???.xlsx',
        'image': '?????.png',
    }
    return {
        'fileName': file_name or default_names.get(source_type, '????'),
        'sourceType': source_type,
        'needsMapping': source_type in {'document', 'table'},
        'headers': deepcopy(MAPPING_TEMPLATE),
        'entityTypes': schema['entityTypes'],
    }


def get_extraction_result(source_type: str, file_name: str, mappings: list[dict] | None = None) -> dict:
    start, end = _chunk_for_source(source_type)
    triples = TRIPLES[start:end]

    related_ids = set()
    for triple in triples:
        if isinstance(triple['subject'], str) and triple['subject'] in ENTITY_BY_ID:
            related_ids.add(triple['subject'])
        if isinstance(triple['object'], str) and triple['object'] in ENTITY_BY_ID:
            related_ids.add(triple['object'])

    entity_rows = [
        {'name': ENTITY_BY_ID[entity_id]['name'], 'type': ENTITY_BY_ID[entity_id]['type']}
        for entity_id in related_ids
    ]

    relation_count = {}
    for triple in triples:
        relation_count[triple['predicate']] = relation_count.get(triple['predicate'], 0) + 1

    triple_rows = [
        {
            'subject': _resolve_name(triple['subject']),
            'predicate': triple['predicate'],
            'object': _resolve_name(triple['object']),
            'subjectType': _resolve_type(triple['subject']),
            'objectType': _resolve_type(triple['object']),
        }
        for triple in triples
    ]

    default_names = {
        'document': '????_A08.docx',
        'table': 'FMEA???.xlsx',
        'image': '?????.png',
    }

    return {
        'fileName': file_name or default_names.get(source_type, '????'),
        'sourceType': source_type,
        'tripleRows': triple_rows,
        'entities': sorted(entity_rows, key=lambda item: (TYPE_PRIORITY.get(item['type'], 99), item['name'])),
        'relations': [{'name': name, 'count': count} for name, count in relation_count.items()],
        'counts': {
            'triples': len(triple_rows),
            'entities': len(entity_rows),
            'relations': len(relation_count),
        },
        'appliedMappings': mappings or [],
    }

