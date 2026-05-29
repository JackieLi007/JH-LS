from __future__ import annotations

import argparse
import json
import os
import sys
import zipfile
from difflib import SequenceMatcher
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest
from xml.sax.saxutils import escape


PROJECT_ROOT = Path(__file__).resolve().parent
TOP_COUNT = 5
SNAPSHOT_PATH = PROJECT_ROOT / 'artifacts' / 'neo4j_index' / 'graph_snapshot.json'
DEFAULT_API_URL = 'http://127.0.0.1:5000/api/query'

FAULT_CHAIN_RELATION_LABELS = {
    'HAS_FAILURE_MODE',
    'HAS',
    'INCLUDE',
    'LEADS_TO',
    'LEVEL_CLASSIFICATION',
    'OCCURRENCE_STAGE',
    'PROBABILITY',
    'SOLUTION',
    'YES_OR_NO',
    '故障模式',
    '具有故障模式',
    '存在故障',
    '有',
    '包含',
    '导致',
    '严酷度等级',
    '发生阶段',
    '发生概率',
    '设计措施',
    '是否单点',
}

ONTOLOGY_PLACEHOLDER_NODE_NAMES = {
    '总体',
    '总体功能',
    '总体级故障模式',
    '总体级故障现象',
    '系统',
    '系统功能',
    '系统级故障模式',
    '系统级故障现象',
    '单机',
    '单机功能',
    '单机级故障模式',
    '单机级故障现象',
    '组件',
    '零部组件',
    '零部组件功能',
    '组件级故障模式',
    '组件级故障现象',
    '功能',
    '属性',
    '发生阶段',
    '是否单点',
    '严酷度等级',
    '发生概率',
    '设计措施',
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='批量读取 TXT 查询，输出每条查询在知识库中的 Top5 节点到 Excel。',
    )
    parser.add_argument(
        'input',
        nargs='?',
        default='queries.txt',
        help='输入 TXT 文件路径，默认 queries.txt；每行一条查询。也可传入 - 从标准输入读取。',
    )
    parser.add_argument(
        '-o',
        '--output',
        default='',
        help='输出 .xlsx 文件路径；默认生成在输入文件同目录，文件名为 <输入文件名>_top5.xlsx。',
    )
    llm_group = parser.add_mutually_exclusive_group()
    llm_group.add_argument(
        '--use-llm',
        dest='use_llm',
        action='store_true',
        default=True,
        help='启用大模型优先的故障链查询；默认启用。',
    )
    llm_group.add_argument(
        '--no-llm',
        dest='use_llm',
        action='store_false',
        help='关闭大模型，直接走 BERT/本地规则兜底。',
    )
    parser.add_argument(
        '--fault-chain',
        action='store_true',
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        '--all-nodes',
        action='store_true',
        help='改为全知识库节点检索；默认使用故障链查询。',
    )
    parser.add_argument(
        '--api-url',
        default=DEFAULT_API_URL,
        help=f'后端故障链查询接口，默认 {DEFAULT_API_URL}；传空字符串可跳过 API。',
    )
    parser.add_argument(
        '--api-timeout',
        type=float,
        default=20.0,
        help='单条查询请求后端 API 的超时时间，单位秒，默认 20。',
    )
    parser.add_argument(
        '--detail',
        action='store_true',
        help='Top1-Top5 单元格中追加层级、所属对象和分数。',
    )
    return parser.parse_args()


def read_queries(input_arg: str) -> list[str]:
    if input_arg == '-':
        content = sys.stdin.read()
    else:
        input_path = Path(input_arg)
        if not input_path.exists():
            raise FileNotFoundError(f'输入文件不存在：{input_path}')
        content = read_text_with_fallback(input_path)

    queries = [line.strip() for line in content.splitlines()]
    return [query for query in queries if query]


def read_text_with_fallback(path: Path) -> str:
    last_error: UnicodeDecodeError | None = None
    for encoding in ('utf-8-sig', 'utf-8', 'gb18030'):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    raise UnicodeDecodeError(
        last_error.encoding if last_error else 'unknown',
        last_error.object if last_error else b'',
        last_error.start if last_error else 0,
        last_error.end if last_error else 0,
        f'无法按 utf-8-sig、utf-8 或 gb18030 读取文本：{path}',
    )


