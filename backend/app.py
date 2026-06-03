from __future__ import annotations

import os
import json
import re
import shutil
import sys
import time
import traceback
import zipfile
from collections import defaultdict, deque
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Any
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest

from flask import Flask, g, has_request_context, jsonify, request
from flask_cors import CORS
from neo4j import GraphDatabase
from neo4j.exceptions import TransientError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.offline_config import configure_offline_environment, offline_enabled, url_allowed_in_offline
from backend.fknow_routes import register_fknow_routes

configure_offline_environment()

DEFAULT_LOCAL_LLM_BASE_URL = 'http://192.168.102.240:8866/v1'
DEFAULT_LOCAL_LLM_MODEL = 'Qwen3-Next-80B-A3B-Instruct'
DEFAULT_BERT_MODEL_NAME = 'bert-base-chinese'
ATTRIBUTE_MATERIALIZE_LOCK = Lock()


class FaultQueryBertError(RuntimeError):
    pass


RELATION_LABELS = {
    'HAS_FAILURE_MODE': '故障模式',
    'HAS_FUNCTION': '功能',
    'HAS': '有',
    'INCLUDE': '包含',
    'LEADS_TO': '导致',
    'LEVEL_CLASSIFICATION': '严酷度等级',
    'OCCURRENCE_STAGE': '发生阶段',
    'PROBABILITY': '发生概率',
    'SOLUTION': '设计措施',
    'YES_OR_NO': '是否单点',
}

FAULT_CHAIN_RELATION_TYPES = {
    'HAS_FAILURE_MODE',
    'HAS',
    'INCLUDE',
    'LEADS_TO',
    'LEVEL_CLASSIFICATION',
    'OCCURRENCE_STAGE',
    'PROBABILITY',
    'SOLUTION',
    'YES_OR_NO',
}

FAULT_CHAIN_RELATION_LABELS = {RELATION_LABELS[relation] for relation in FAULT_CHAIN_RELATION_TYPES}

ATTRIBUTE_RELATION_TYPES = {
    'LEVEL_CLASSIFICATION',
    'OCCURRENCE_STAGE',
    'PROBABILITY',
    'SOLUTION',
    'YES_OR_NO',
}

ATTRIBUTE_RELATION_LABELS = {RELATION_LABELS[relation] for relation in ATTRIBUTE_RELATION_TYPES}

RELATION_TYPE_ALIASES = {
    'HAS_FAILURE_MODE': ('HAS_FAILURE_MODE', '故障模式', '具有故障模式', '存在故障'),
    'HAS_FUNCTION': ('HAS_FUNCTION', '具有功能', '功能'),
    'HAS': ('HAS', '有'),
    'INCLUDE': ('INCLUDE', '包含'),
    'LEADS_TO': ('LEADS_TO', '导致'),
    'LEVEL_CLASSIFICATION': ('LEVEL_CLASSIFICATION', '等级分类', '严酷度等级'),
    'OCCURRENCE_STAGE': ('OCCURRENCE_STAGE', '发生阶段'),
    'PROBABILITY': ('PROBABILITY', '发生概率'),
    'SOLUTION': ('SOLUTION', '解决措施', '设计措施'),
    'YES_OR_NO': ('YES_OR_NO', '是否单点'),
}

RELATION_OPERATION_SPECS = {
    '发生阶段': {'canonical': 'OCCURRENCE_STAGE', 'label': '发生阶段', 'node_label': '发生阶段'},
    '是否单点': {'canonical': 'YES_OR_NO', 'label': '是否单点', 'node_label': '是否单点'},
    '严酷度等级': {'canonical': 'LEVEL_CLASSIFICATION', 'label': '严酷度等级', 'node_label': '严酷度等级'},
    '发生概率': {'canonical': 'PROBABILITY', 'label': '发生概率', 'node_label': '发生概率'},
    '设计措施': {'canonical': 'SOLUTION', 'label': '设计措施', 'node_label': '设计措施'},
}

ATTRIBUTE_PROPERTY_NAMES = tuple(RELATION_OPERATION_SPECS.keys())

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

LABEL_META = {
    'Component': {'level': '组件', 'node_type': 'component', 'priority': 'P2', 'status': '结构对象'},
    'Machine': {'level': '单机', 'node_type': 'component', 'priority': 'P2', 'status': '单机对象'},
    'System': {'level': '系统', 'node_type': 'component', 'priority': 'P2', 'status': '系统对象'},
    'Function': {'level': '功能', 'node_type': 'component', 'priority': 'P3', 'status': '功能定义'},
    'Attribute': {'level': '属性', 'node_type': 'condition', 'priority': 'P3', 'status': '属性定义'},
    'ComponentFailureMode': {'level': '组件级故障模式', 'node_type': 'root-cause', 'priority': 'P1', 'status': '待排查'},
    'UnitFailureMode': {'level': '单机级故障模式', 'node_type': 'fault', 'priority': 'P1', 'status': '重点关注'},
    'SystemFailureMode': {'level': '系统级故障模式', 'node_type': 'impact', 'priority': 'P1', 'status': '系统影响'},
    'OverallFailureMode': {'level': '总体级故障模式', 'node_type': 'impact', 'priority': 'P1', 'status': '总体影响'},
    'OccurrenceStage': {'level': '发生阶段', 'node_type': 'condition', 'priority': 'P3', 'status': '工况条件'},
    'ProbabilityLevel': {'level': '发生概率', 'node_type': 'condition', 'priority': 'P3', 'status': '风险评估'},
    'SeverityLevel': {'level': '严酷度等级', 'node_type': 'condition', 'priority': 'P2', 'status': '风险评估'},
    'SinglePoint': {'level': '是否单点', 'node_type': 'condition', 'priority': 'P2', 'status': '判定条件'},
    'DesignMeasure': {'level': '设计措施', 'node_type': 'condition', 'priority': 'P2', 'status': '建议措施'},
    '组件': {'level': '组件', 'node_type': 'component', 'priority': 'P2', 'status': '结构对象'},
    '零部组件': {'level': '零部组件', 'node_type': 'component', 'priority': 'P2', 'status': '结构对象'},
    '单机': {'level': '单机', 'node_type': 'component', 'priority': 'P2', 'status': '单机对象'},
    '系统': {'level': '系统', 'node_type': 'component', 'priority': 'P2', 'status': '系统对象'},
    '总体': {'level': '总体', 'node_type': 'component', 'priority': 'P2', 'status': '总体对象'},
    '功能': {'level': '功能', 'node_type': 'component', 'priority': 'P3', 'status': '功能定义'},
    '单机功能': {'level': '单机功能', 'node_type': 'component', 'priority': 'P3', 'status': '功能定义'},
    '系统功能': {'level': '系统功能', 'node_type': 'component', 'priority': 'P3', 'status': '功能定义'},
    '总体功能': {'level': '总体功能', 'node_type': 'component', 'priority': 'P3', 'status': '功能定义'},
    '零部组件功能': {'level': '零部组件功能', 'node_type': 'component', 'priority': 'P3', 'status': '功能定义'},
    '属性': {'level': '属性', 'node_type': 'condition', 'priority': 'P3', 'status': '属性定义'},
    '属性值': {'level': '属性值', 'node_type': 'condition', 'priority': 'P3', 'status': '属性值'},
    '发生阶段': {'level': '发生阶段', 'node_type': 'condition', 'priority': 'P3', 'status': '工况条件'},
    '发生概率': {'level': '发生概率', 'node_type': 'condition', 'priority': 'P3', 'status': '风险评估'},
    '严酷度等级': {'level': '严酷度等级', 'node_type': 'condition', 'priority': 'P2', 'status': '风险评估'},
    '是否单点': {'level': '是否单点', 'node_type': 'condition', 'priority': 'P2', 'status': '判定条件'},
    '设计措施': {'level': '设计措施', 'node_type': 'condition', 'priority': 'P2', 'status': '建议措施'},
    '组件级故障模式': {'level': '组件级故障模式', 'node_type': 'root-cause', 'priority': 'P1', 'status': '待排查'},
    '单机级故障模式': {'level': '单机级故障模式', 'node_type': 'fault', 'priority': 'P1', 'status': '重点关注'},
    '系统级故障模式': {'level': '系统级故障模式', 'node_type': 'impact', 'priority': 'P1', 'status': '系统影响'},
    '总体级故障模式': {'level': '总体级故障模式', 'node_type': 'impact', 'priority': 'P1', 'status': '总体影响'},
    '组件级故障现象': {'level': '组件级故障现象', 'node_type': 'impact', 'priority': 'P2', 'status': '故障现象'},
    '单机级故障现象': {'level': '单机级故障现象', 'node_type': 'impact', 'priority': 'P2', 'status': '故障现象'},
    '系统级故障现象': {'level': '系统级故障现象', 'node_type': 'impact', 'priority': 'P2', 'status': '故障现象'},
    '总体级故障现象': {'level': '总体级故障现象', 'node_type': 'impact', 'priority': 'P2', 'status': '故障现象'},
    '故障现象': {'level': '故障现象', 'node_type': 'impact', 'priority': 'P2', 'status': '故障现象'},
}

LABEL_COLUMNS = {
    'Component': 10, '组件': 10, '零部组件': 10, 'Machine': 10, '单机': 10,
    'System': 22, '系统': 22, 'Function': 22, '功能': 22, '单机功能': 22, '系统功能': 22, '总体功能': 22, '零部组件功能': 22,
    'Attribute': 22, '属性': 22, '属性值': 22,
    'ComponentFailureMode': 38, '组件级故障模式': 38,
    'UnitFailureMode': 52, '单机级故障模式': 52,
    'SystemFailureMode': 68, '系统级故障模式': 68,
    'OverallFailureMode': 84, '总体级故障模式': 84,
    'OccurrenceStage': 84, '发生阶段': 84, 'ProbabilityLevel': 84, '发生概率': 84,
    'SeverityLevel': 96, '严酷度等级': 96, 'SinglePoint': 96, '是否单点': 96, 'DesignMeasure': 96, '设计措施': 96,
    '故障现象': 84, '组件级故障现象': 84, '单机级故障现象': 84, '系统级故障现象': 84, '总体级故障现象': 84,
}

QUERY_FIELDS = {'name': 'name', 'owner': 'owner', 'raw_text': 'rawText', 'key': 'key'}

GROUP_ORDER = {'总体': 0, '系统': 1, '单体': 2, '组件': 3, '功能': 4, '其他': 5}

LEVEL_ORDER = {
    '总体级故障模式': 0,
    '系统': 1,
    '系统级故障模式': 2,
    '单机': 3,
    '单机级故障模式': 4,
    '组件': 5,
    '组件级故障模式': 6,
    '功能': 7,
    '属性': 8,
    '属性值': 8,
    '发生阶段': 9,
    '发生概率': 10,
    '严酷度等级': 11,
    '是否单点': 12,
    '设计措施': 13,
    '故障现象': 14,
    '组件级故障现象': 14,
    '单机级故障现象': 14,
    '系统级故障现象': 14,
    '总体级故障现象': 14,
}

LEVEL_GROUP = {
    '总体级故障模式': '总体',
    '系统': '系统',
    '系统级故障模式': '系统',
    '单机': '单体',
    '单机级故障模式': '单体',
    '组件': '组件',
    '组件级故障模式': '组件',
    '功能': '功能',
    '属性': '其他',
    '属性值': '其他',
    '发生阶段': '其他',
    '发生概率': '其他',
    '严酷度等级': '其他',
    '是否单点': '其他',
    '设计措施': '其他',
    '故障现象': '其他',
    '组件级故障现象': '组件',
    '单机级故障现象': '单体',
    '系统级故障现象': '系统',
    '总体级故障现象': '总体',
}


STAGE_DEFINITIONS = [
    {
        'key': 'component',
        'title': '组件级',
        'levels': {'组件'},
        'preference': {'组件': 0},
    },
    {
        'key': 'unit',
        'title': '单体级',
        'levels': {'单机', '单机级故障模式'},
        'preference': {'单机级故障模式': 0, '单机': 1},
    },
    {
        'key': 'system',
        'title': '系统级',
        'levels': {'系统', '系统级故障模式'},
        'preference': {'系统级故障模式': 0, '系统': 1},
    },
    {
        'key': 'overall',
        'title': '总体级',
        'levels': {'总体级故障模式'},
        'preference': {'总体级故障模式': 0},
    },
]

