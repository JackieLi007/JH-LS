#!/usr/bin/env python3
"""Import fault-analysis spreadsheet data into Neo4j."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple
from xml.etree import ElementTree as ET


HEADER_MACHINE = "系统树节点"
HEADER_FUNCTION = "功能"
HEADER_UNIT_FAILURE = "故障模式名称"
HEADER_COMPONENT_REASON = "故障原因"
HEADER_SYSTEM_EFFECT = "高一层级影响"
HEADER_FINAL_EFFECT = "最终影响"
HEADER_SINGLE_POINT = "是否单点"
HEADER_SEVERITY = "严酷度等级"
HEADER_PROBABILITY = "发生概率等级"
HEADER_PHASE = "任务阶段"
HEADER_MEASURE = "设计措施"

HEADER_CANONICAL_MAP = {
    HEADER_MACHINE: HEADER_MACHINE,
    HEADER_FUNCTION: HEADER_FUNCTION,
    HEADER_UNIT_FAILURE: HEADER_UNIT_FAILURE,
    HEADER_COMPONENT_REASON: HEADER_COMPONENT_REASON,
    HEADER_SYSTEM_EFFECT: HEADER_SYSTEM_EFFECT,
    "高一层次影响": HEADER_SYSTEM_EFFECT,
    "高一层影响": HEADER_SYSTEM_EFFECT,
    HEADER_FINAL_EFFECT: HEADER_FINAL_EFFECT,
    HEADER_SINGLE_POINT: HEADER_SINGLE_POINT,
    HEADER_SEVERITY: HEADER_SEVERITY,
    "严重度等级": HEADER_SEVERITY,
    "严重度": HEADER_SEVERITY,
    HEADER_PROBABILITY: HEADER_PROBABILITY,
    "发生概率": HEADER_PROBABILITY,
    HEADER_PHASE: HEADER_PHASE,
    "发生阶段": HEADER_PHASE,
    HEADER_MEASURE: HEADER_MEASURE,
}

REQUIRED_HEADERS = [
    HEADER_MACHINE,
    HEADER_FUNCTION,
    HEADER_UNIT_FAILURE,
    HEADER_COMPONENT_REASON,
    HEADER_SYSTEM_EFFECT,
    HEADER_FINAL_EFFECT,
    HEADER_SINGLE_POINT,
    HEADER_SEVERITY,
    HEADER_PROBABILITY,
    HEADER_PHASE,
    HEADER_MEASURE,
]

HEADER_ALIASES = {
    HEADER_MACHINE: "machine_name",
    HEADER_FUNCTION: "function_name",
    HEADER_UNIT_FAILURE: "unit_failure_mode",
    HEADER_COMPONENT_REASON: "component_reason",
    HEADER_SYSTEM_EFFECT: "system_effect",
    HEADER_FINAL_EFFECT: "overall_effect",
    HEADER_SINGLE_POINT: "is_single_point",
    HEADER_SEVERITY: "severity_level",
    HEADER_PROBABILITY: "probability_level",
    HEADER_PHASE: "mission_phase",
    HEADER_MEASURE: "design_measure",
}

NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
ALLOWED_MAPPING_MODES = {"property", "node", "relationship"}

BASE_NODE_SPECS = {
    "machine": {"label": "单机", "property": "name", "row_field": "machine_name"},
    "function": {"label": "功能", "property": "name", "row_field": "function_name"},
    "component": {"label": "组件", "property": "name", "row_field": "component_name"},
    "system": {"label": "系统", "property": "name", "row_field": "system_name"},
    "unit_failure_mode": {
        "label": "单机级故障模式",
        "property": "key",
        "row_field": "unit_failure_key",
    },
    "component_failure_mode": {
        "label": "组件级故障模式",
        "property": "key",
        "row_field": "component_failure_key",
    },
    "system_failure_mode": {
        "label": "系统级故障模式",
        "property": "key",
        "row_field": "system_failure_key",
    },
    "overall_failure_mode": {
        "label": "总体级故障模式",
        "property": "key",
        "row_field": "overall_failure_key",
    },
    "is_single_point": {"label": "是否单点", "property": "key", "row_field": "single_point_key"},
    "severity_level": {"label": "严酷度等级", "property": "key", "row_field": "severity_key"},
    "probability_level": {"label": "发生概率", "property": "key", "row_field": "probability_key"},
    "mission_phase": {"label": "发生阶段", "property": "key", "row_field": "phase_key"},
    "design_measure": {"label": "设计措施", "property": "key", "row_field": "measure_key"},
}

BASE_NODE_ALIASES = {
    "单机": "machine",
    "功能": "function",
    "组件": "component",
    "系统": "system",
    "单机级故障模式": "unit_failure_mode",
    "组件级故障模式": "component_failure_mode",
    "系统级故障模式": "system_failure_mode",
    "总体级故障模式": "overall_failure_mode",
    "是否单点": "is_single_point",
    "严酷度等级": "severity_level",
    "发生概率": "probability_level",
    "发生阶段": "mission_phase",
    "设计措施": "design_measure",
}


@dataclass
class GraphRow:
    row_number: int
    machine_name: str
    function_name: str
    unit_failure_mode: str
    component_name: str
    component_failure_mode: str
    system_name: str
    system_failure_mode: str
    overall_failure_mode: str
    is_single_point: str
    severity_level: str
    probability_level: str
    mission_phase: str
    design_measure: str
    component_reason_raw: str
    system_effect_raw: str
    extra_columns: Dict[str, str]


@dataclass
class MappingRule:
    column: str
    mode: str
    target: Optional[str] = None
    property_name: Optional[str] = None
    label: Optional[str] = None
    key_prefix: Optional[str] = None
    connect_from: Optional[str] = None
    relation: Optional[str] = None
    source: Optional[str] = None
    relationship_property: Optional[str] = None
    when: str = "nonempty"
    equals: Optional[str] = None
    name_property: str = "name"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract spreadsheet data and import a fault knowledge graph into Neo4j."
    )
    parser.add_argument(
        "-i",
        "--input",
        type=Path,
        default=None,
        help="Input spreadsheet file (.xlsx or .csv). Defaults to the first spreadsheet in the current directory.",
    )
    parser.add_argument("--sheet", default=None, help="Worksheet name for .xlsx input.")
    parser.add_argument("--uri", default="bolt://localhost:7687", help="Neo4j Bolt URI.")
    parser.add_argument("--user", default="neo4j", help="Neo4j username.")
    parser.add_argument("--password", default=None, help="Neo4j password.")
    parser.add_argument("--database", default="neo4j", help="Neo4j database name.")
    parser.add_argument(
        "--mapping",
        type=Path,
        default=None,
        help="Optional mapping config (.json). Defaults to mapping.json in the current directory when present.",
    )
    parser.add_argument(
        "--extra-input",
        type=Path,
        default=None,
        help="Optional second spreadsheet (.xlsx or .csv). Rows are merged with the primary input by row order.",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Delete all existing graph data before importing.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and validate the data without connecting to Neo4j.",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=5,
        help="How many parsed rows to print during dry-run.",
    )
    return parser.parse_args()


def find_default_input(root: Path) -> Path:
    for suffix in (".xlsx", ".csv"):
        matches = sorted(
            path
            for path in root.iterdir()
            if path.suffix.lower() == suffix and not path.name.startswith("~$")
        )
        if matches:
            return matches[0]
    raise FileNotFoundError("No .xlsx or .csv file found in the working directory.")


def normalize_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r\n", "\n").replace("\r", "\n").strip()
    return text


def canonicalize_header_name(value: object) -> str:
    text = normalize_text(value)
    return HEADER_CANONICAL_MAP.get(text, text)


OPENING_BRACKETS = "([{（【"
CLOSING_BRACKETS = ")]}）】"
BRACKET_PAIRS = dict(zip(CLOSING_BRACKETS, OPENING_BRACKETS))


def split_top_level_text(value: str, separators: set[str]) -> List[str]:
    text = normalize_text(value)
    if not text:
        return []
    parts: List[str] = []
    current: List[str] = []
    stack: List[str] = []
    for ch in text:
        if ch in OPENING_BRACKETS:
            stack.append(ch)
        elif ch in CLOSING_BRACKETS:
            if stack and stack[-1] == BRACKET_PAIRS.get(ch):
                stack.pop()
        if ch in separators and not stack:
            segment = "".join(current).strip()
            if segment:
                parts.append(segment)
            current = []
            continue
        current.append(ch)
    segment = "".join(current).strip()
    if segment:
        parts.append(segment)
    return parts


def split_prefixed_text(value: str) -> Tuple[str, str]:
    text = normalize_text(value)
    if not text:
        return "", ""
    stack: List[str] = []
    for index, ch in enumerate(text):
        if ch in OPENING_BRACKETS:
            stack.append(ch)
            continue
        if ch in CLOSING_BRACKETS:
            if stack and stack[-1] == BRACKET_PAIRS.get(ch):
                stack.pop()
            continue
        if ch in {":", "："} and not stack:
            left = text[:index].strip()
            right = text[index + 1 :].strip()
            return left, right
    return "", text


def split_numbered_texts(value: str) -> List[str]:
    text = normalize_text(value).replace("\uFF1A", ":")
    if not text:
        return []
    matches = list(re.finditer(r"\d+\s*:", text))
    if not matches:
        return []

    segments: List[str] = []
    current_start = matches[0].end() if matches[0].start() == 0 else 0
    iter_matches = matches[1:] if matches[0].start() == 0 else matches
    for match in iter_matches:
        segment = text[current_start:match.start()].strip(" ;\uFF1B,\uFF0C\u3001")
        if segment:
            segments.append(segment)
        current_start = match.end()
    tail = text[current_start:].strip(" ;\uFF1B,\uFF0C\u3001")
    if tail:
        segments.append(tail)
    return segments if len(segments) > 1 else []


def split_prefixed_texts(value: str) -> List[Tuple[str, str]]:
    text = normalize_text(value)
    if not text:
        return []
    segments = split_numbered_texts(text)
    if not segments:
        segments = split_top_level_text(text, {"\n", ";", "；"})
        if len(segments) <= 1:
            colon_count = sum(1 for ch in text if ch in {":", "："})
            if colon_count > 1:
                segmented = split_top_level_text(text, {"\n", ";", "；", ",", "，"})
                if len(segmented) > 1:
                    segments = segmented
    parsed: List[Tuple[str, str]] = []
    for segment in segments or [text]:
        parsed.append(split_prefixed_text(segment))
    return parsed



def get_shared_strings(xlsx: zipfile.ZipFile) -> List[str]:
    if "xl/sharedStrings.xml" not in xlsx.namelist():
        return []
    root = ET.fromstring(xlsx.read("xl/sharedStrings.xml"))
    values: List[str] = []
    for item in root.findall("a:si", NS):
        texts = [text_node.text or "" for text_node in item.iterfind(".//a:t", NS)]
        values.append("".join(texts))
    return values


def get_sheet_path(xlsx: zipfile.ZipFile, sheet_name: Optional[str]) -> str:
    workbook = ET.fromstring(xlsx.read("xl/workbook.xml"))
    rels = ET.fromstring(xlsx.read("xl/_rels/workbook.xml.rels"))
    rel_map = {
        rel.attrib["Id"]: rel.attrib["Target"]
        for rel in rels
        if rel.tag.endswith("Relationship")
    }
    sheets = workbook.find("a:sheets", NS)
    if sheets is None:
        raise ValueError("Workbook does not contain any sheets.")

    selected = None
    if sheet_name:
        for sheet in sheets:
            if sheet.attrib.get("name") == sheet_name:
                selected = sheet
                break
        if selected is None:
            raise ValueError(f"Sheet '{sheet_name}' was not found.")
    else:
        selected = sheets[0]

    rel_id = selected.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
    target = rel_map[rel_id]
    return f"xl/{target}"


def read_xlsx_rows(path: Path, sheet_name: Optional[str]) -> Iterator[Dict[str, str]]:
    with zipfile.ZipFile(path) as xlsx:
        shared_strings = get_shared_strings(xlsx)
        sheet_path = get_sheet_path(xlsx, sheet_name)
        sheet = ET.fromstring(xlsx.read(sheet_path))
        for row in sheet.findall(".//a:sheetData/a:row", NS):
            current: Dict[str, str] = {}
            for cell in row.findall("a:c", NS):
                reference = cell.attrib.get("r", "")
                column = "".join(ch for ch in reference if ch.isalpha())
                cell_type = cell.attrib.get("t")
                value_node = cell.find("a:v", NS)
                value = ""
                if cell_type == "s" and value_node is not None:
                    value = shared_strings[int(value_node.text)]
                elif cell_type == "inlineStr":
                    inline = cell.find("a:is", NS)
                    if inline is not None:
                        value = "".join(node.text or "" for node in inline.iterfind(".//a:t", NS))
                elif value_node is not None:
                    value = value_node.text or ""
                current[column] = normalize_text(value)
            yield current


def read_csv_rows(path: Path) -> Iterator[Dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            yield {normalize_text(k): normalize_text(v) for k, v in row.items() if k is not None}


def load_records(
    path: Path,
    sheet_name: Optional[str],
    require_required_headers: bool = True,
) -> List[Dict[str, str]]:
    if not path.exists():
        raise SystemExit(f"Input file does not exist: {path}")
    suffix = path.suffix.lower()
    if suffix not in {".xlsx", ".csv"}:
        raise SystemExit("Only .xlsx and .csv files are supported.")
    if path.name.startswith("~$"):
        raise SystemExit(
            f"Input file looks like an Excel temporary lock file, not a real spreadsheet: {path}"
        )
    is_xlsx = suffix == ".xlsx"
    try:
        raw_rows = read_xlsx_rows(path, sheet_name) if is_xlsx else read_csv_rows(path)
    except zipfile.BadZipFile as exc:
        raise SystemExit(
            f"Failed to open spreadsheet as .xlsx: {path}. "
            "This usually means the file is not a real Excel workbook, is corrupted, "
            "or you selected an Excel temporary file that starts with '~$'."
        ) from exc
    return rows_to_records(raw_rows, is_xlsx=is_xlsx, require_required_headers=require_required_headers)


def merge_records(
    primary_records: Sequence[Dict[str, str]],
    extra_records: Sequence[Dict[str, str]],
) -> List[Dict[str, str]]:
    if len(primary_records) != len(extra_records):
        raise ValueError(
            "Primary input and extra input must contain the same number of data rows for row-wise merge. "
            f"Got {len(primary_records)} and {len(extra_records)}."
        )

    merged_records: List[Dict[str, str]] = []
    for index, (primary, extra) in enumerate(zip(primary_records, extra_records), start=2):
        merged = dict(primary)
        for key, value in extra.items():
            if key in merged and value:
                merged[key] = value
            elif key not in merged:
                merged[key] = value
        if not merged:
            raise ValueError(f"Merged row {index} is empty.")
        merged_records.append(merged)
    return merged_records


def rows_to_records(
    raw_rows: Iterable[Dict[str, str]],
    is_xlsx: bool,
    require_required_headers: bool = True,
) -> List[Dict[str, str]]:
    rows = list(raw_rows)
    if not rows:
        raise ValueError("Spreadsheet does not contain any rows.")

    if is_xlsx:
        header_map = rows[0]
        ordered_headers = {
            column: canonicalize_header_name(value)
            for column, value in header_map.items()
            if normalize_text(value)
        }
        missing = [header for header in REQUIRED_HEADERS if header not in ordered_headers.values()]
        if require_required_headers and missing:
            raise ValueError(f"Missing required headers: {', '.join(missing)}")

        name_to_column = {name: column for column, name in ordered_headers.items()}
        records = []
        for row in rows[1:]:
            record = {
                header: normalize_text(row.get(column, ""))
                for header, column in name_to_column.items()
            }
            records.append(record)
        return records

    header_names = {canonicalize_header_name(header) for header in rows[0].keys()}
    missing = [header for header in REQUIRED_HEADERS if header not in header_names]
    if require_required_headers and missing:
        raise ValueError(f"Missing required headers: {', '.join(missing)}")
    return [
        {canonicalize_header_name(header): normalize_text(value) for header, value in row.items()}
        for row in rows
    ]


def build_graph_rows(records: Sequence[Dict[str, str]]) -> List[GraphRow]:
    graph_rows: List[GraphRow] = []

    def pair_at(pairs: List[Tuple[str, str]], index: int) -> Tuple[str, str]:
        if not pairs:
            return "", ""
        if index < len(pairs):
            return pairs[index]
        return pairs[-1]

    for offset, record in enumerate(records, start=2):
        machine_name = normalize_text(record[HEADER_MACHINE])
        function_name = normalize_text(record[HEADER_FUNCTION])
        unit_failure_mode = normalize_text(record[HEADER_UNIT_FAILURE])
        component_reason_raw = normalize_text(record[HEADER_COMPONENT_REASON])
        system_effect_raw = normalize_text(record[HEADER_SYSTEM_EFFECT])
        overall_failure_mode = normalize_text(record[HEADER_FINAL_EFFECT])

        if not machine_name or not unit_failure_mode:
            continue

        component_pairs = split_prefixed_texts(component_reason_raw)
        system_pairs = split_prefixed_texts(system_effect_raw)

        pair_count = max(len(component_pairs), len(system_pairs), 1)
        for pair_index in range(pair_count):
            component_name, component_failure_mode = pair_at(component_pairs, pair_index)
            system_name, system_failure_mode = pair_at(system_pairs, pair_index)

            if not component_name:
                continue
            if not component_failure_mode:
                component_failure_mode = component_reason_raw or "未标注组件级故障模式"
            if not system_name:
                system_name = "未标注系统"
            if not system_failure_mode:
                system_failure_mode = system_effect_raw or "未标注系统级故障模式"
            if not overall_failure_mode:
                overall_failure_mode = "未标注总体级故障模式"

            graph_rows.append(
                GraphRow(
                    row_number=offset,
                    machine_name=machine_name,
                    function_name=function_name,
                    unit_failure_mode=unit_failure_mode,
                    component_name=component_name,
                    component_failure_mode=component_failure_mode,
                    system_name=system_name,
                    system_failure_mode=system_failure_mode,
                    overall_failure_mode=overall_failure_mode,
                    is_single_point=normalize_text(record[HEADER_SINGLE_POINT]),
                    severity_level=normalize_text(record[HEADER_SEVERITY]),
                    probability_level=normalize_text(record[HEADER_PROBABILITY]),
                    mission_phase=normalize_text(record[HEADER_PHASE]),
                    design_measure=normalize_text(record[HEADER_MEASURE]),
                    component_reason_raw=component_reason_raw,
                    system_effect_raw=system_effect_raw,
                    extra_columns={
                        key: normalize_text(value)
                        for key, value in record.items()
                        if key not in REQUIRED_HEADERS
                    },
                )
            )
    if not graph_rows:
        raise ValueError("No valid data rows were found after parsing.")
    return graph_rows


def make_failure_key(owner: str, mode: str, level: str) -> str:
    return f"{level}::{owner}::{mode}"


def serialize_rows(graph_rows: Sequence[GraphRow]) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for row in graph_rows:
        rows.append(
            {
                "row_number": row.row_number,
                "machine_name": row.machine_name,
                "function_name": row.function_name,
                "unit_failure_mode": row.unit_failure_mode,
                "unit_failure_key": make_failure_key(row.machine_name, row.unit_failure_mode, "unit"),
                "component_name": row.component_name,
                "component_failure_mode": row.component_failure_mode,
                "component_failure_key": make_failure_key(
                    row.component_name, row.component_failure_mode, "component"
                ),
                "system_name": row.system_name,
                "system_failure_mode": row.system_failure_mode,
                "system_failure_key": make_failure_key(row.system_name, row.system_failure_mode, "system"),
                "overall_failure_mode": row.overall_failure_mode,
                "overall_failure_key": f"overall::{row.overall_failure_mode}",
                "is_single_point": row.is_single_point,
                "severity_level": row.severity_level,
                "probability_level": row.probability_level,
                "mission_phase": row.mission_phase,
                "design_measure": row.design_measure,
                "component_reason_raw": row.component_reason_raw,
                "system_effect_raw": row.system_effect_raw,
                "single_point_key": f"single_point::{row.is_single_point or '未标注'}",
                "severity_key": f"severity::{row.severity_level or '未标注'}",
                "probability_key": f"probability::{row.probability_level or '未标注'}",
                "phase_key": f"phase::{row.mission_phase or '未标注'}",
                "measure_key": f"measure::{row.design_measure or '未标注'}",
                "extra_columns": row.extra_columns,
            }
        )
    return rows


def quote_cypher_identifier(value: str) -> str:
    return f"`{value.replace('`', '``')}`"


def resolve_base_node_alias(value: str) -> str:
    alias = normalize_text(value)
    if alias in BASE_NODE_SPECS:
        return alias
    if alias in BASE_NODE_ALIASES:
        return BASE_NODE_ALIASES[alias]
    allowed = ", ".join(sorted(BASE_NODE_SPECS))
    raise ValueError(f"Unknown target '{value}'. Supported targets: {allowed}")


def normalize_mapping_rule(raw_rule: Dict[str, Any], index: int) -> MappingRule:
    if not isinstance(raw_rule, dict):
        raise ValueError(f"Mapping rule #{index} must be an object.")

    column = normalize_text(raw_rule.get("column"))
    mode = normalize_text(raw_rule.get("mode")).lower()
    if not column:
        raise ValueError(f"Mapping rule #{index} is missing 'column'.")
    if mode not in ALLOWED_MAPPING_MODES:
        allowed_modes = ", ".join(sorted(ALLOWED_MAPPING_MODES))
        raise ValueError(f"Mapping rule #{index} has invalid mode '{mode}'. Allowed: {allowed_modes}")

    rule = MappingRule(
        column=column,
        mode=mode,
        target=normalize_text(raw_rule.get("target")) or None,
        property_name=normalize_text(raw_rule.get("property")) or None,
        label=normalize_text(raw_rule.get("label")) or None,
        key_prefix=normalize_text(raw_rule.get("key_prefix")) or None,
        connect_from=normalize_text(raw_rule.get("connect_from")) or None,
        relation=normalize_text(raw_rule.get("relation")) or None,
        source=normalize_text(raw_rule.get("source")) or None,
        relationship_property=normalize_text(raw_rule.get("relationship_property")) or None,
        when=normalize_text(raw_rule.get("when") or "nonempty").lower(),
        equals=normalize_text(raw_rule.get("equals")) or None,
        name_property=normalize_text(raw_rule.get("name_property") or "name"),
    )

    if rule.when not in {"nonempty", "equals"}:
        raise ValueError(f"Mapping rule #{index} has invalid 'when': {rule.when}")
    if rule.when == "equals" and rule.equals is None:
        raise ValueError(f"Mapping rule #{index} uses when='equals' but does not provide 'equals'.")

    if rule.mode == "property":
        if not rule.target or not rule.property_name:
            raise ValueError(f"Mapping rule #{index} in property mode requires 'target' and 'property'.")
        rule.target = resolve_base_node_alias(rule.target)
    elif rule.mode == "node":
        if not rule.label:
            raise ValueError(f"Mapping rule #{index} in node mode requires 'label'.")
        if rule.connect_from and not rule.relation:
            raise ValueError(f"Mapping rule #{index} in node mode requires 'relation' with 'connect_from'.")
        if rule.connect_from:
            rule.connect_from = resolve_base_node_alias(rule.connect_from)
        if not rule.key_prefix:
            rule.key_prefix = re.sub(r"\W+", "_", column).strip("_").lower() or "mapped"
    elif rule.mode == "relationship":
        if not rule.source or not rule.target or not rule.relation:
            raise ValueError(
                f"Mapping rule #{index} in relationship mode requires 'source', 'target', and 'relation'."
            )
        rule.source = resolve_base_node_alias(rule.source)
        rule.target = resolve_base_node_alias(rule.target)

    return rule


def load_mapping_rules(path: Path, available_columns: Sequence[str]) -> List[MappingRule]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Mapping file was not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to parse mapping file {path}: {exc}") from exc

    raw_rules = raw.get("columns") if isinstance(raw, dict) else None
    if not isinstance(raw_rules, list):
        raise ValueError("Mapping file must contain a top-level 'columns' array.")

    rules = [normalize_mapping_rule(item, index + 1) for index, item in enumerate(raw_rules)]
    missing_columns = sorted({rule.column for rule in rules if rule.column not in available_columns})
    if missing_columns:
        raise ValueError(f"Mapping columns were not found in the input file: {', '.join(missing_columns)}")
    return rules


def build_mapping_rows(
    rows: Sequence[Dict[str, object]],
    rule: MappingRule,
) -> List[Dict[str, str]]:
    mapping_rows: List[Dict[str, str]] = []
    for row in rows:
        extra_columns = row.get("extra_columns", {})
        if not isinstance(extra_columns, dict):
            continue
        value = normalize_text(extra_columns.get(rule.column, ""))
        entry = {
            "value": value,
            "machine_name": normalize_text(row.get("machine_name", "")),
            "function_name": normalize_text(row.get("function_name", "")),
            "component_name": normalize_text(row.get("component_name", "")),
            "system_name": normalize_text(row.get("system_name", "")),
            "unit_failure_key": normalize_text(row.get("unit_failure_key", "")),
            "component_failure_key": normalize_text(row.get("component_failure_key", "")),
            "system_failure_key": normalize_text(row.get("system_failure_key", "")),
            "overall_failure_key": normalize_text(row.get("overall_failure_key", "")),
            "single_point_key": normalize_text(row.get("single_point_key", "")),
            "severity_key": normalize_text(row.get("severity_key", "")),
            "probability_key": normalize_text(row.get("probability_key", "")),
            "phase_key": normalize_text(row.get("phase_key", "")),
            "measure_key": normalize_text(row.get("measure_key", "")),
        }
        if rule.mode == "node":
            entry["node_key"] = f"{rule.key_prefix}::{value or '未标注'}"
        mapping_rows.append(entry)
    return mapping_rows


def build_match_clause(variable: str, alias: str) -> str:
    spec = BASE_NODE_SPECS[alias]
    label = quote_cypher_identifier(spec["label"])
    prop = quote_cypher_identifier(spec["property"])
    row_field = spec["row_field"]
    return f"MATCH ({variable}:{label} {{{prop}: row.{row_field}}})"


def build_value_filter(rule: MappingRule) -> str:
    if rule.when == "equals":
        return "row.value = $expected_value"
    return "row.value <> ''"


def apply_mapping_rules(
    session: Any,
    rows: Sequence[Dict[str, object]],
    rules: Sequence[MappingRule],
) -> None:
    for rule in rules:
        mapping_rows = build_mapping_rows(rows, rule)
        if not mapping_rows:
            continue

        parameters: Dict[str, Any] = {"rows": mapping_rows}
        filter_clause = build_value_filter(rule)
        if rule.when == "equals":
            parameters["expected_value"] = rule.equals

        if rule.mode == "property":
            spec = BASE_NODE_SPECS[rule.target or ""]
            label = quote_cypher_identifier(spec["label"])
            match_property = quote_cypher_identifier(spec["property"])
            property_name = quote_cypher_identifier(rule.property_name or "")
            row_field = spec["row_field"]
            query = f"""
            UNWIND $rows AS row
            WITH row
            WHERE {filter_clause}
            MATCH (target:{label} {{{match_property}: row.{row_field}}})
            SET target.{property_name} = row.value
            """
            session.run(query, **parameters).consume()
            continue

        if rule.mode == "node":
            label = quote_cypher_identifier(rule.label or "")
            name_property = quote_cypher_identifier(rule.name_property)
            relation = quote_cypher_identifier(rule.relation or "")
            clauses = [
                "UNWIND $rows AS row",
                "WITH row",
                f"WHERE {filter_clause}",
                f"MERGE (mapped:{label} {{key: row.node_key}})",
                f"ON CREATE SET mapped.{name_property} = row.value",
            ]
            if rule.connect_from:
                clauses.append("WITH row, mapped")
                clauses.append(build_match_clause("source", rule.connect_from))
                clauses.append(f"MERGE (source)-[:{relation}]->(mapped)")
            session.run("\n".join(clauses), **parameters).consume()
            continue

        source_alias = rule.source or ""
        target_alias = rule.target or ""
        relation = quote_cypher_identifier(rule.relation or "")
        clauses = [
            "UNWIND $rows AS row",
            "WITH row",
            f"WHERE {filter_clause}",
            build_match_clause("source", source_alias),
            build_match_clause("target", target_alias),
            f"MERGE (source)-[rel:{relation}]->(target)",
        ]
        if rule.relationship_property:
            relationship_property = quote_cypher_identifier(rule.relationship_property)
            clauses.append(f"SET rel.{relationship_property} = row.value")
        session.run("\n".join(clauses), **parameters).consume()


def print_summary(graph_rows: Sequence[GraphRow], sample_size: int) -> None:
    machines = {row.machine_name for row in graph_rows}
    components = {row.component_name for row in graph_rows}
    systems = {row.system_name for row in graph_rows}
    print(f"Parsed rows: {len(graph_rows)}")
    print(f"Machines: {len(machines)}")
    print(f"Components: {len(components)}")
    print(f"Systems: {len(systems)}")
    print("")
    for row in graph_rows[:sample_size]:
        print(
            f"[Row {row.row_number}] 单机={row.machine_name} | 单机级故障模式={row.unit_failure_mode} | "
            f"组件={row.component_name} | 组件级故障模式={row.component_failure_mode} | "
            f"系统={row.system_name} | 系统级故障模式={row.system_failure_mode}"
        )


def import_to_neo4j(
    rows: Sequence[Dict[str, object]],
    uri: str,
    user: str,
    password: str,
    database: str,
    clear: bool,
    mapping_rules: Sequence[MappingRule],
) -> None:
    try:
        from neo4j import GraphDatabase
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "The 'neo4j' package is required for import. Install it with: pip install neo4j"
        ) from exc

    constraints = [
        "CREATE CONSTRAINT machine_name_unique IF NOT EXISTS FOR (n:`单机`) REQUIRE n.name IS UNIQUE",
        "CREATE CONSTRAINT function_name_unique IF NOT EXISTS FOR (n:`功能`) REQUIRE n.name IS UNIQUE",
        "CREATE CONSTRAINT component_name_unique IF NOT EXISTS FOR (n:`组件`) REQUIRE n.name IS UNIQUE",
        "CREATE CONSTRAINT system_name_unique IF NOT EXISTS FOR (n:`系统`) REQUIRE n.name IS UNIQUE",
        "CREATE CONSTRAINT occurrence_stage_key_unique IF NOT EXISTS FOR (n:`发生阶段`) REQUIRE n.key IS UNIQUE",
        "CREATE CONSTRAINT single_point_key_unique IF NOT EXISTS FOR (n:`是否单点`) REQUIRE n.key IS UNIQUE",
        "CREATE CONSTRAINT severity_level_key_unique IF NOT EXISTS FOR (n:`严酷度等级`) REQUIRE n.key IS UNIQUE",
        "CREATE CONSTRAINT probability_level_key_unique IF NOT EXISTS FOR (n:`发生概率`) REQUIRE n.key IS UNIQUE",
        "CREATE CONSTRAINT design_measure_key_unique IF NOT EXISTS FOR (n:`设计措施`) REQUIRE n.key IS UNIQUE",
        "CREATE CONSTRAINT unit_failure_mode_key_unique IF NOT EXISTS FOR (n:`单机级故障模式`) REQUIRE n.key IS UNIQUE",
        "CREATE CONSTRAINT component_failure_mode_key_unique IF NOT EXISTS FOR (n:`组件级故障模式`) REQUIRE n.key IS UNIQUE",
        "CREATE CONSTRAINT system_failure_mode_key_unique IF NOT EXISTS FOR (n:`系统级故障模式`) REQUIRE n.key IS UNIQUE",
        "CREATE CONSTRAINT overall_failure_mode_key_unique IF NOT EXISTS FOR (n:`总体级故障模式`) REQUIRE n.key IS UNIQUE",
    ]

    import_query = """
    UNWIND $rows AS row
    MERGE (machine:`单机` {name: row.machine_name})
    MERGE (function:`功能` {name: row.function_name})
    MERGE (machine)-[:`具有功能`]->(function)

    MERGE (component:`组件` {name: row.component_name})
    MERGE (system:`系统` {name: row.system_name})

    MERGE (unitMode:`单机级故障模式` {key: row.unit_failure_key})
      ON CREATE SET
        unitMode.name = row.unit_failure_mode,
        unitMode.owner = row.machine_name
    MERGE (machine)-[:`具有故障模式`]->(unitMode)

    MERGE (componentMode:`组件级故障模式` {key: row.component_failure_key})
      ON CREATE SET
        componentMode.name = row.component_failure_mode,
        componentMode.owner = row.component_name,
        componentMode.raw_text = row.component_reason_raw
    MERGE (component)-[:`具有故障模式`]->(componentMode)
    MERGE (componentMode)-[:`导致`]->(unitMode)

    MERGE (systemMode:`系统级故障模式` {key: row.system_failure_key})
      ON CREATE SET
        systemMode.name = row.system_failure_mode,
        systemMode.owner = row.system_name,
        systemMode.raw_text = row.system_effect_raw
    MERGE (system)-[:`具有故障模式`]->(systemMode)
    MERGE (unitMode)-[:`导致`]->(systemMode)

    MERGE (overallMode:`总体级故障模式` {key: row.overall_failure_key})
      ON CREATE SET
        overallMode.name = row.overall_failure_mode
    MERGE (systemMode)-[:`导致`]->(overallMode)

    MERGE (singlePoint:`是否单点` {key: row.single_point_key})
      ON CREATE SET singlePoint.name = row.is_single_point
    MERGE (severity:`严酷度等级` {key: row.severity_key})
      ON CREATE SET severity.name = row.severity_level
    MERGE (probability:`发生概率` {key: row.probability_key})
      ON CREATE SET probability.name = row.probability_level
    MERGE (phase:`发生阶段` {key: row.phase_key})
      ON CREATE SET phase.name = row.mission_phase
    MERGE (measure:`设计措施` {key: row.measure_key})
      ON CREATE SET measure.name = row.design_measure

    MERGE (unitMode)-[:`是否单点`]->(singlePoint)
    MERGE (unitMode)-[:`严酷度等级`]->(severity)
    MERGE (unitMode)-[:`发生概率`]->(probability)
    MERGE (unitMode)-[:`发生阶段`]->(phase)
    MERGE (unitMode)-[:`设计措施`]->(measure)
    """

    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        with driver.session(database=database) as session:
            for statement in constraints:
                session.run(statement).consume()
            if clear:
                session.run("MATCH (n) DETACH DELETE n").consume()
                for statement in constraints:
                    session.run(statement).consume()
            session.run(import_query, rows=list(rows)).consume()
            if mapping_rules:
                apply_mapping_rules(session, rows=rows, rules=mapping_rules)
    finally:
        driver.close()


def main() -> int:
    args = parse_args()
    input_path = args.input or find_default_input(Path.cwd())
    records = load_records(input_path, args.sheet, require_required_headers=True)
    if args.extra_input:
        extra_records = load_records(args.extra_input, args.sheet, require_required_headers=False)
        records = merge_records(records, extra_records)
    graph_rows = build_graph_rows(records)
    mapping_path = args.mapping
    mapping_rules = load_mapping_rules(mapping_path, records[0].keys()) if mapping_path else []

    if args.dry_run:
        print_summary(graph_rows, sample_size=args.sample_size)
        if mapping_rules:
            print(f"Loaded mapping rules: {len(mapping_rules)} from {mapping_path}")
        return 0

    if not args.password:
        raise SystemExit("Neo4j password is required. Use --password to provide it.")

    import_to_neo4j(
        rows=serialize_rows(graph_rows),
        uri=args.uri,
        user=args.user,
        password=args.password,
        database=args.database,
        clear=args.clear,
        mapping_rules=mapping_rules,
    )
    print(f"Imported {len(graph_rows)} rows into Neo4j from {input_path.name}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