def default_output_path(input_arg: str) -> Path:
    if input_arg == '-':
        return PROJECT_ROOT / 'query_top5_results.xlsx'
    input_path = Path(input_arg)
    return input_path.with_name(f'{input_path.stem}_top5.xlsx')


def normalize_api_url(raw_url: str) -> str:
    value = str(raw_url or '').strip().rstrip('/')
    if not value:
        return ''
    if value.endswith('/api/query'):
        return value
    return f'{value}/api/query'


def build_result_rows_from_api(
    queries: list[str],
    api_url: str,
    timeout: float,
    detail: bool,
) -> list[list[str]]:
    rows = [['输入内容', 'top1', 'top2', 'top3', 'top4', 'top5']]
    total = len(queries)
    for index, query in enumerate(queries, start=1):
        top_matches = query_fault_chain_api(api_url, query, timeout)[:TOP_COUNT]
        top_values = [format_match(match, detail) for match in top_matches]
        top_values.extend([''] * (TOP_COUNT - len(top_values)))
        rows.append([query, *top_values])
        top1 = top_values[0] if top_values else ''
        print(f'[{index}/{total}] {query} -> {top1 or "未匹配"}', flush=True)
    return rows


def query_fault_chain_api(api_url: str, query: str, timeout: float) -> list[dict[str, Any]]:
    body = json.dumps({'text': query}, ensure_ascii=False).encode('utf-8')
    req = urlrequest.Request(
        api_url,
        data=body,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urlrequest.urlopen(req, timeout=timeout) as response:
            payload = json.loads(response.read().decode('utf-8'))
    except urlerror.HTTPError as exc:
        error_body = exc.read().decode('utf-8', errors='replace')
        try:
            payload = json.loads(error_body)
        except json.JSONDecodeError:
            raise RuntimeError(f'后端 API 返回 HTTP {exc.code}: {error_body}') from exc
    except urlerror.URLError as exc:
        raise RuntimeError(f'无法连接后端 API：{exc.reason}') from exc

    result = payload.get('result') if isinstance(payload, dict) else None
    if not isinstance(result, dict):
        return []
    raw_matches = result.get('topMatches')
    if not isinstance(raw_matches, list):
        return []
    return normalize_match_list(raw_matches)


def normalize_match_list(raw_matches: list[Any]) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for index, raw_match in enumerate(raw_matches[:TOP_COUNT], start=1):
        if not isinstance(raw_match, dict):
            continue
        name = str(raw_match.get('name') or raw_match.get('matchedNode') or '').strip()
        if not name:
            continue
        matches.append({
            'rank': int(raw_match.get('rank') or index),
            'id': str(raw_match.get('id') or raw_match.get('nodeId') or '').strip(),
            'name': name,
            'level': str(raw_match.get('level') or '').strip(),
            'owner': str(raw_match.get('owner') or '').strip(),
            'score': raw_match.get('score') if raw_match.get('score') not in (None, '') else '',
            'confidence': raw_match.get('confidence') if raw_match.get('confidence') not in (None, '') else '',
            'matchedKeywords': raw_match.get('matchedKeywords') if isinstance(raw_match.get('matchedKeywords'), list) else [],
        })
    return matches


def load_query_backend(use_llm: bool) -> Any | None:
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    load_env_files()
    os.environ['FAULT_QUERY_LLM_ENABLED'] = '1' if use_llm else '0'

    try:
        from backend import app as fault_app
    except Exception as exc:
        print(f'后端查询模块不可用，改用脚本内置检索：{exc}', flush=True)
        return None

    return fault_app


def load_env_files() -> None:
    for env_path in (PROJECT_ROOT / '.env', PROJECT_ROOT / 'backend' / '.env'):
        if not env_path.exists():
            continue
        for raw_line in env_path.read_text(encoding='utf-8').splitlines():
            line = raw_line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, value = line.split('=', 1)
            key = key.strip().lstrip('\ufeff')
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def fetch_graph(fault_app: Any | None) -> dict[str, list[dict[str, Any]]]:
    if fault_app is not None:
        return fetch_graph_readonly(fault_app)
    return fetch_graph_standalone()


def fetch_graph_readonly(fault_app: Any) -> dict[str, list[dict[str, Any]]]:
    with fault_app.get_driver().session(database=fault_app.get_database()) as session:
        node_records = session.run(
            'MATCH (n) '
            'RETURN elementId(n) AS id, labels(n)[0] AS label, properties(n) AS props '
            'ORDER BY label, coalesce(n.owner, ""), coalesce(n.name, "")',
        ).data()
        edge_records = session.run(
            'MATCH (a)-[r]->(b) '
            'RETURN elementId(a) AS source, type(r) AS relation, elementId(b) AS target '
            'ORDER BY relation',
        ).data()

    nodes = [
        fault_app.build_node_view(record)
        for record in node_records
        if not fault_app.is_ontology_placeholder_record(record)
    ]
    visible_node_ids = {node['id'] for node in nodes}
    edges = [
        fault_app.build_edge_view(record)
        for record in edge_records
        if record.get('source') in visible_node_ids and record.get('target') in visible_node_ids
    ]
    return {'nodes': nodes, 'edges': edges}


def fetch_graph_standalone() -> dict[str, list[dict[str, Any]]]:
    load_env_files()
    try:
        return fetch_graph_from_neo4j_driver()
    except Exception as exc:
        print(f'Neo4j 直连不可用，改用本地快照：{exc}', flush=True)
        return fetch_graph_from_snapshot(SNAPSHOT_PATH)


def fetch_graph_from_neo4j_driver() -> dict[str, list[dict[str, Any]]]:
    try:
        from neo4j import GraphDatabase
    except Exception as exc:
        raise RuntimeError('当前 Python 环境缺少 neo4j 驱动') from exc

    uri = os.environ.get('NEO4J_URI', 'bolt://127.0.0.1:7687')
    username = os.environ.get('NEO4J_USERNAME', 'neo4j')
    password = os.environ.get('NEO4J_PASSWORD', '').strip() or '12345678'
    database = os.environ.get('NEO4J_DATABASE', '').strip() or None

    driver = GraphDatabase.driver(uri, auth=(username, password))
    try:
        with driver.session(database=database) as session:
            node_records = session.run(
                'MATCH (n) '
                'RETURN elementId(n) AS id, labels(n)[0] AS label, properties(n) AS props '
                'ORDER BY label, coalesce(n.owner, ""), coalesce(n.name, "")',
            ).data()
            edge_records = session.run(
                'MATCH (a)-[r]->(b) '
                'RETURN elementId(a) AS source, type(r) AS relation, elementId(b) AS target '
                'ORDER BY relation',
            ).data()
    finally:
        driver.close()

    nodes = [
        build_node_view_standalone(record)
        for record in node_records
        if not is_ontology_placeholder_record_standalone(record)
    ]
    visible_node_ids = {node['id'] for node in nodes}
    edges = [
        build_edge_view_standalone(record)
        for record in edge_records
        if record.get('source') in visible_node_ids and record.get('target') in visible_node_ids
    ]
    return {'nodes': nodes, 'edges': edges}


def fetch_graph_from_snapshot(path: Path) -> dict[str, list[dict[str, Any]]]:
    if not path.exists():
        raise FileNotFoundError(f'未找到 Neo4j 快照文件：{path}')
    data = json.loads(path.read_text(encoding='utf-8'))
    raw_nodes = data.get('nodes') if isinstance(data.get('nodes'), list) else []
    raw_edges = data.get('edges') if isinstance(data.get('edges'), list) else []

    nodes = [build_node_view_from_snapshot(item) for item in raw_nodes if isinstance(item, dict)]
    visible_node_ids = {node['id'] for node in nodes}
    edges = [
        build_edge_view_from_snapshot(item)
        for item in raw_edges
        if isinstance(item, dict)
        and item.get('source') in visible_node_ids
        and item.get('target') in visible_node_ids
    ]
    return {'nodes': nodes, 'edges': edges}


def build_node_view_standalone(record: dict[str, Any]) -> dict[str, Any]:
    label = str(record.get('label') or '').strip()
    props = record.get('props') if isinstance(record.get('props'), dict) else {}
    name = str(props.get('name') or props.get('owner') or label or record.get('id') or '').strip()
    owner = str(props.get('owner') or '').strip()
    raw_text = str(props.get('raw_text') or props.get('rawText') or '').strip()
    key = str(props.get('key') or '').strip()
    return {
        'id': str(record.get('id') or '').strip(),
        'name': name,
        'label': label,
        'level': label,
        'type': label,
        'owner': owner,
        'rawText': raw_text,
        'key': key,
        'description': raw_text or key or f'{label}节点：{name}',
        'status': label,
    }


def build_node_view_from_snapshot(item: dict[str, Any]) -> dict[str, Any]:
    props = item.get('attributes') if isinstance(item.get('attributes'), dict) else {}
    labels = props.get('_labels') if isinstance(props.get('_labels'), list) else []
    label = str(labels[0] if labels else item.get('type') or '').strip()
    name = str(item.get('name') or props.get('name') or props.get('owner') or label or item.get('id') or '').strip()
    owner = str(props.get('owner') or '').strip()
    raw_text = str(props.get('raw_text') or props.get('rawText') or item.get('description') or '').strip()
    key = str(props.get('key') or '').strip()
    return {
        'id': str(item.get('id') or '').strip(),
        'name': name,
        'label': label,
        'level': label,
        'type': str(item.get('type') or label).strip(),
        'owner': owner,
        'rawText': raw_text,
        'key': key,
        'description': str(item.get('description') or raw_text or key or f'{label}节点：{name}'),
        'status': label,
    }


def build_edge_view_standalone(record: dict[str, Any]) -> dict[str, Any]:
    relation = str(record.get('relation') or '').strip()
    return {
        'from': str(record.get('source') or '').strip(),
        'to': str(record.get('target') or '').strip(),
        'label': relation,
        'relationType': relation,
        'rawRelationType': relation,
        'strength': 'normal',
    }


def build_edge_view_from_snapshot(item: dict[str, Any]) -> dict[str, Any]:
    attrs = item.get('attributes') if isinstance(item.get('attributes'), dict) else {}
    relation = str(attrs.get('_neo4j_type') or item.get('type') or '').strip()
    return {
        'from': str(item.get('source') or '').strip(),
        'to': str(item.get('target') or '').strip(),
        'label': relation,
        'relationType': relation,
        'rawRelationType': relation,
        'strength': 'normal',
    }


def is_ontology_placeholder_record_standalone(record: dict[str, Any]) -> bool:
    label = str(record.get('label') or '').strip()
    props = record.get('props') if isinstance(record.get('props'), dict) else {}
    name = str(props.get('name') or props.get('owner') or label).strip()
    owner = str(props.get('owner') or '').strip()
    raw_text = str(props.get('raw_text') or '').strip()
    key = str(props.get('key') or '').strip()
    return (
        not owner
        and not raw_text
        and not key
        and name in ONTOLOGY_PLACEHOLDER_NODE_NAMES
        and (name == label or label in ONTOLOGY_PLACEHOLDER_NODE_NAMES)
    )


def build_result_rows(
    queries: list[str],
    graph: dict[str, list[dict[str, Any]]],
    fault_app: Any | None,
    detail: bool,
    fault_chain: bool,
) -> list[list[str]]:
    rows = [['输入内容', 'top1', 'top2', 'top3', 'top4', 'top5']]
    total = len(queries)
    for index, query in enumerate(queries, start=1):
        ranked = rank_query_nodes(query, graph, fault_app, fault_chain)
        top_matches = build_top_matches(query, ranked, fault_app)[:TOP_COUNT]
        top_values = [format_match(match, detail) for match in top_matches]
        top_values.extend([''] * (TOP_COUNT - len(top_values)))
        rows.append([query, *top_values])
        top1 = top_values[0] if top_values else ''
        print(f'[{index}/{total}] {query} -> {top1 or "未匹配"}', flush=True)
    return rows


def rank_query_nodes(
    query: str,
    graph: dict[str, list[dict[str, Any]]],
    fault_app: Any | None,
    fault_chain: bool,
) -> list[dict[str, Any]]:
    if fault_app is not None:
        if fault_chain:
            ranked = fault_app.rank_fault_chain_query_nodes(query, graph)
            if ranked:
                return ranked
            return []
        candidates = fault_app.semantic_candidate_pool(graph['nodes'])
        ranked = fault_app.rank_nodes_with_local_similarity(query, candidates)
        if ranked:
            return ranked
        return [{**node, 'score': 1} for node in candidates[:TOP_COUNT]]

    if fault_chain:
        return rank_fault_chain_nodes_standalone(query, graph)

    ranked = rank_nodes_standalone(query, graph['nodes'])
    if ranked:
        return ranked
    return []


def rank_fault_chain_nodes_standalone(
    query: str,
    graph: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    ranked = rank_nodes_standalone(query, graph['nodes'])
    if not ranked:
        return []

    connected_ids = fault_chain_connected_node_ids_standalone(graph)
    connected_failures = [
        node for node in ranked
        if node.get('id') in connected_ids and is_failure_mode_node_standalone(node)
    ]
    if connected_failures:
        return connected_failures

    failures = [node for node in ranked if is_failure_mode_node_standalone(node)]
    if failures:
        return failures
    return ranked


def fault_chain_connected_node_ids_standalone(graph: dict[str, list[dict[str, Any]]]) -> set[str]:
    ids: set[str] = set()
    for edge in graph['edges']:
        if not is_fault_chain_edge_standalone(edge):
            continue
        ids.add(str(edge.get('from') or ''))
        ids.add(str(edge.get('to') or ''))
    return {item for item in ids if item}


def is_fault_chain_edge_standalone(edge: dict[str, Any]) -> bool:
    relation = str(edge.get('relationType') or edge.get('label') or edge.get('rawRelationType') or '').strip()
    return relation in FAULT_CHAIN_RELATION_LABELS


def is_failure_mode_node_standalone(node: dict[str, Any]) -> bool:
    fields = ('type', 'level', 'label', 'name', 'description', 'rawText', 'key')
    text = ''.join(str(node.get(field, '')) for field in fields)
    return (
        '故障模式' in text
        or '故障现象' in text
        or str(node.get('type') or '') in {'root-cause', 'fault', 'impact'}
    )


def rank_nodes_standalone(query: str, nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    variants = query_variants_standalone(query)
    terms = expanded_query_terms_standalone(variants)
    ranked = []
    for node in nodes:
        score = local_node_match_score_standalone(node, variants, terms)
        ranked.append({**node, 'score': max(1, score)})
    ranked.sort(key=lambda item: (-int(item.get('score') or 0), item.get('name', '')))
    return ranked


def local_node_match_score_standalone(node: dict[str, Any], variants: list[str], terms: set[str]) -> int:
    name = normalize_text(str(node.get('name') or ''))
    corpus = node_corpus_standalone(node)
    score = 0

    for variant in variants:
        if variant and name == variant:
            score += 120
        elif variant and variant in name:
            score += 80
        elif variant and name and name in variant:
            score += 48
        if variant and variant in corpus:
            score += 36

    for term in terms:
        if not term:
            continue
        if term in name:
            score += max(8, len(term) * 5)
        elif term in corpus:
            score += max(3, len(term) * 2)

    best_name_ratio = max((SequenceMatcher(None, variant, name).ratio() for variant in variants if variant and name), default=0)
    if best_name_ratio >= 0.35:
        score += int(best_name_ratio * 30)

    query_grams = set().union(*(ngrams_text(variant) for variant in variants))
    corpus_grams = ngrams_text(corpus)
    if query_grams and corpus_grams:
        overlap = len(query_grams & corpus_grams) / len(query_grams)
        if overlap >= 0.15:
            score += int(overlap * 24)

    return score


def build_top_matches(query: str, ranked: list[dict[str, Any]], fault_app: Any | None) -> list[dict[str, Any]]:
    if fault_app is not None:
        return fault_app.build_top_matches(query, ranked)

    matches = []
    for index, item in enumerate(ranked[:TOP_COUNT], start=1):
        score = int(item.get('score') or 0)
        matches.append({
            'rank': index,
            'id': str(item.get('id') or ''),
            'name': str(item.get('name') or item.get('label') or item.get('id') or ''),
            'level': str(item.get('level') or ''),
            'owner': str(item.get('owner') or ''),
            'score': score,
            'confidence': max(1, min(100, score)),
            'matchedKeywords': matched_terms_standalone(query, item),
        })
    return matches


def normalize_text(text: str) -> str:
    value = str(text or '').lower().strip()
    replacements = {
        '渗漏': '泄漏',
        '外漏': '泄漏',
        '漏液': '泄漏',
        '漏油': '泄漏',
        '无法打开': '打不开',
        '不能打开': '打不开',
        '开不了': '打不开',
        '开启失败': '打不开',
        '卡死': '卡滞',
        '阀门': '阀',
    }
    for source, target in sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True):
        value = value.replace(source, target)
    return value


def query_variants_standalone(query: str) -> list[str]:
    raw = str(query or '').strip().lower()
    normalized = normalize_text(raw)
    variants = {raw, normalized}
    return sorted((item for item in variants if item), key=len, reverse=True)


def expanded_query_terms_standalone(variants: list[str]) -> set[str]:
    terms = set(variants)
    synonym_groups = [
        ('泄漏', '外漏', '渗漏', '漏液', '漏油'),
        ('软管', '摇摆软管'),
        ('动力下降', '推力下降', '压力下降', '比冲过小', '无推力'),
        ('打不开', '无法打开', '不能打开', '开不了', '开启失败', '卡滞'),
        ('阀', '阀门', '电磁阀', '单向阀'),
        ('发动机', '引擎'),
    ]
    for variant in variants:
        for group in synonym_groups:
            if any(term in variant for term in group):
                terms.update(normalize_text(term) for term in group)
        terms.update(ngrams_text(variant))
    return {term for term in terms if term}


def node_corpus_standalone(node: dict[str, Any]) -> str:
    fields = ('name', 'owner', 'rawText', 'key', 'level', 'label', 'type', 'description', 'status')
    return normalize_text(' '.join(str(node.get(field, '')) for field in fields))


def ngrams_text(text: str) -> set[str]:
    value = normalize_text(text)
    grams = set()
    for size in (2, 3, 4):
        for index in range(len(value) - size + 1):
            gram = value[index:index + size]
            if gram.strip():
                grams.add(gram)
    return grams


def matched_terms_standalone(query: str, node: dict[str, Any]) -> list[str]:
    variants = query_variants_standalone(query)
    terms = expanded_query_terms_standalone(variants)
    corpus = node_corpus_standalone(node)
    matched = [term for term in sorted(terms, key=len, reverse=True) if term in corpus]
    return matched[:6]


def format_match(match: dict[str, Any], detail: bool) -> str:
    name = str(match.get('name') or match.get('label') or match.get('id') or '').strip()
    if not detail:
        return name

    extras = []
    for key, label in (('level', '层级'), ('owner', '所属')):
        value = str(match.get(key) or '').strip()
        if value:
            extras.append(f'{label}:{value}')
    score = match.get('score')
    if score not in (None, ''):
        extras.append(f'分数:{score}')
    return f'{name}（{"；".join(extras)}）' if extras else name


def write_xlsx(rows: list[list[str]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    worksheet_xml = build_worksheet_xml(rows)
    workbook_xml = build_workbook_xml()
    styles_xml = build_styles_xml()
    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    files = {
        '[Content_Types].xml': build_content_types_xml(),
        '_rels/.rels': build_root_rels_xml(),
        'docProps/app.xml': build_app_props_xml(),
        'docProps/core.xml': build_core_props_xml(now),
        'xl/workbook.xml': workbook_xml,
        'xl/_rels/workbook.xml.rels': build_workbook_rels_xml(),
        'xl/styles.xml': styles_xml,
        'xl/worksheets/sheet1.xml': worksheet_xml,
    }

    with zipfile.ZipFile(output_path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)


def build_worksheet_xml(rows: list[list[str]]) -> str:
    row_count = max(1, len(rows))
    col_count = TOP_COUNT + 1
    dimension = f'A1:{excel_column_name(col_count)}{row_count}'
    columns_xml = (
        '<cols>'
        '<col min="1" max="1" width="52" customWidth="1"/>'
        '<col min="2" max="6" width="34" customWidth="1"/>'
        '</cols>'
    )
    sheet_data = ''.join(build_row_xml(row_index, row) for row_index, row in enumerate(rows, start=1))
    auto_filter = f'<autoFilter ref="{dimension}"/>' if row_count > 1 else ''
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<dimension ref="{dimension}"/>'
        '<sheetViews><sheetView workbookViewId="0">'
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        '<selection pane="bottomLeft"/>'
        '</sheetView></sheetViews>'
        f'{columns_xml}'
        f'<sheetData>{sheet_data}</sheetData>'
        f'{auto_filter}'
        '<pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" header="0.3" footer="0.3"/>'
        '</worksheet>'
    )


def build_row_xml(row_index: int, values: list[str]) -> str:
    style = 1 if row_index == 1 else 2
    height = '24' if row_index == 1 else '42'
    cells = ''.join(
        build_cell_xml(row_index, col_index, values[col_index - 1] if col_index <= len(values) else '', style)
        for col_index in range(1, TOP_COUNT + 2)
    )
    return f'<row r="{row_index}" spans="1:{TOP_COUNT + 1}" ht="{height}" customHeight="1">{cells}</row>'


def build_cell_xml(row_index: int, col_index: int, value: str, style: int) -> str:
    ref = f'{excel_column_name(col_index)}{row_index}'
    text = '' if value is None else str(value)
    if not text:
        return f'<c r="{ref}" s="{style}"/>'
    space = ' xml:space="preserve"' if text != text.strip() else ''
    return f'<c r="{ref}" s="{style}" t="inlineStr"><is><t{space}>{escape(text)}</t></is></c>'


def excel_column_name(index: int) -> str:
    name = ''
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def build_content_types_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '</Types>'
    )


def build_root_rels_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
        '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
        '</Relationships>'
    )


def build_workbook_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Top5" sheetId="1" r:id="rId1"/></sheets>'
        '</workbook>'
    )