SUPPORT_LEVELS = {
    '属性',
    '属性值',
    '发生阶段',
    '发生概率',
    '严酷度等级',
    '是否单点',
    '设计措施',
    '故障现象',
    '组件级故障现象',
    '单机级故障现象',
    '系统级故障现象',
    '总体级故障现象',
}
FAULT_CHAIN_SUPPORT_LEVELS = SUPPORT_LEVELS

def create_app() -> Flask:
    app = Flask(__name__)
    app.json.sort_keys = False
    CORS(app)

    @app.before_request
    def log_api_request() -> None:
        if request.path.startswith('/api/'):
            print(f"[API] {request.method} {request.path} from={request.remote_addr}", flush=True)

    @app.after_request
    def prevent_api_cache(response: Any) -> Any:
        if request.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/api/health')
    def health() -> Any:
        with get_driver().session(database=get_database()) as session:
            node_count = session.run('MATCH (n) RETURN count(n) AS count').single()['count']
            edge_count = session.run('MATCH ()-[r]->() RETURN count(r) AS count').single()['count']
        return jsonify({
            'status': 'ok',
            'uri': get_neo4j_uri(),
            'database': get_database() or 'neo4j',
            'nodeCount': node_count,
            'edgeCount': edge_count,
            'llmEnabled': is_llm_query_enabled(),
            'llmBaseUrl': get_llm_base_url(),
            'llmModel': get_llm_model(),
            'bert': bert_diagnostics(load_model=False),
        })

    @app.get('/api/bert/status')
    def bert_status() -> Any:
        load_model = str(request.args.get('load', '')).strip().lower() in {'1', 'true', 'yes'}
        diagnostics = bert_diagnostics(load_model=load_model)
        status_code = 200 if diagnostics.get('ok') else 500
        return jsonify(build_api_envelope(bool(diagnostics.get('ok')), status_code, diagnostics.get('message', ''), diagnostics)), status_code

    @app.get('/api/graph')
    def graph() -> Any:
        return jsonify({'message': 'ok', 'graph': build_graph_payload()})

    @app.post('/api/graph/nodes')
    def create_graph_node() -> Any:
        payload = request.get_json(silent=True) or {}
        try:
            result = create_business_node(payload)
        except ValueError as exc:
            return jsonify(build_api_envelope(False, 400, str(exc), {'graph': build_graph_payload()})), 400
        return jsonify(build_api_envelope(True, 200, '节点已新增', result))

    @app.patch('/api/graph/nodes/<path:node_id>')
    def update_graph_node(node_id: str) -> Any:
        payload = request.get_json(silent=True) or {}
        try:
            result = update_business_node(node_id, payload)
        except ValueError as exc:
            return jsonify(build_api_envelope(False, 400, str(exc), {'graph': build_graph_payload()})), 400
        return jsonify(build_api_envelope(True, 200, '节点已修改', result))

    @app.delete('/api/graph/nodes/<path:node_id>')
    def delete_graph_node(node_id: str) -> Any:
        try:
            result = delete_business_node(node_id)
        except ValueError as exc:
            return jsonify(build_api_envelope(False, 400, str(exc), {'graph': build_graph_payload()})), 400
        return jsonify(build_api_envelope(True, 200, '节点已删除', result))

    @app.post('/api/query')
    def query_fault() -> Any:
        payload = request.get_json(silent=True) or {}
        text = str(payload.get('text', '')).strip()
        print(f"[FaultQuery] received text={text!r}", flush=True)
        if not text:
            return jsonify(build_api_envelope(False, 400, '请先输入故障现象。', empty_query_result())), 400

        graph = fetch_graph_from_neo4j()
        try:
            ranked = rank_fault_chain_query_nodes(text, graph)
        except FaultQueryBertError as exc:
            log_query_backend_strategy(text)
            diagnostics = bert_diagnostics(load_model=False)
            print(f"[FaultQuery][BERT_ERROR] {exc}", flush=True)
            print(f"[FaultQuery][BERT_DIAGNOSTICS] {json.dumps(diagnostics, ensure_ascii=False)}", flush=True)
            traceback.print_exception(type(exc), exc, exc.__traceback__)
            message = str(exc)
            return jsonify(build_api_envelope(False, 500, message, {**empty_query_result(), 'summary': message, 'bertDiagnostics': diagnostics})), 500
        if not ranked:
            log_query_backend_strategy(text)
            return jsonify(build_api_envelope(False, 404, 'BERT 未匹配到故障节点', {**empty_query_result(), 'summary': 'BERT 已完成向量匹配，但未在 Neo4j 图数据库中匹配到相关故障节点。'})), 404

        best = ranked[0]
        log_query_backend_strategy(text, best)
        top_matches = build_top_matches(text, ranked)
        return jsonify(build_api_envelope(True, 200, '查询成功', build_query_result_payload(text, best, graph, top_matches)))

    @app.post('/api/query/node')
    def query_fault_node() -> Any:
        payload = request.get_json(silent=True) or {}
        text = str(payload.get('text', '')).strip()
        node_id = str(payload.get('nodeId') or payload.get('id') or '').strip()
        if not node_id:
            return jsonify(build_api_envelope(False, 400, '请选择候选节点。', empty_query_result())), 400

        graph = fetch_graph_from_neo4j()
        node = next((item for item in graph['nodes'] if item['id'] == node_id), None)
        if not node:
            return jsonify(build_api_envelope(False, 404, '当前图谱中未找到该候选节点，请重新查询。', empty_query_result())), 404

        top_matches = normalize_top_matches_payload(payload.get('topMatches'))
        if not top_matches:
            top_matches = build_top_matches(text, [{**node, 'score': 100}])
        return jsonify(build_api_envelope(True, 200, '候选结果已切换', build_query_result_payload(text, node, graph, top_matches)))

    @app.get('/api/fmea/current-fault-modes')
    def fmea_current_fault_modes() -> Any:
        return jsonify(build_api_envelope(True, 200, '操作成功', list_current_fault_modes()))

    @app.route('/api/fmea/inference-results', methods=['GET', 'POST'])
    def fmea_inference_results() -> Any:
        return jsonify(build_api_envelope(True, 200, '操作成功', infer_fmea_results(read_fault_mode_inputs())))

    @app.get('/api/fta/current-fault-modes')
    def fta_current_fault_modes() -> Any:
        return jsonify(build_api_envelope(True, 200, '操作成功', list_current_fault_modes()))

    @app.route('/api/fta/inference-results', methods=['GET', 'POST'])
    def fta_inference_results() -> Any:
        return jsonify(build_api_envelope(True, 200, '操作成功', infer_fta_results(read_fault_mode_inputs())))

    register_fknow_routes(app)

    return app


def empty_query_result() -> dict[str, Any]:
    return {
        'nodeId': '', 'activeTab': 'overview', 'title': '等待查询',
        'summary': '输入故障现象后，系统会从 Neo4j 图数据库中查询关联节点与关系。',
        'checks': [], 'matchedKeywords': [], 'matchedNode': None, 'matchedLabel': None, 'pathNodeIds': [],
        'reasoningSteps': [], 'reasoningEvidence': [], 'topMatches': [],
    }


def build_query_result_payload(
    query_text: str,
    node: dict[str, Any],
    graph: dict[str, list[dict[str, Any]]],
    top_matches: list[dict[str, Any]],
) -> dict[str, Any]:
    related = collect_related(node['id'], graph)
    reasoning = build_full_chain_reasoning(query_text, node, graph, related)
    active_tab = 'layer' if node['type'] in {'impact', 'condition'} else 'path'
    return {
        'nodeId': node['id'],
        'activeTab': active_tab,
        'title': f"命中图谱节点：{node['name']}",
        'summary': reasoning['summary'],
        'checks': reasoning['checks'],
        'matchedKeywords': matched_terms(query_text, node),
        'matchedNode': node['name'],
        'matchedLabel': node['label'],
        'topMatches': top_matches,
        'pathNodeIds': reasoning['pathNodeIds'],
        'reasoningSteps': reasoning['steps'],
        'reasoningEvidence': reasoning['evidence'],
    }


def normalize_top_matches_payload(raw_matches: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_matches, list):
        return []

    matches: list[dict[str, Any]] = []
    for index, raw_match in enumerate(raw_matches[:5], start=1):
        if not isinstance(raw_match, dict):
            continue
        node_id = str(raw_match.get('id') or '').strip()
        name = str(raw_match.get('name') or '').strip()
        if not node_id or not name:
            continue
        matches.append({
            'rank': int(raw_match.get('rank') or index),
            'id': node_id,
            'name': name,
            'level': str(raw_match.get('level') or ''),
            'owner': str(raw_match.get('owner') or ''),
            'score': max(1, min(100, float(raw_match.get('score') or 0))),
            'confidence': max(1, min(100, float(raw_match.get('confidence') or 0))),
            'matchedKeywords': raw_match.get('matchedKeywords') if isinstance(raw_match.get('matchedKeywords'), list) else [],
        })
    return matches


def proxy_plm_reasoning_request(url_env_key: str) -> Any:
    upstream_url = os.environ.get(url_env_key, '').strip()
    if not upstream_url:
        return jsonify(build_api_envelope(
            success=False,
            code=500,
            message=f'未配置上游接口地址：{url_env_key}',
            result=[],
        )), 500

    try:
        upstream_data, status_code = call_upstream_json(upstream_url)
    except RuntimeError as exc:
        return jsonify(build_api_envelope(
            success=False,
            code=403,
            message=str(exc),
            result=[],
        )), 403
    except urlerror.HTTPError as exc:
        error_body = read_error_body(exc)
        return jsonify(build_api_envelope(
            success=False,
            code=exc.code,
            message=error_body.get('message') or f'上游接口返回错误：{exc.code}',
            result=error_body.get('result', []),
            token=error_body.get('token'),
            notify_icon=error_body.get('notifyIcon'),
        )), exc.code
    except urlerror.URLError as exc:
        return jsonify(build_api_envelope(
            success=False,
            code=502,
            message=f'无法连接上游接口：{exc.reason}',
            result=[],
        )), 502
    except TimeoutError:
        return jsonify(build_api_envelope(False, 504, '上游接口请求超时', [])), 504
    except Exception as exc:
        return jsonify(build_api_envelope(False, 500, f'调用上游接口失败：{exc}', [])), 500

    envelope = normalize_api_envelope(upstream_data, status_code)
    return jsonify(envelope), status_code if status_code >= 400 else 200


def call_upstream_json(upstream_url: str) -> tuple[Any, int]:
    if not url_allowed_in_offline(upstream_url):
        raise RuntimeError(f'离线模式禁止访问公网接口：{upstream_url}')

    method = request.method
    url = append_query_string(upstream_url, request.query_string.decode('utf-8'))
    headers = build_upstream_headers()
    body: bytes | None = None

    if method == 'POST':
        payload = request.get_json(silent=True)
        body = json.dumps(payload if payload is not None else {}, ensure_ascii=False).encode('utf-8')
        headers['Content-Type'] = 'application/json'

    timeout = float(os.environ.get('PLM_REASONING_TIMEOUT', '15'))
    upstream_request = urlrequest.Request(url, data=body, headers=headers, method=method)
    with urlrequest.urlopen(upstream_request, timeout=timeout) as response:
        response_body = response.read().decode('utf-8')
        data = json.loads(response_body) if response_body.strip() else {}
        return data, response.status


def append_query_string(url: str, query_string: str) -> str:
    if not query_string:
        return url

    separator = '&' if urlparse.urlsplit(url).query else '?'
    return f'{url}{separator}{query_string}'


def build_upstream_headers() -> dict[str, str]:
    headers = {'Accept': 'application/json'}
    auth_header = request.headers.get('Authorization', '').strip()
    if auth_header:
        headers['Authorization'] = auth_header

    token = os.environ.get('PLM_REASONING_TOKEN', '').strip()
    if token and 'Authorization' not in headers:
        headers['Authorization'] = f'Bearer {token}'

    return headers


def read_error_body(exc: urlerror.HTTPError) -> dict[str, Any]:
    try:
        raw_body = exc.read().decode('utf-8')
        data = json.loads(raw_body) if raw_body.strip() else {}
        return data if isinstance(data, dict) else {'result': data}
    except Exception:
        return {}


def normalize_api_envelope(data: Any, fallback_code: int = 200) -> dict[str, Any]:
    if isinstance(data, dict) and {'success', 'code', 'message', 'result'} <= data.keys():
        return {
            'success': bool(data.get('success')),
            'code': data.get('code') or fallback_code,
            'message': data.get('message') or '',
            'result': data.get('result') if data.get('result') is not None else [],
            'token': data.get('token'),
            'notifyIcon': data.get('notifyIcon'),
        }

    return build_api_envelope(True, fallback_code, '操作成功', data if data is not None else [])


def build_api_envelope(
    success: bool,
    code: int,
    message: str,
    result: Any,
    token: Any = None,
    notify_icon: Any = None,
) -> dict[str, Any]:
    return {
        'success': success,
        'code': code,
        'message': message,
        'result': result,
        'token': token,
        'notifyIcon': notify_icon,
    }


def read_fault_mode_inputs() -> list[dict[str, Any]]:
    if request.method == 'GET':
        return read_fault_mode_inputs_from_query()

    payload = request.get_json(silent=True)
    if isinstance(payload, list):
        return normalize_fault_mode_items(payload)
    if isinstance(payload, dict):
        for key in ('result', 'faultModes', 'items', 'data'):
            value = payload.get(key)
            if isinstance(value, list):
                return normalize_fault_mode_items(value)
        return [payload]
    return []


def read_fault_mode_inputs_from_query() -> list[dict[str, Any]]:
    for key in ('items', 'data', 'faultModes', 'result'):
        parsed = parse_query_json_list(key)
        if parsed:
            return parsed

    fields = (
        'id',
        'productName',
        'function',
        'faultMode',
        'faultReason',
        'name',
        'text',
        'countermeasures',
        'taskPhase',
        'singlePoint',
        'severityCategory',
        'occurrenceRating',
    )
    values_by_field = {field: request.args.getlist(field) for field in fields}
    item_count = max((len(values) for values in values_by_field.values()), default=0)
    if item_count <= 1:
        text = request.args.get('text') or request.args.get('faultMode') or request.args.get('name') or ''
        return [{'id': request.args.get('id') or '', 'faultMode': text}]

    items: list[dict[str, Any]] = []
    for index in range(item_count):
        item = {
            field: values[index].strip()
            for field, values in values_by_field.items()
            if index < len(values) and values[index].strip()
        }
        if not item.get('faultMode'):
            item['faultMode'] = item.get('text') or item.get('name') or ''
        items.append(item)
    return items


def parse_query_json_list(key: str) -> list[dict[str, Any]]:
    raw_value = request.args.get(key)
    if not raw_value:
        return []
    try:
        value = json.loads(raw_value)
    except json.JSONDecodeError:
        return normalize_fault_mode_items(request.args.getlist(key))
    if isinstance(value, list):
        return normalize_fault_mode_items(value)
    return []


def normalize_fault_mode_items(values: list[Any]) -> list[dict[str, Any]]:
    return [item if isinstance(item, dict) else {'faultMode': str(item)} for item in values]


def list_current_fault_modes() -> list[dict[str, Any]]:
    graph = fetch_graph_from_neo4j()
    fault_nodes = [
        node for node in graph['nodes']
        if node.get('type') in {'root-cause', 'fault', 'impact'} or '故障模式' in str(node.get('level', ''))
    ]
    return [build_plm_fault_mode_view(node) for node in sorted(fault_nodes, key=lambda item: (item.get('level', ''), item.get('name', '')))]


def build_plm_fault_mode_view(node: dict[str, Any]) -> dict[str, Any]:
    return {
        'id': node.get('id', ''),
        'containerPath': None,
        'createBy': None,
        'createFullName': None,
        'createName': None,
        'createOrgId': None,
        'createTime': None,
        'createDeptId': None,
        'deleteFlag': None,
        'updateBy': None,
        'updateName': None,
        'updateFullName': None,
        'updateTime': None,
        'updateOrgId': None,
        'updateDeptId': None,
        'partOid': node.get('id', ''),
        'productName': node.get('owner') or None,
        'productCode': None,
        'function': None,
        'faultMode': node.get('name') or None,
        'faultReason': None,
        'countermeasures': None,
        'taskPhase': None,
        'singlePoint': None,
        'severityCategory': None,
        'occurrenceRating': None,
        'projectId': None,
    }