def build_workbook_rels_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        '</Relationships>'
    )


def build_styles_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="2">'
        '<font><sz val="11"/><name val="Microsoft YaHei"/></font>'
        '<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Microsoft YaHei"/></font>'
        '</fonts>'
        '<fills count="3">'
        '<fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FF1F4E78"/><bgColor indexed="64"/></patternFill></fill>'
        '</fills>'
        '<borders count="2">'
        '<border><left/><right/><top/><bottom/><diagonal/></border>'
        '<border><left style="thin"><color rgb="FFD9E2F3"/></left><right style="thin"><color rgb="FFD9E2F3"/></right>'
        '<top style="thin"><color rgb="FFD9E2F3"/></top><bottom style="thin"><color rgb="FFD9E2F3"/></bottom><diagonal/></border>'
        '</borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="3">'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1">'
        '<alignment horizontal="center" vertical="center"/></xf>'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1">'
        '<alignment vertical="top" wrapText="1"/></xf>'
        '</cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        '</styleSheet>'
    )


def build_app_props_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
        'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
        '<Application>Python</Application>'
        '</Properties>'
    )


def build_core_props_xml(timestamp: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:dcmitype="http://purl.org/dc/dcmitype/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        '<dc:creator>batch_query_top5_to_excel.py</dc:creator>'
        '<cp:lastModifiedBy>batch_query_top5_to_excel.py</cp:lastModifiedBy>'
        f'<dcterms:created xsi:type="dcterms:W3CDTF">{timestamp}</dcterms:created>'
        f'<dcterms:modified xsi:type="dcterms:W3CDTF">{timestamp}</dcterms:modified>'
        '</cp:coreProperties>'
    )


def main() -> int:
    args = parse_args()
    output_path = Path(args.output) if args.output else default_output_path(args.input)
    use_fault_chain = not args.all_nodes

    try:
        queries = read_queries(args.input)
    except Exception as exc:
        print(f'读取输入失败：{exc}', file=sys.stderr)
        return 1
    if not queries:
        print('输入文件中没有可查询的内容。', file=sys.stderr)
        return 1

    rows: list[list[str]] | None = None
    api_url = normalize_api_url(args.api_url)
    if use_fault_chain and api_url:
        try:
            print(f'使用后端故障链接口：{api_url}', flush=True)
            rows = build_result_rows_from_api(queries, api_url, args.api_timeout, args.detail)
        except Exception as exc:
            print(f'后端 API 查询不可用，改用本地故障链查询：{exc}', flush=True)

    if rows is None:
        try:
            fault_app = load_query_backend(args.use_llm)
            graph = fetch_graph(fault_app)
        except Exception as exc:
            print(f'连接或读取知识库失败：{exc}', file=sys.stderr)
            return 2

        mode = ('故障链查询（大模型 -> BERT -> 本地规则）' if args.use_llm else '故障链查询（BERT -> 本地规则）') if use_fault_chain else '全知识库节点检索'
        print(f'已读取 {len(queries)} 条查询；知识库节点 {len(graph["nodes"])} 个，关系 {len(graph["edges"])} 条；模式：{mode}。', flush=True)
        rows = build_result_rows(queries, graph, fault_app, args.detail, use_fault_chain)

    try:
        write_xlsx(rows, output_path)
    except Exception as exc:
        print(f'写出 Excel 失败：{exc}', file=sys.stderr)
        return 3

    print(f'已生成：{output_path.resolve()}', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