def infer_fmea_results(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [build_fmea_result(item, run_local_reasoning(item)) for item in items]


def infer_fta_results(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [build_fta_tree(item, run_local_reasoning(item)) for item in items]


def run_local_reasoning(item: dict[str, Any]) -> dict[str, Any]:
    text = build_inference_text(item)
    if not text:
        return empty_query_result()

    graph = fetch_graph_from_neo4j()
    try:
        ranked = rank_fault_chain_query_nodes(text, graph)
    except FaultQueryBertError as exc:
        return {**empty_query_result(), 'summary': str(exc)}
    if not ranked:
        return {**empty_query_result(), 'summary': '未在知识图谱中匹配到可推理的故障模式。'}

    best = ranked[0]
    related = collect_related(best['id'], graph)
    reasoning = build_full_chain_reasoning(text, best, graph, related)
    return {
        'nodeId': best['id'],
        'title': f"命中图谱节点：{best['name']}",
        'summary': reasoning['summary'],
        'checks': reasoning['checks'],
        'matchedNode': best['name'],
        'matchedLabel': best['label'],
        'reasoningSteps': reasoning['steps'],
    }


def build_inference_text(item: dict[str, Any]) -> str:
    fields = ('productName', 'function', 'faultMode', 'faultReason', 'name', 'text')
    return ' '.join(str(item.get(field, '')).strip() for field in fields if str(item.get(field, '')).strip())


def build_fmea_result(item: dict[str, Any], reasoning: dict[str, Any]) -> dict[str, Any]:
    checks = reasoning.get('checks', [])
    return {
        'id': item.get('id') or reasoning.get('nodeId') or '',
        'productName': item.get('productName') or infer_stage_node_name(reasoning, '系统级') or infer_stage_node_name(reasoning, '单体级'),
        'function': item.get('function'),
        'faultMode': reasoning.get('matchedNode') or item.get('faultMode'),
        'faultReason': item.get('faultReason') or reasoning.get('summary'),
        'countermeasures': item.get('countermeasures') or extract_check_value(checks, '设计措施'),
        'taskPhase': item.get('taskPhase') or extract_check_value(checks, '发生阶段'),
        'singlePoint': item.get('singlePoint') or single_point_code(extract_check_value(checks, '是否单点')),
        'severityCategory': item.get('severityCategory') or extract_check_value(checks, '严酷度'),
        'occurrenceRating': item.get('occurrenceRating') or extract_check_value(checks, '发生概率'),
    }


def build_fta_tree(item: dict[str, Any], reasoning: dict[str, Any]) -> dict[str, Any]:
    steps = reasoning.get('reasoningSteps') or []
    ordered = list(reversed(steps))
    if not ordered:
        source_id = item.get('id') or reasoning.get('nodeId') or ''
        return build_fta_node('1', '0', item.get('faultMode') or reasoning.get('matchedNode') or '', source_id, None, True)

    root_source_id = ordered[0].get('nodeId') or item.get('id')
    root = build_fta_node(
        '1',
        '0',
        ordered[0].get('nodeName', ''),
        root_source_id,
        None,
        ordered[0].get('nodeId') == reasoning.get('nodeId'),
    )
    cursor = root
    for index, step in enumerate(ordered[1:], start=2):
        child = build_fta_node(
            str(index),
            cursor['id'],
            step.get('nodeName', ''),
            step.get('nodeId') or item.get('id'),
            cursor.get('fmeaId'),
            step.get('nodeId') == reasoning.get('nodeId'),
        )
        cursor['children'] = [child]
        cursor = child
    return root


def build_fta_node(node_id: str, parent_id: str | int, name: str, fmea_id: Any, fmea_parent_id: Any, selected: bool) -> dict[str, Any]:
    return {
        'Rect': {},
        'Results': {},
        'children': None,
        'count': '1',
        'faultMode': None,
        'fmeaId': fmea_id,
        'fmeaParentId': fmea_parent_id,
        'id': node_id,
        'lamda': None,
        'name': name,
        'parentId': parent_id,
        'rmaSTSLibraryVos': None,
        'selected': selected,
        'type': 'Or',
    }


def infer_stage_node_name(reasoning: dict[str, Any], stage: str) -> str | None:
    for step in reasoning.get('reasoningSteps', []):
        if stage in str(step.get('stage', '')):
            return step.get('nodeName')
    return None


def extract_check_value(checks: list[str], label: str) -> str | None:
    for check in checks:
        if label not in check:
            continue
        if '：' in check:
            return check.rsplit('：', 1)[-1]
        if ':' in check:
            return check.rsplit(':', 1)[-1]
    return None


def single_point_code(value: str | None) -> str | None:
    if value == '是':
        return 'A'
    if value == '否':
        return 'B'
    return value


@lru_cache(maxsize=1)
def get_driver():
    return GraphDatabase.driver(get_neo4j_uri(), auth=(get_neo4j_username(), get_neo4j_password()))


def get_neo4j_uri() -> str:
    return os.environ.get('NEO4J_URI', 'bolt://127.0.0.1:7687')


def get_neo4j_username() -> str:
    return os.environ.get('NEO4J_USERNAME', 'neo4j')


def get_neo4j_password() -> str:
    return os.environ.get('NEO4J_PASSWORD', '').strip() or 'jkok123999'


def get_database() -> str | None:
    database = os.environ.get('NEO4J_DATABASE', '').strip()
    return database or None


def quote_cypher_identifier(identifier: str) -> str:
    clean = str(identifier or '').strip()
    if not clean:
        raise ValueError('Neo4j 标签或关系类型不能为空。')
    return f'`{clean.replace("`", "``")}`'


def normalize_relation_type(raw_relation: str) -> str:
    raw = str(raw_relation or '').strip()
    if not raw:
        return ''
    for canonical, aliases in RELATION_TYPE_ALIASES.items():
        if raw == canonical or any(alias and alias in raw for alias in aliases):
            return canonical
    return raw


def ensure_fault_attribute_nodes_from_properties() -> None:
    """Materialize legacy fault properties into attribute nodes without losing old data."""
    with ATTRIBUTE_MATERIALIZE_LOCK:
        for attempt in range(3):
            try:
                ensure_fault_attribute_nodes_from_properties_once()
                return
            except TransientError as exc:
                is_deadlock = getattr(exc, 'code', '') == 'Neo.TransientError.Transaction.DeadlockDetected' or 'DeadlockDetected' in str(exc)
                if not is_deadlock or attempt == 2:
                    raise
                time.sleep(0.15 * (attempt + 1))


def ensure_fault_attribute_nodes_from_properties_once() -> None:
    with get_driver().session(database=get_database()) as session:
        records = session.run(
            '''
            MATCH (fault)
            WHERE any(label IN labels(fault) WHERE label IN ['单机级故障模式', 'UnitFailureMode'])
            RETURN elementId(fault) AS id, properties(fault) AS props
            '''
        ).data()

        for record in records:
            fault_id = record['id']
            props = record.get('props') or {}
            fault_identity = str(props.get('id') or fault_id).strip()
            for spec in RELATION_OPERATION_SPECS.values():
                values = normalize_property_values(props.get(spec['label']))
                if not values:
                    continue
                node_label = quote_cypher_identifier(spec['node_label'])
                relation_type = quote_cypher_identifier(spec['label'])
                combined_name = ' / '.join(values)
                combined_key = f'{spec["node_label"]}:{fault_identity}:{spec["label"]}'
                session.run(
                    f'''
                    MATCH (fault)
                    WHERE elementId(fault) = $faultId
                    OPTIONAL MATCH (fault)-[oldRel:{relation_type}]->(oldNode)
                    DELETE oldRel
                    WITH fault, collect(oldNode) AS oldNodes
                    MERGE (attribute:{node_label} {{key: $combinedKey}})
                      ON CREATE SET attribute.source_type = coalesce(fault.source_type, 'legacy_property'),
                                    attribute.generated_from = 'fault_property'
                    SET attribute.name = $combinedName,
                        attribute.value_list = $values,
                        attribute.updated_at = datetime()
                    MERGE (fault)-[rel:{relation_type}]->(attribute)
                      ON CREATE SET rel.generated_from = 'fault_property'
                    WITH oldNodes
                    UNWIND oldNodes AS oldNode
                    WITH oldNode
                    WHERE oldNode IS NOT NULL
                      AND oldNode.generated_from = 'fault_property'
                      AND NOT EXISTS {{ MATCH (oldNode)--() }}
                    DETACH DELETE oldNode
                    ''',
                    faultId=fault_id,
                    combinedKey=combined_key,
                    combinedName=combined_name,
                    values=values,
                ).consume()


def fetch_graph_from_neo4j() -> dict[str, list[dict[str, Any]]]:
    ensure_fault_attribute_nodes_from_properties()
    with get_driver().session(database=get_database()) as session:
        node_records = session.run('MATCH (n) RETURN elementId(n) AS id, labels(n)[0] AS label, properties(n) AS props ORDER BY label, coalesce(n.owner, ""), coalesce(n.name, "")').data()
        edge_records = session.run('MATCH (a)-[r]->(b) RETURN elementId(a) AS source, type(r) AS relation, elementId(b) AS target ORDER BY relation').data()
    nodes = []
    for record in node_records:
        if is_ontology_placeholder_record(record):
            continue
        nodes.append(build_node_view(record))
    visible_node_ids = {node['id'] for node in nodes}
    edges = [
        build_edge_view(record)
        for record in edge_records
        if record.get('source') in visible_node_ids and record.get('target') in visible_node_ids
    ]
    return {'nodes': nodes, 'edges': edges}


def is_ontology_placeholder_record(record: dict[str, Any]) -> bool:
    label = str(record.get('label') or '').strip()
    props = record.get('props') or {}
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


def build_graph_payload() -> dict[str, Any]:
    graph = fetch_graph_from_neo4j()
    return {
        'nodes': graph['nodes'],
        'edges': graph['edges'],
        'hierarchyTree': build_hierarchy_tree(graph['nodes']),
        'ontologyTree': build_ontology_tree(graph['nodes'], graph['edges']),
        'defaultNodeId': graph['nodes'][0]['id'] if graph['nodes'] else '',
        'stats': {'nodeCount': len(graph['nodes']), 'edgeCount': len(graph['edges'])},
        'version': current_graph_version_summary(),
    }


def current_graph_version_summary() -> dict[str, Any] | None:
    try:
        from backend.kg_pipeline_service import list_kg_versions

        versions = list_kg_versions(1).get('versions', [])
        return versions[0] if versions else None
    except Exception as exc:
        print(f"[KGVersion] current version unavailable: {exc}", flush=True)
        return None


def build_node_view(record: dict[str, Any]) -> dict[str, Any]:
    label = record['label']
    props = record['props'] or {}
    meta = LABEL_META.get(label, {'level': label, 'node_type': 'condition', 'priority': 'P3', 'status': label})
    name = props.get('name') or props.get('owner') or label
    hierarchy_path = [part for part in (meta['level'], props.get('owner'), name) if part]
    description = props.get('raw_text') or props.get('key') or f'{meta["level"]}节点：{name}'
    tags = [meta['level'], *([props['owner']] if props.get('owner') else [])]
    x, y = layout_position(label, name)
    return {
        'id': record['id'], 'name': name, 'shortName': shorten(name), 'x': x, 'y': y,
        'type': meta['node_type'], 'level': meta['level'], 'status': meta['status'],
        'description': description, 'tags': tags, 'hierarchyPath': hierarchy_path, 'priority': meta['priority'],
        'label': label, 'owner': props.get('owner', ''), 'rawText': props.get('raw_text', ''), 'key': props.get('key', ''),
    }


def build_edge_view(record: dict[str, Any]) -> dict[str, Any]:
    raw_relation = record['relation']
    relation = normalize_relation_type(raw_relation)
    return {
        'from': record['source'], 'to': record['target'],
        'label': RELATION_LABELS.get(relation, relation),
        'strength': 'critical' if relation in {'LEADS_TO', 'HAS_FAILURE_MODE'} else 'normal',
        'relationType': relation,
        'rawRelationType': raw_relation,
    }


def create_business_node(payload: dict[str, Any]) -> dict[str, Any]:
    node_kind = str(payload.get('type') or payload.get('nodeType') or '').strip()
    name = str(payload.get('name') or '').strip()
    parent_id = str(payload.get('parentId') or '').strip()
    relation_label = str(payload.get('relationType') or payload.get('relation') or '').strip()

    if node_kind not in {'属性值', '故障现象'}:
        raise ValueError('只能新增“属性值”或“故障现象”类型节点。')
    if not name:
        raise ValueError('节点名称不能为空。')
    if not parent_id:
        raise ValueError('新增节点必须选择所属节点，不能创建孤立节点。')

    with get_driver().session(database=get_database()) as session:
        parent_record = session.run(
            'MATCH (parent) WHERE elementId(parent) = $parentId RETURN elementId(parent) AS id, labels(parent)[0] AS label, properties(parent) AS props',
            parentId=parent_id,
        ).single()
        if not parent_record:
            raise ValueError('未找到所属节点。')
        parent_record_dict = dict(parent_record)
        parent = build_node_view(parent_record_dict)
        parent_props = parent_record_dict.get('props') or {}
        parent_identity = str(parent_props.get('id') or parent_id).strip()

        if node_kind == '属性值':
            if parent.get('level') != '单机级故障模式':
                raise ValueError('属性值必须绑定到单机级故障模式节点。')
            spec = RELATION_OPERATION_SPECS.get(relation_label)
            if not spec:
                raise ValueError('请选择属性值对应的关系类型。')
            node_label = spec['node_label']
            db_relation = spec['label']
            key = ''
        else:
            if not is_failure_mode_node(parent):
                raise ValueError('故障现象必须绑定到故障模式节点。')
            node_label = phenomenon_label_for_parent(parent.get('level', ''))
            db_relation = '有'
            key = f'{node_label}:{parent_identity}:{db_relation}:{name}'

        created_id = ''
        if node_kind == '属性值':
            append_fault_property_value(session, parent_id, db_relation, name)
        else:
            node_label_ref = quote_cypher_identifier(node_label)
            relation_ref = quote_cypher_identifier(db_relation)
            created = session.run(
                f'''
                MATCH (parent)
                WHERE elementId(parent) = $parentId
                MERGE (node:{node_label_ref} {{key: $key}})
                  ON CREATE SET node.created_from = 'manual',
                                node.source_type = 'manual'
                SET node.name = $name,
                    node.updated_at = datetime()
                MERGE (parent)-[rel:{relation_ref}]->(node)
                  ON CREATE SET rel.created_from = 'manual'
                RETURN elementId(node) AS id
                ''',
                parentId=parent_id,
                key=key,
                name=name,
            ).single()
            created_id = created['id'] if created else ''

    graph = build_graph_payload()
    if node_kind == '属性值':
        created_id = find_related_attribute_node_id(parent_id, db_relation, graph) or ''
    return {'nodeId': created_id, 'graph': graph}


def update_business_node(node_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get('name') or '').strip()
    if not name:
        raise ValueError('节点名称不能为空。')

    with get_driver().session(database=get_database()) as session:
        record = session.run(
            'MATCH (node) WHERE elementId(node) = $nodeId RETURN elementId(node) AS id, labels(node)[0] AS label, properties(node) AS props',
            nodeId=node_id,
        ).single()
        if not record:
            raise ValueError('未找到需要修改的节点。')
        node = build_node_view(dict(record))
        old_name = str(node.get('name') or '').strip()
        if is_attribute_value_node(node):
            replace_attribute_value_in_parent_properties(session, node_id, old_name, name)
        session.run(
            '''
            MATCH (node)
            WHERE elementId(node) = $nodeId
            SET node.name = $name,
                node.updated_at = datetime()
            ''',
            nodeId=node_id,
            name=name,
        ).consume()

    return {'nodeId': node_id, 'graph': build_graph_payload()}


def delete_business_node(node_id: str) -> dict[str, Any]:
    with get_driver().session(database=get_database()) as session:
        record = session.run(
            'MATCH (node) WHERE elementId(node) = $nodeId RETURN elementId(node) AS id, labels(node)[0] AS label, properties(node) AS props',
            nodeId=node_id,
        ).single()
        if not record:
            raise ValueError('未找到需要删除的节点。')
        node = build_node_view(dict(record))
        if not (is_attribute_value_node(node) or is_phenomenon_node(node)):
            raise ValueError('该节点类型只支持修改，不支持删除。')
        if is_attribute_value_node(node):
            remove_attribute_value_from_parent_properties(session, node_id, str(node.get('name') or '').strip())
        session.run('MATCH (node) WHERE elementId(node) = $nodeId DETACH DELETE node', nodeId=node_id).consume()

    return {'nodeId': node_id, 'graph': build_graph_payload()}


def phenomenon_label_for_parent(parent_level: str) -> str:
    if '组件级' in parent_level:
        return '组件级故障现象'
    if '系统级' in parent_level:
        return '系统级故障现象'
    if '总体级' in parent_level:
        return '总体级故障现象'
    return '单机级故障现象'


def find_related_attribute_node_id(parent_id: str, relation_label: str, graph: dict[str, list[dict[str, Any]]]) -> str | None:
    relation_type = normalize_relation_type(relation_label)
    expected_label = RELATION_LABELS.get(relation_type, relation_label)
    node_ids = {node['id'] for node in graph['nodes'] if is_attribute_value_node(node)}
    for edge in graph['edges']:
        if edge.get('from') == parent_id and edge.get('to') in node_ids and edge.get('label') == expected_label:
            return str(edge.get('to') or '')
    return None


def is_attribute_value_node(node: dict[str, Any]) -> bool:
    level = str(node.get('level') or '')
    label = str(node.get('label') or '')
    return level in SUPPORT_LEVELS and '故障现象' not in level and (
        level in {'属性', '属性值', *ATTRIBUTE_PROPERTY_NAMES}
        or label in {'Attribute', 'ATTRIBUTE', '属性', '属性值', *ATTRIBUTE_PROPERTY_NAMES}
    )


def is_phenomenon_node(node: dict[str, Any]) -> bool:
    return '故障现象' in str(node.get('level') or '') or '故障现象' in str(node.get('label') or '')


def normalize_property_values(value: Any) -> list[str]:
    values = value if isinstance(value, list) else [value]
    normalized: list[str] = []
    for item in values:
        text = str(item or '').strip()
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def parse_property_value_input(value: Any) -> list[str]:
    if isinstance(value, list):
        return normalize_property_values(value)
    text = str(value or '').strip()
    if not text:
        return []
    parts = re.split(r'\s*/\s*|[；;，,、]\s*', text)
    values = [part.strip() for part in parts if part and part.strip()]
    return normalize_property_values(values or [text])


def set_fault_property_values(session: Any, fault_id: str, property_name: str, values: list[str]) -> None:
    prop_ref = quote_cypher_identifier(property_name)
    if not values:
        session.run(
            f'MATCH (fault) WHERE elementId(fault) = $faultId REMOVE fault.{prop_ref}',
            faultId=fault_id,
        ).consume()
        return
    next_value: Any = values[0] if len(values) == 1 else values
    session.run(
        f'MATCH (fault) WHERE elementId(fault) = $faultId SET fault.{prop_ref} = $value',
        faultId=fault_id,
        value=next_value,
    ).consume()


def append_fault_property_value(session: Any, fault_id: str, property_name: str, value: str) -> None:
    record = session.run(
        'MATCH (fault) WHERE elementId(fault) = $faultId RETURN properties(fault) AS props',
        faultId=fault_id,
    ).single()
    props = record['props'] if record else {}
    values = normalize_property_values((props or {}).get(property_name))
    text = str(value or '').strip()
    if text and text not in values:
        values.append(text)
    set_fault_property_values(session, fault_id, property_name, values)


def attribute_parent_records(session: Any, node_id: str) -> list[dict[str, Any]]:
    return session.run(
        '''
        MATCH (fault)-[rel]->(node)
        WHERE elementId(node) = $nodeId
          AND any(label IN labels(fault) WHERE label IN ['单机级故障模式', 'UnitFailureMode'])
        RETURN elementId(fault) AS faultId, type(rel) AS relation, properties(fault) AS props
        ''',
        nodeId=node_id,
    ).data()


def replace_attribute_value_in_parent_properties(session: Any, node_id: str, old_value: str, new_value: str) -> None:
    for record in attribute_parent_records(session, node_id):
        relation = normalize_relation_type(record.get('relation', ''))
        property_name = RELATION_LABELS.get(relation, record.get('relation', ''))
        if property_name not in ATTRIBUTE_PROPERTY_NAMES:
            continue
        set_fault_property_values(session, record['faultId'], property_name, parse_property_value_input(new_value))


def remove_attribute_value_from_parent_properties(session: Any, node_id: str, value: str) -> None:
    for record in attribute_parent_records(session, node_id):
        relation = normalize_relation_type(record.get('relation', ''))
        property_name = RELATION_LABELS.get(relation, record.get('relation', ''))
        if property_name not in ATTRIBUTE_PROPERTY_NAMES:
            continue
        set_fault_property_values(session, record['faultId'], property_name, [])


def layout_position(label: str, name: str) -> tuple[float, float]:
    column = LABEL_COLUMNS.get(label, 96)
    seed = sum(ord(ch) for ch in f'{label}:{name}')
    return float(column), float((seed % 84) + 8)


def shorten(name: str) -> str:
    return name if len(name) <= 8 else f'{name[:8]}…'

def build_hierarchy_tree(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, dict[str, list[dict[str, Any]]]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for node in nodes:
        group = LEVEL_GROUP.get(node['level'], '其他')
        grouped[group][node['level']][str(node.get('owner', '')).strip()].append(node)

    tree: list[dict[str, Any]] = []
    for group_name, levels in grouped.items():
        group_children: list[dict[str, Any]] = []
        ordered_levels = sorted(levels.items(), key=lambda item: (LEVEL_ORDER.get(item[0], 999), item[0]))
        for level_name, owners in ordered_levels:
            level_children: list[dict[str, Any]] = []
            for owner, owner_nodes in sorted(owners.items(), key=lambda item: item[0]):
                sorted_nodes = sorted(owner_nodes, key=lambda item: item['name'])
                if not owner or owner in {'???', '\u672a\u5206\u7c7b', '???'}:
                    level_children.extend({'id': item['id'], 'name': item['name']} for item in sorted_nodes)
                else:
                    level_children.append({
                        'id': f'owner::{level_name}::{owner}',
                        'name': owner,
                        'children': [{'id': item['id'], 'name': item['name']} for item in sorted_nodes],
                    })
            if len(ordered_levels) == 1 and level_name == group_name:
                group_children.extend(level_children)
            else:
                group_children.append({'id': f'level::{level_name}', 'name': level_name, 'children': level_children})
        tree.append({'id': f'group::{group_name}', 'name': group_name, 'children': group_children})

    tree.sort(key=lambda item: (GROUP_ORDER.get(item['name'], 999), item['name']))
    return tree


def tree_node_sort_key(node: dict[str, Any]) -> tuple[Any, ...]:
    return (
        LEVEL_ORDER.get(node.get('level', ''), 999),
        str(node.get('owner', '')).strip(),
        node.get('name', ''),
    )


def build_ontology_tree(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not nodes:
        return []

    del edges

    grouped_by_label: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node in nodes:
        grouped_by_label[str(node.get('label', node.get('level', '其他')))].append(node)

    def make_leaf(node: dict[str, Any]) -> dict[str, Any]:
        return {
            'id': node['id'],
            'name': node['name'],
            'level': node.get('level', ''),
        }

    def make_owner_group(display_level: str, owner: str, owner_nodes: list[dict[str, Any]]) -> dict[str, Any]:
        sorted_nodes = sorted(owner_nodes, key=tree_node_sort_key)
        return {
            'id': f'ontology::owner::{display_level}::{owner}',
            'name': owner,
            'level': display_level,
            'meta': f'共 {len(sorted_nodes)} 个实例',
            'children': [make_leaf(node) for node in sorted_nodes],
        }

    tree: list[dict[str, Any]] = []
    ordered_labels = sorted(
        grouped_by_label.items(),
        key=lambda item: (
            LEVEL_ORDER.get(item[1][0].get('level', item[0]), 999),
            item[1][0].get('level', item[0]),
            item[0],
        ),
    )

    for raw_label, label_nodes in ordered_labels:
        sorted_nodes = sorted(label_nodes, key=tree_node_sort_key)
        display_level = sorted_nodes[0].get('level', raw_label)
        owner_buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for node in sorted_nodes:
            owner = str(node.get('owner', '')).strip()
            owner_buckets[owner].append(node)

        children: list[dict[str, Any]] = []
        for owner, owner_nodes in sorted(owner_buckets.items(), key=lambda item: (item[0] == '', item[0], tree_node_sort_key(item[1][0]))):
            if not owner or owner in {'???', '未分类'}:
                children.extend(make_leaf(node) for node in owner_nodes)
                continue

            if len(owner_nodes) == 1:
                children.extend(make_leaf(node) for node in owner_nodes)
                continue

            children.append(make_owner_group(display_level, owner, owner_nodes))

        tree.append({
            'id': f'ontology::class::{raw_label}',
            'name': display_level,
            'meta': f'共 {len(sorted_nodes)} 个实例',
            'children': children,
        })

    return tree


def rank_nodes(query_text: str, nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return rank_nodes_with_project_bert(query_text, nodes)


def rank_fault_chain_query_nodes(query_text: str, graph: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    candidates = semantic_candidate_pool(graph['nodes'])
    return prioritize_fault_chain_query_nodes(rank_nodes_with_project_bert(query_text, candidates), graph)


OPEN_FAILURE_EXPANSIONS = (
    '一次打不开',
    '打不开',
    '无法打开',
    '不能打开',
    '开启失败',
    '开不了',
    '卡滞',
    '通电后打开',
)

OPEN_DELAY_EXPRESSIONS = (
    '多次才能打开',
    '多次才打开',
    '多次打开才能打开',
    '多次开启才能打开',
    '多次启动才能打开',
    '需要多次才能打开',
    '需要多次打开',
    '反复打开才能打开',
    '反复开启才能打开',
    '反复启动才能打开',
    '打开困难',
    '开启困难',
    '启动困难',
    '不易打开',
)

VALVE_TERMS = ('阀', '阀门', '电磁阀', '单向阀')
ENGINE_TERMS = ('发动机', '引擎')
OPEN_SUBJECT_TERMS = VALVE_TERMS + ENGINE_TERMS

FAILURE_INTENT_TERMS = (
    '故障',
    '失效',
    '异常',
    '无法',
    '不能',
    '不起',
    '不动',
    '打不开',
    '一次打不开',
    '开不了',
    '卡滞',
    '困难',
    '多次',
    '反复',
)

QUERY_REWRITE_RULES = (
    ('多次才能打开', '一次打不开'),
    ('多次才打开', '一次打不开'),
    ('多次打开才能打开', '一次打不开'),
    ('多次开启才能打开', '一次打不开'),
    ('多次启动才能打开', '一次打不开'),
    ('需要多次才能打开', '一次打不开'),
    ('需要多次打开', '一次打不开'),
    ('反复打开才能打开', '一次打不开'),
    ('反复开启才能打开', '一次打不开'),
    ('反复启动才能打开', '一次打不开'),
    ('打开困难', '一次打不开'),
    ('开启困难', '一次打不开'),
    ('启动困难', '一次打不开'),
    ('不易打开', '一次打不开'),
    ('无法打开', '打不开'),
    ('不能打开', '打不开'),
    ('开不了', '打不开'),
    ('开启失败', '打不开'),
)


def expand_terms(query: str) -> list[str]:
    terms = {query}
    synonym_groups = [
        ('泄漏', '外漏', '渗漏', '漏液', '漏油'),
        ('软管', '摇摆软管'),
        ('动力下降', '推力下降', '压力下降', '比冲过小', '无推力'),
        ('姿态', '控制', '回位'),
        ('疲劳', '失稳'),
        ('结构破坏', '破坏'),
        OPEN_FAILURE_EXPANSIONS,
        OPEN_DELAY_EXPRESSIONS,
        VALVE_TERMS,
        ENGINE_TERMS,
    ]
    for group in synonym_groups:
        if any(term in query for term in group):
            terms.update(group)
    if is_open_failure_query(query):
        terms.update(OPEN_FAILURE_EXPANSIONS)
        terms.update(OPEN_DELAY_EXPRESSIONS)
    for size in (2, 3, 4):
        for index in range(len(query) - size + 1):
            segment = query[index:index + size]
            if segment.strip():
                terms.add(segment)
    return sorted(terms, key=len, reverse=True)


def normalize(text: str) -> str:
    value = str(text).lower().strip()
    replacements = {
        '渗漏': '泄漏',
        '外漏': '泄漏',
        '漏液': '泄漏',
        '漏油': '泄漏',
        '推力波动': '动力下降',
        '动力波动': '动力下降',
        '无法打开': '打不开',
        '不能打开': '打不开',
        '开不了': '打不开',
        '开启失败': '打不开',
        '卡死': '卡滞',
        '阀门': '阀',
        '液氧阀': '阀',
        '氧阀': '阀',
    }
    replacements.update(dict(QUERY_REWRITE_RULES))
    for source, target in sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True):
        value = value.replace(source, target)
    return value


def is_open_failure_query(query: str) -> bool:
    return (
        any(term in query for term in OPEN_FAILURE_EXPANSIONS)
        or any(term in query for term in OPEN_DELAY_EXPRESSIONS)
    ) and any(term in query for term in OPEN_SUBJECT_TERMS)


def query_variants(query_text: str) -> list[str]:
    raw = str(query_text).lower().strip()
    normalized = normalize(raw)
    variants = {raw, normalized}

    for source, target in sorted(QUERY_REWRITE_RULES, key=lambda item: len(item[0]), reverse=True):
        if source in raw:
            variants.add(raw.replace(source, target))
            variants.add(target)
        if source in normalized:
            variants.add(normalized.replace(source, target))
            variants.add(target)

    if any(term in normalized for term in OPEN_DELAY_EXPRESSIONS) or '一次打不开' in normalized:
        variants.add(normalized.replace('一次打不开', '打不开'))
        for subject in OPEN_SUBJECT_TERMS:
            if subject in normalized:
                variants.add(f'{subject}打不开')
                variants.add(f'{subject}一次打不开')

    return sorted((item for item in variants if item), key=len, reverse=True)


def expanded_query_terms(variants: list[str]) -> set[str]:
    terms: set[str] = set()
    for variant in variants:
        terms.update(expand_terms(variant))
    return {term for term in terms if term}


def has_failure_intent(variants: list[str]) -> bool:
    return any(any(term in variant for term in FAILURE_INTENT_TERMS) for variant in variants)


def node_corpus(node: dict[str, Any]) -> str:
    return normalize(' '.join(str(node.get(field, '')) for field in ('name', 'owner', 'rawText', 'key', 'level', 'label')))


def ngrams(text: str) -> set[str]:
    value = normalize(text)
    grams: set[str] = set()
    for size in (2, 3, 4):
        for index in range(len(value) - size + 1):
            segment = value[index:index + size]
            if segment.strip():
                grams.add(segment)
    return grams


def rank_nodes_with_semantic_fallback(
    query_text: str,
    nodes: list[dict[str, Any]],
    allowed_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    candidates = semantic_candidate_pool(nodes, allowed_ids)
    if not candidates:
        return []
    return rank_nodes_with_project_bert(query_text, candidates)


def semantic_candidate_pool(nodes: list[dict[str, Any]], allowed_ids: set[str] | None = None) -> list[dict[str, Any]]:
    allowed = [node for node in nodes if allowed_ids is None or node.get('id') in allowed_ids]
    return sorted(allowed, key=query_candidate_sort_key)


def unique_non_empty_texts(values: list[str], limit: int = 8) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or '').strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def llm_rewrite_query_texts(query_text: str, candidates: list[dict[str, Any]]) -> list[str]:
    if not is_llm_query_enabled():
        set_llm_trace({
            'enabled': False,
            'called': False,
            'rewriteSource': 'input',
            'fallback': 'input-query',
        })
        return [query_text]

    llm_candidates = llm_candidate_pool(candidates)
    if not llm_candidates:
        set_llm_trace({
            'enabled': True,
            'called': False,
            'rewriteSource': 'input',
            'fallback': 'input-query',
            'error': '没有可供大模型参考的图谱文本，已直接使用原始问题做 BERT 匹配',
        })
        return [query_text]

    try:
        set_llm_trace({
            'enabled': True,
            'called': True,
            'model': get_llm_model(),
            'candidateCount': len(llm_candidates),
            'rewriteSource': 'llm',
        })
        payload = call_query_rewrite_llm(query_text, llm_candidates)
    except Exception as exc:
        set_llm_trace({
            'enabled': True,
            'called': True,
            'model': get_llm_model(),
            'candidateCount': len(llm_candidates),
            'rewriteSource': 'input',
            'fallback': 'input-query',
            'error': f'大模型改写失败，已直接使用原始问题做 BERT 匹配：{exc}',
        })
        return [query_text]

    rewrites = parse_llm_rewrite_texts(payload)
    if not rewrites:
        update_llm_trace({
            'rewriteSource': 'input',
            'fallback': 'input-query',
            'selection': payload,
            'error': '大模型未返回可用改写，已直接使用原始问题做 BERT 匹配',
        })
        return [query_text]

    query_texts = unique_non_empty_texts([query_text, *rewrites])
    update_llm_trace({
        'rewriteSource': 'llm',
        'rewrites': rewrites,
        'rewriteCount': len(rewrites),
        'reason': payload.get('reason'),
    })
    return query_texts


def parse_llm_rewrite_texts(payload: dict[str, Any]) -> list[str]:
    raw_values = payload.get('rewrites')
    if not isinstance(raw_values, list):
        single = raw_values if isinstance(raw_values, str) else payload.get('canonicalQuery') or payload.get('rewrite')
        raw_values = [single] if single else []
    return unique_non_empty_texts([str(item) for item in raw_values if item], limit=6)


def bert_query_texts(query_text: str, candidates: list[dict[str, Any]]) -> list[str]:
    return llm_rewrite_query_texts(query_text, candidates)


def compact_exact_text(text: str) -> str:
    return re.sub(r'\s+', '', str(text or '').strip().lower())


def node_exact_texts(node: dict[str, Any]) -> list[str]:
    fields = ('name', 'rawText', 'key')
    return unique_non_empty_texts([str(node.get(field, '')) for field in fields], limit=6)


def query_exactly_matches_node(query_texts: list[str], node: dict[str, Any]) -> bool:
    query_values = {compact_exact_text(text) for text in query_texts if compact_exact_text(text)}
    node_values = {compact_exact_text(text) for text in node_exact_texts(node) if compact_exact_text(text)}
    return bool(query_values & node_values)


def semantic_confidence_ratio(value: Any, exact_match: bool = False) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        score = 0.0
    score = max(0.0, min(1.0, score))
    if not exact_match:
        score = min(score, 0.99)
    return score


def confidence_ratio_to_percent(value: float) -> int:
    return max(1, min(100, int(round(value * 100))))


def bounded_percent_score(value: Any, exact_match: bool = False) -> int:
    try:
        score = int(round(float(value)))
    except (TypeError, ValueError):
        score = 0
    upper_bound = 100 if exact_match else 99
    return max(1, min(upper_bound, score))


def rank_nodes_with_project_bert(query_text: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    encoder = get_project_bert_encoder()
    if not encoder:
        message = 'BERT 模型未加载，故障链查询已停止：请检查 FAULT_QUERY_BERT_MODEL 或本地 bert-base-chinese 模型文件。'
        update_llm_trace({'semanticFallback': 'bert-error', 'error': message})
        raise FaultQueryBertError(message)

    tokenizer, model, device, source = encoder
    limit = max(1, int(os.environ.get('FAULT_QUERY_BERT_CANDIDATE_LIMIT', '256')))
    selected_candidates = candidates[:limit]
    if not selected_candidates:
        return []
    query_texts = bert_query_texts(query_text, selected_candidates)
    node_texts = [node_primary_semantic_text(node) for node in selected_candidates]
    object_texts = [node_object_semantic_text(node) for node in selected_candidates]
    texts = [*query_texts, *node_texts, *object_texts]

    try:
        import torch

        embeddings = encode_with_project_bert(tokenizer, model, device, texts)
        query_count = len(query_texts)
        if embeddings.size(0) < query_count + len(selected_candidates):
            message = 'BERT 向量输出数量异常，故障链查询已停止。'
            update_llm_trace({'semanticFallback': 'bert-error', 'semanticModel': source, 'error': message})
            raise FaultQueryBertError(message)
        query_embeddings = embeddings[:query_count]
        node_embeddings = embeddings[query_count:query_count + len(selected_candidates)]
        object_embeddings = embeddings[query_count + len(selected_candidates):]
        node_score_matrix = torch.matmul(node_embeddings, query_embeddings.T)
        object_score_matrix = torch.matmul(object_embeddings, query_embeddings.T) if object_embeddings.size(0) else None
        node_scores, node_query_indexes = torch.max(node_score_matrix, dim=1)
        if object_score_matrix is not None and object_score_matrix.size(0):
            object_scores, _ = torch.max(object_score_matrix, dim=1)
        else:
            object_scores = torch.zeros(len(selected_candidates))
    except FaultQueryBertError:
        raise
    except Exception as exc:
        message = f'BERT 向量匹配失败，故障链查询已停止：{exc}'
        update_llm_trace({'semanticFallback': 'bert-error', 'semanticModel': source, 'error': message})
        raise FaultQueryBertError(message) from exc

    ranked: list[dict[str, Any]] = []
    for index, (node, similarity) in enumerate(zip(selected_candidates, node_scores.tolist())):
        node_score = float(node_scores[index])
        object_score = float(object_scores[index]) if index < len(object_scores) else 0.0
        matched_query_text = query_texts[int(node_query_indexes[index])] if index < len(node_query_indexes) else query_text
        exact_match = query_exactly_matches_node([query_text], node)
        raw_node_score = 1.0 if exact_match else node_score
        final_node_score = semantic_confidence_ratio(raw_node_score, exact_match)
        semantic_score = confidence_ratio_to_percent(final_node_score)
        ranked.append({
            **node,
            'score': semantic_score,
            'semanticScore': semantic_score,
            'nodeSemanticScore': round(final_node_score, 6),
            'bertNodeSemanticScore': round(node_score, 6),
            'objectSemanticScore': round(semantic_confidence_ratio(object_score, exact_match), 4),
            'matchedQueryText': matched_query_text,
            'queryRewrites': query_texts,
            'exactTextMatch': exact_match,
            'rankSource': 'bert',
        })

    ranked.sort(key=lambda item: (-item['nodeSemanticScore'], -item['objectSemanticScore'], item['name']))
    if ranked:
        update_llm_trace({'semanticFallback': 'bert', 'semanticModel': source})
    return ranked


@lru_cache(maxsize=1)
def get_project_bert_encoder() -> tuple[Any, Any, str, str]:
    try:
        import torch
        from transformers import AutoModel, AutoTokenizer
    except Exception as exc:
        raise FaultQueryBertError(
            f'BERT 依赖未安装或不可导入：{exc}。请在启动 Flask 的同一个 Python 环境中安装 backend/requirements.txt。'
        ) from exc

    source = resolve_project_bert_source()
    if not source:
        raise FaultQueryBertError(
            f'未找到 BERT 模型目录。当前 FAULT_QUERY_BERT_MODEL={os.environ.get("FAULT_QUERY_BERT_MODEL", "")!r}，'
            f'默认查找 {PROJECT_ROOT / "models" / DEFAULT_BERT_MODEL_NAME}。'
        )

    try:
        tokenizer = AutoTokenizer.from_pretrained(source, local_files_only=True)
        model_kwargs: dict[str, Any] = {'local_files_only': True}
        if (Path(source) / 'pytorch_model.bin').exists():
            model_kwargs['use_safetensors'] = False
        model = AutoModel.from_pretrained(source, **model_kwargs)
        device = os.environ.get('FAULT_QUERY_BERT_DEVICE', '').strip() or ('cuda' if torch.cuda.is_available() else 'cpu')
        model = model.to(device)
        model.eval()
        return tokenizer, model, device, source
    except Exception as exc:
        raise FaultQueryBertError(f'BERT 模型加载失败：source={source}，error={exc}') from exc


def resolve_project_bert_source() -> str | None:
    configured = os.environ.get('FAULT_QUERY_BERT_MODEL', '').strip()
    for candidate in fault_query_bert_candidates(configured):
        if candidate and candidate.exists():
            return str(candidate)

    for model_name in (configured, DEFAULT_BERT_MODEL_NAME):
        snapshot = resolve_huggingface_snapshot(model_name)
        if snapshot:
            return str(snapshot)

    bundled_model = extract_bundled_bert_model()
    return str(bundled_model) if bundled_model else None


def fault_query_bert_candidates(configured: str = '') -> list[Path]:
    candidates: list[Path] = []
    if configured:
        configured_path = Path(configured)
        candidates.append(configured_path if configured_path.is_absolute() else PROJECT_ROOT / configured_path)
    candidates.extend([
        PROJECT_ROOT / 'models' / DEFAULT_BERT_MODEL_NAME,
        PROJECT_ROOT / 'fknow' / 'models' / DEFAULT_BERT_MODEL_NAME,
    ])
    return candidates


def describe_bert_source(path: Path) -> dict[str, Any]:
    required_files = ['config.json', 'vocab.txt']
    weight_files = ['pytorch_model.bin', 'model.safetensors']
    return {
        'path': str(path),
        'exists': path.exists(),
        'isDir': path.is_dir(),
        'requiredFiles': {name: (path / name).exists() for name in required_files},
        'weightFiles': {name: (path / name).exists() for name in weight_files},
        'hasWeights': any((path / name).exists() for name in weight_files),
    }


def dependency_status(module_name: str) -> dict[str, Any]:
    try:
        module = __import__(module_name)
        return {
            'ok': True,
            'version': str(getattr(module, '__version__', 'unknown')),
            'file': str(getattr(module, '__file__', '')),
        }
    except Exception as exc:
        return {'ok': False, 'error': str(exc)}


def bert_diagnostics(load_model: bool = False) -> dict[str, Any]:
    configured = os.environ.get('FAULT_QUERY_BERT_MODEL', '').strip()
    candidates = fault_query_bert_candidates(configured)
    resolved_source = resolve_project_bert_source()
    torch_status = dependency_status('torch')
    transformers_status = dependency_status('transformers')
    diagnostics: dict[str, Any] = {
        'ok': False,
        'message': '',
        'pythonExecutable': sys.executable,
        'pythonVersion': sys.version,
        'projectRoot': str(PROJECT_ROOT),
        'cwd': str(Path.cwd()),
        'env': {
            'FAULT_QUERY_BERT_MODEL': configured,
            'FAULT_QUERY_BERT_DEVICE': os.environ.get('FAULT_QUERY_BERT_DEVICE', '').strip(),
            'FAULT_QUERY_BERT_CANDIDATE_LIMIT': os.environ.get('FAULT_QUERY_BERT_CANDIDATE_LIMIT', '').strip(),
            'FAULT_QUERY_BERT_MAX_LENGTH': os.environ.get('FAULT_QUERY_BERT_MAX_LENGTH', '').strip(),
            'FAULT_QUERY_BERT_BATCH_SIZE': os.environ.get('FAULT_QUERY_BERT_BATCH_SIZE', '').strip(),
        },
        'dependencies': {
            'torch': torch_status,
            'transformers': transformers_status,
        },
        'candidates': [describe_bert_source(path) for path in candidates],
        'resolvedSource': resolved_source or '',
        'loadRequested': load_model,
    }

    if not torch_status.get('ok') or not transformers_status.get('ok'):
        diagnostics['message'] = 'BERT 依赖未安装或不可导入，请检查 Flask 启动所用 Python 环境。'
        return diagnostics

    if not resolved_source:
        diagnostics['message'] = '未找到 BERT 模型目录，请检查 FAULT_QUERY_BERT_MODEL 或 models/bert-base-chinese。'
        return diagnostics

    source_info = describe_bert_source(Path(resolved_source))
    diagnostics['resolvedSourceFiles'] = source_info
    missing_required = [name for name, exists in source_info['requiredFiles'].items() if not exists]
    if missing_required or not source_info['hasWeights']:
        diagnostics['message'] = f"BERT 模型文件不完整，缺少：{', '.join(missing_required) or '权重文件 pytorch_model.bin/model.safetensors'}。"
        return diagnostics

    if load_model:
        try:
            _, _, device, source = get_project_bert_encoder()
            diagnostics['device'] = device
            diagnostics['resolvedSource'] = source
        except FaultQueryBertError as exc:
            diagnostics['message'] = str(exc)
            diagnostics['traceback'] = ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            return diagnostics
        except Exception as exc:
            diagnostics['message'] = f'BERT 诊断加载失败：{exc}'
            diagnostics['traceback'] = ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            return diagnostics

    diagnostics['ok'] = True
    diagnostics['message'] = 'BERT 配置检查通过。' if not load_model else 'BERT 模型加载成功。'
    return diagnostics


def resolve_huggingface_snapshot(model_name: str) -> Path | None:
    if not model_name or any(separator in model_name for separator in ('\\', '/')) and Path(model_name).exists():
        return None
    snapshot_root = Path.home() / '.cache' / 'huggingface' / 'hub' / f"models--{model_name.replace('/', '--')}" / 'snapshots'
    if not snapshot_root.exists():
        return None
    snapshots = sorted(path for path in snapshot_root.iterdir() if path.is_dir())
    return snapshots[-1] if snapshots else None


def extract_bundled_bert_model() -> Path | None:
    target = PROJECT_ROOT / 'models' / DEFAULT_BERT_MODEL_NAME
    if (target / 'config.json').exists() and (target / 'vocab.txt').exists():
        return target

    archive = PROJECT_ROOT / 'fknow.zip'
    if not archive.exists():
        return None

    prefix = f'fknow/models/{DEFAULT_BERT_MODEL_NAME}/'
    target_root = target.resolve()
    try:
        with zipfile.ZipFile(archive) as zip_file:
            members = [info for info in zip_file.infolist() if info.filename.startswith(prefix) and not info.is_dir()]
            if not members:
                return None
            target.mkdir(parents=True, exist_ok=True)
            for info in members:
                relative_name = info.filename[len(prefix):]
                if not relative_name:
                    continue
                destination = (target / relative_name).resolve()
                if target_root not in destination.parents and destination != target_root:
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with zip_file.open(info) as source_file, destination.open('wb') as target_file:
                    shutil.copyfileobj(source_file, target_file)
    except Exception:
        return None

    return target if (target / 'config.json').exists() and (target / 'vocab.txt').exists() else None


def encode_with_project_bert(tokenizer: Any, model: Any, device: str, texts: list[str]) -> Any:
    import torch
    import torch.nn.functional as functional

    max_length = max(16, int(os.environ.get('FAULT_QUERY_BERT_MAX_LENGTH', '160')))
    batch_size = max(1, int(os.environ.get('FAULT_QUERY_BERT_BATCH_SIZE', '16')))
    batches = []
    with torch.inference_mode():
        for offset in range(0, len(texts), batch_size):
            encoded = tokenizer(
                texts[offset:offset + batch_size],
                padding=True,
                truncation=True,
                max_length=max_length,
                return_tensors='pt',
            )
            encoded = {key: value.to(device) for key, value in encoded.items()}
            outputs = model(**encoded)
            mask = encoded['attention_mask'].unsqueeze(-1).expand(outputs.last_hidden_state.size()).float()
            pooled = (outputs.last_hidden_state * mask).sum(dim=1) / torch.clamp(mask.sum(dim=1), min=1e-9)
            batches.append(functional.normalize(pooled, p=2, dim=1).cpu())
    return torch.cat(batches, dim=0) if batches else torch.empty((0, 0))


def node_semantic_text(node: dict[str, Any]) -> str:
    return '；'.join(part for part in (node_primary_semantic_text(node), node_object_semantic_text(node)) if part)


def node_primary_semantic_text(node: dict[str, Any]) -> str:
    fields = ('name', 'level', 'rawText', 'key', 'status', 'description', 'label')
    return '；'.join(str(node.get(field, '')).strip() for field in fields if str(node.get(field, '')).strip())


def node_object_semantic_text(node: dict[str, Any]) -> str:
    fields = ('owner',)
    return '；'.join(str(node.get(field, '')).strip() for field in fields if str(node.get(field, '')).strip())


def set_llm_trace(trace: dict[str, Any]) -> None:
    if has_request_context():
        g.llm_trace = trace


def update_llm_trace(updates: dict[str, Any]) -> None:
    if not has_request_context():
        return
    trace = dict(getattr(g, 'llm_trace', {'enabled': is_llm_query_enabled(), 'called': False}))
    trace.update(updates)
    g.llm_trace = trace


def get_llm_trace() -> dict[str, Any]:
    if not has_request_context():
        return {'enabled': is_llm_query_enabled(), 'called': False}
    return getattr(g, 'llm_trace', {'enabled': is_llm_query_enabled(), 'called': False})


def log_query_backend_strategy(query_text: str, best_node: dict[str, Any] | None = None) -> None:
    trace = get_llm_trace()
    if trace.get('semanticFallback') == 'bert-error':
        strategy = 'BERT失败'
        detail = str(trace.get('error') or 'BERT 未跑通')
    elif trace.get('rewriteSource') == 'llm':
        strategy = '大模型改写+BERT'
        detail = f"{trace.get('model') or get_llm_model()} -> {trace.get('semanticModel') or resolve_project_bert_source() or DEFAULT_BERT_MODEL_NAME}"
    else:
        strategy = 'BERT'
        detail = str(trace.get('semanticModel') or resolve_project_bert_source() or DEFAULT_BERT_MODEL_NAME)

    best_name = best_node.get('name', '') if best_node else ''
    best_score = top_match_score(query_text, best_node) if best_node else ''
    print(
        f"[FaultQuery] query={query_text!r} strategy={strategy} detail={detail} "
        f"best={best_name!r} score={best_score}",
        flush=True,
    )


def log_runtime_config() -> None:
    bert_source = resolve_project_bert_source()
    llm_state = 'enabled' if is_llm_query_enabled() else 'disabled'
    print(
        "[Startup] Fault query logging enabled. "
        f"Python={sys.executable} "
        f"offline={offline_enabled()} "
        f"LLM={llm_state} model={get_llm_model()} base={get_llm_base_url()} "
        f"BERT={bert_source or 'not found'} "
        f"Neo4j={get_neo4j_uri()} database={get_database() or 'neo4j'}",
        flush=True,
    )


def is_llm_query_enabled() -> bool:
    enabled = os.environ.get('FAULT_QUERY_LLM_ENABLED', '').strip().lower()
    if enabled in {'0', 'false', 'no', 'off'}:
        return False
    if enabled and enabled not in {'1', 'true', 'yes', 'on'}:
        return False
    base_url = get_llm_base_url()
    if not url_allowed_in_offline(base_url):
        return False
    return bool(base_url and get_llm_model())


def get_llm_base_url() -> str:
    return (
        os.environ.get('FAULT_QUERY_LLM_BASE_URL', '').strip()
        or os.environ.get('QWEN3_BASE_URL', '').strip()
        or os.environ.get('DASHSCOPE_BASE_URL', '').strip()
        or DEFAULT_LOCAL_LLM_BASE_URL
    )


def get_llm_api_key() -> str:
    explicit_key = (
        os.environ.get('FAULT_QUERY_LLM_API_KEY', '').strip()
        or os.environ.get('QWEN3_API_KEY', '').strip()
    )
    if explicit_key:
        return explicit_key
    if 'dashscope' in get_llm_base_url().lower():
        return os.environ.get('DASHSCOPE_API_KEY', '').strip()
    return ''


def get_llm_model() -> str:
    return (
        os.environ.get('FAULT_QUERY_LLM_MODEL', '').strip()
        or os.environ.get('QWEN3_MODEL', '').strip()
        or os.environ.get('DASHSCOPE_MODEL', '').strip()
        or DEFAULT_LOCAL_LLM_MODEL
    )


def llm_candidate_pool(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    limit = max(1, int(os.environ.get('FAULT_QUERY_LLM_CANDIDATE_LIMIT', '256')))
    return sorted(nodes, key=query_candidate_sort_key)[:limit]


def call_query_rewrite_llm(query_text: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    base_url = get_llm_base_url().rstrip('/')
    if not url_allowed_in_offline(base_url):
        raise RuntimeError(f'离线模式禁止访问公网大模型接口：{base_url}')
    url = base_url if base_url.endswith('/chat/completions') else f'{base_url}/chat/completions'
    timeout = float(os.environ.get('FAULT_QUERY_LLM_TIMEOUT', '4'))
    api_key = get_llm_api_key()
    model = get_llm_model()
    candidate_payload = [{
        'id': item['id'],
        'name': item['name'],
        'level': item.get('level', ''),
        'owner': item.get('owner', ''),
        'rawText': item.get('rawText', ''),
        'key': item.get('key', ''),
    } for item in candidates]

    prompt = (
        '你是故障知识图谱查询语义转写器，不负责选择节点、排序或打分。'
        '请根据候选图谱文本的 name、rawText、key、level、owner 的命名结构，'
        '把用户口语化问题改写成 1 到 6 个更可能出现在图谱节点中的表达方式。'
        '改写应尽量短，优先接近故障模式、故障现象或实体对象名称；不要输出候选节点 ID；不要做最终匹配。'
        '例如“发动机多次才能打开”可改写为“发动机一次起动失败”“发动机一次打不开”“一次起动失败”。'
        '只输出 JSON：{"rewrites":["..."],"reason":"..."}。'
    )
    payload = {
        'model': model,
        'temperature': float(os.environ.get('FAULT_QUERY_LLM_TEMPERATURE', '0.7')),
        'messages': [
            {'role': 'system', 'content': prompt},
            {'role': 'user', 'content': json.dumps({'query': query_text, 'candidates': candidate_payload}, ensure_ascii=False)},
        ],
    }
    if os.environ.get('QWEN3_ENABLE_THINKING', '').strip().lower() in {'1', 'true', 'yes', 'on'}:
        payload['enable_thinking'] = True
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    headers = {'Content-Type': 'application/json'}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    req = urlrequest.Request(
        url,
        data=body,
        headers=headers,
        method='POST',
    )
    with urlrequest.urlopen(req, timeout=timeout) as response:
        data = json.loads(response.read().decode('utf-8'))
    content = data.get('choices', [{}])[0].get('message', {}).get('content', '')
    return parse_llm_json(content)


def parse_llm_json(content: str) -> dict[str, Any]:
    value = str(content).strip()
    if value.startswith('```'):
        value = re.sub(r'^```(?:json)?\s*', '', value)
        value = re.sub(r'\s*```$', '', value)
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', value, flags=re.S)
        if not match:
            return {}
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}


def load_local_env() -> None:
    candidates = [
        Path(__file__).resolve().with_name('.env'),
        Path(__file__).resolve().parent.parent / '.env',
    ]
    for env_path in candidates:
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


def build_top_matches(query_text: str, ranked: list[dict[str, Any]]) -> list[dict[str, Any]]:
    matches = ranked[:5]
    if not matches:
        return []

    top_matches: list[dict[str, Any]] = []
    for index, item in enumerate(matches, start=1):
        score = top_match_score(query_text, item)
        top_matches.append({
            'rank': index,
            'id': item['id'],
            'name': item['name'],
            'level': item.get('level', ''),
            'owner': item.get('owner', ''),
            'score': score,
            'confidence': top_match_confidence(query_text, item),
            'matchedKeywords': matched_terms(query_text, item),
        })
    return top_matches


def top_match_score(query_text: str, item: dict[str, Any]) -> int:
    exact_match = bool(item.get('exactTextMatch')) or query_exactly_matches_node([query_text], item)
    return bounded_percent_score(item.get('score', 0), exact_match)


def top_match_confidence(query_text: str, item: dict[str, Any]) -> float:
    exact_match = bool(item.get('exactTextMatch')) or query_exactly_matches_node([query_text], item)
    if item.get('rankSource') == 'bert':
        try:
            node_score = max(0.0, float(item.get('nodeSemanticScore', 0.0)))
        except (TypeError, ValueError):
            node_score = 0.0
        confidence = round(semantic_confidence_ratio(node_score, exact_match) * 100, 1)
        return max(1, min(100, confidence))
    try:
        confidence = round(float(item.get('score', 0) or 0), 1)
    except (TypeError, ValueError):
        confidence = 0.0
    if not exact_match:
        confidence = min(confidence, 99.0)
    return max(1, min(100, confidence))


def query_candidate_sort_key(node: dict[str, Any]) -> tuple[Any, ...]:
    return (
        0 if is_failure_mode_node(node) else 1,
        LEVEL_ORDER.get(node.get('level', ''), 999),
        node.get('owner', ''),
        node.get('name', ''),
    )


def prioritize_fault_chain_query_nodes(ranked: list[dict[str, Any]], graph: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    if not ranked:
        return []
    connected_ids = fault_chain_connected_node_ids(graph)
    connected_failures = [
        node for node in ranked
        if node.get('id') in connected_ids and is_failure_mode_node(node)
    ]
    if connected_failures:
        return connected_failures

    failures = [node for node in ranked if is_failure_mode_node(node)]
    if failures:
        return failures

    return ranked


def filter_fault_chain_query_nodes(ranked: list[dict[str, Any]], graph: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    connected_ids = fault_chain_connected_node_ids(graph)
    return [
        node for node in ranked
        if node.get('id') in connected_ids and is_failure_mode_node(node)
    ]


def fault_chain_connected_node_ids(graph: dict[str, list[dict[str, Any]]]) -> set[str]:
    ids: set[str] = set()
    for edge in graph['edges']:
        if not is_fault_chain_edge(edge):
            continue
        ids.add(edge['from'])
        ids.add(edge['to'])
    return ids


def is_failure_mode_node(node: dict[str, Any]) -> bool:
    return node.get('type') in {'root-cause', 'fault', 'impact'} or '故障模式' in str(node.get('level', ''))


def collect_related(node_id: str, graph: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    node_map = {node['id']: node for node in graph['nodes']}
    related: list[dict[str, Any]] = []
    for edge in graph['edges']:
        if not is_fault_chain_edge(edge):
            continue
        if edge['from'] == node_id and edge['to'] in node_map:
            related.append({'direction': '输出', 'relation': edge['label'], 'target': node_map[edge['to']]})
        elif edge['to'] == node_id and edge['from'] in node_map:
            related.append({'direction': '输入', 'relation': edge['label'], 'target': node_map[edge['from']]})
    return related[:8]


def build_summary(node: dict[str, Any], related: list[dict[str, Any]]) -> str:
    if not related:
        return f"Neo4j 图数据库匹配到“{node['name']}”节点，当前没有抽取到更多直接关联关系。"
    fragments = [f"{item['direction']}{item['relation']}：{item['target']['name']}" for item in related[:4]]
    return f"Neo4j 图数据库匹配到“{node['name']}”（{node['level']}），相关关系包括：" + '；'.join(fragments) + '。'


def build_checks(related: list[dict[str, Any]]) -> list[str]:
    return [f"检查{item['direction']}{item['relation']}节点：{item['target']['name']}" for item in related[:6]]


def stage_for_level(level: str) -> dict[str, Any] | None:
    for stage in STAGE_DEFINITIONS:
        if level in stage['levels']:
            return stage
    return None


def build_adjacency(graph: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    adjacency: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in graph['edges']:
        if not is_fault_chain_edge(edge):
            continue
        adjacency[edge['from']].append({'neighbor': edge['to'], 'edge': edge, 'direction': '输出'})
        adjacency[edge['to']].append({'neighbor': edge['from'], 'edge': edge, 'direction': '输入'})
    return adjacency


def is_fault_chain_edge(edge: dict[str, Any]) -> bool:
    return (
        edge.get('relationType') in FAULT_CHAIN_RELATION_TYPES
        or edge.get('label') in FAULT_CHAIN_RELATION_LABELS
    )


def shortest_paths_from(start_id: str, graph: dict[str, list[dict[str, Any]]]) -> tuple[dict[str, int], dict[str, tuple[str, dict[str, Any]]]]:
    adjacency = build_adjacency(graph)
    distances = {start_id: 0}
    previous: dict[str, tuple[str, dict[str, Any]]] = {}
    queue: deque[str] = deque([start_id])

    while queue:
        current = queue.popleft()
        for item in adjacency.get(current, []):
            neighbor = item['neighbor']
            if neighbor in distances:
                continue
            distances[neighbor] = distances[current] + 1
            previous[neighbor] = (current, item['edge'])
            queue.append(neighbor)

    return distances, previous


def reconstruct_path(target_id: str, previous: dict[str, tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    path: list[dict[str, Any]] = []
    cursor = target_id
    while cursor in previous:
        source, edge = previous[cursor]
        path.append({'from': source, 'to': cursor, 'edge': edge})
        cursor = source
    path.reverse()
    return path


def find_best_stage_node(stage: dict[str, Any], start_node: dict[str, Any], graph: dict[str, list[dict[str, Any]]], distances: dict[str, int]) -> dict[str, Any] | None:
    candidates = [node for node in graph['nodes'] if node['level'] in stage['levels'] and node['id'] in distances]
    if not candidates:
        if start_node['level'] in stage['levels']:
            return start_node
        return None
    candidates.sort(key=lambda item: (
        distances.get(item['id'], 10**6),
        stage['preference'].get(item['level'], 99),
        0 if item['type'] in {'root-cause', 'fault', 'impact'} else 1,
        item['name'],
    ))
    return candidates[0]


def collect_supporting_nodes(path_node_ids: set[str], graph: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    node_map = {node['id']: node for node in graph['nodes']}
    supports: dict[str, dict[str, Any]] = {}
    for edge in graph['edges']:
        if not is_fault_chain_edge(edge):
            continue
        if edge['from'] in path_node_ids and edge['to'] in node_map:
            target = node_map[edge['to']]
            if target['level'] in FAULT_CHAIN_SUPPORT_LEVELS:
                supports[target['id']] = target
        if edge['to'] in path_node_ids and edge['from'] in node_map:
            source = node_map[edge['from']]
            if source['level'] in FAULT_CHAIN_SUPPORT_LEVELS:
                supports[source['id']] = source
    return sorted(supports.values(), key=lambda item: (item['level'], item['name']))


def summarize_stage_step(stage_title: str, node: dict[str, Any], path: list[dict[str, Any]]) -> str:
    if not path:
        return f"{stage_title}命中“{node['name']}”，当前作为推理起点。"
    relations = ' -> '.join(step['edge']['label'] for step in path[:3])
    return f"{stage_title}定位到“{node['name']}”（{node['level']}），可通过链路 {relations} 与搜索命中内容建立关联。"


def build_full_chain_reasoning(query_text: str, node: dict[str, Any], graph: dict[str, list[dict[str, Any]]], related: list[dict[str, Any]]) -> dict[str, Any]:
    distances, previous = shortest_paths_from(node['id'], graph)
    stage_nodes: list[dict[str, Any]] = []
    path_node_ids: set[str] = {node['id']}

    for stage in STAGE_DEFINITIONS:
        stage_node = find_best_stage_node(stage, node, graph, distances)
        if not stage_node:
            continue
        path = reconstruct_path(stage_node['id'], previous) if stage_node['id'] != node['id'] else []
        stage_nodes.append({
            'stage': stage['title'],
            'node': stage_node,
            'path': path,
        })
        path_node_ids.add(stage_node['id'])
        for item in path:
            path_node_ids.add(item['from'])
            path_node_ids.add(item['to'])

    supports = collect_supporting_nodes(path_node_ids, graph)
    for support in supports:
        path_node_ids.add(support['id'])

    steps = [{
        'stage': item['stage'],
        'nodeId': item['node']['id'],
        'nodeName': item['node']['name'],
        'nodeLevel': item['node']['level'],
        'summary': summarize_stage_step(item['stage'], item['node'], item['path']),
    } for item in stage_nodes]

    evidence: list[str] = []
    keywords = matched_terms(query_text, node)
    if keywords:
        evidence.append('搜索命中关键词：' + '、'.join(keywords))
    if related:
        evidence.append('直接关联节点：' + '；'.join(f"{item['target']['name']}（{item['relation']}）" for item in related[:4]))
    if supports:
        evidence.append('支撑条件：' + '；'.join(f"{item['level']}：{item['name']}" for item in supports[:4]))

    summary_parts = [f"搜索内容首先命中“{node['name']}”（{node['level']}）。"]
    if steps:
        summary_parts.append('系统已按组件级、单体级、系统级、总体级完成链路收敛：' + ' -> '.join(
            f"{item['stage']}“{item['nodeName']}”" for item in steps
        ) + '。')
    measures = [item['name'] for item in supports if item['level'] == '设计措施']
    if measures:
        summary_parts.append('可优先结合设计措施执行处置：' + '、'.join(measures[:3]) + '。')

    checks = build_checks(related)
    for support in supports:
        checks.append(f"复核{support['level']}：{support['name']}")

    deduped_checks: list[str] = []
    for check in checks:
        if check not in deduped_checks:
            deduped_checks.append(check)

    ordered_path_ids: list[str] = []

    def append_path_id(node_id: str) -> None:
        if node_id not in ordered_path_ids:
            ordered_path_ids.append(node_id)

    append_path_id(node['id'])
    for item in stage_nodes:
        for path_item in item['path']:
            append_path_id(path_item['from'])
            append_path_id(path_item['to'])
        append_path_id(item['node']['id'])
    for support in supports:
        append_path_id(support['id'])

    return {
        'summary': ''.join(summary_parts) if summary_parts else build_summary(node, related),
        'checks': deduped_checks[:8],
        'pathNodeIds': ordered_path_ids,
        'steps': steps,
        'evidence': evidence[:4],
    }


def matched_terms(query_text: str, node: dict[str, Any]) -> list[str]:
    variants = query_variants(query_text)
    display_terms = {
        '泄漏', '软管', '动力下降', '推力下降', '压力下降', '姿态', '控制', '回位',
        '疲劳', '失稳', '结构破坏', '破坏',
        *OPEN_FAILURE_EXPANSIONS,
        *OPEN_DELAY_EXPRESSIONS,
        *OPEN_SUBJECT_TERMS,
    }
    candidates = {
        candidate for candidate in expanded_query_terms(variants)
        if candidate in display_terms or candidate in variants or len(candidate) >= 5
    }
    terms: list[str] = []
    for _, node_field in QUERY_FIELDS.items():
        value = normalize(node.get(node_field, ''))
        for candidate in sorted(candidates, key=len, reverse=True):
            if candidate and any(candidate in variant for variant in variants) and candidate in value and candidate not in terms:
                terms.append(candidate)
    return terms[:6]


load_local_env()
app = create_app()


if __name__ == '__main__':
    debug_enabled = os.environ.get('FLASK_DEBUG', '').strip().lower() in {'1', 'true', 'yes', 'on'}
    log_runtime_config()
    app.run(host='0.0.0.0', port=5000, debug=debug_enabled, use_reloader=debug_enabled)



