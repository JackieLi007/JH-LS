import json
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import table_extract_service as service
from backend.kg_pipeline_service import normalize_extraction_result_to_triple_payload

ROOT = Path(__file__).resolve().parents[1]
PARSER = runpy.run_path(str(ROOT / 'Rocket Fault' / 'import_fault_graph.py'))


class TableCompletenessTest(unittest.TestCase):
    def test_digit_leading_parts_and_nested_failure_lists(self):
        self.assertEqual(service._split_prefixed_pairs(
            '1:1R16 电阻：开路 2:1R10 1R13 电阻：开路 3:R34 电阻：开路'),
            [('1R16 电阻', '开路'), ('1R10 1R13 电阻', '开路'), ('R34 电阻', '开路')])
        self.assertEqual(service._split_prefixed_pairs(
            '1:芯片D1：1、开路 2、短路 2:电源N1：无输出'),
            [('芯片D1', '1、开路 2、短路'), ('电源N1', '无输出')])
        self.assertEqual(service._split_prefixed_pairs('1:电阻R6：电压1.5V异常'),
                         [('电阻R6', '电压1.5V异常')])

    def test_mechanical_and_electrical_natural_causes(self):
        examples = {'电磁铁异常': ('电磁铁', '异常'),
                    '先导腔供气/放气异常': ('先导腔', '供气/放气异常'),
                    '活门/推杆运动卡滞': ('活门/推杆', '运动卡滞'),
                    '主活门密封异常': ('主活门', '密封异常'),
                    '孔板异常变形': ('孔板', '异常变形'),
                    '孔板尺寸过小': ('孔板', '尺寸过小'),
                    '气簧腔温度过低': ('气簧腔', '温度过低'),
                    '变频器不输出': ('变频器', '不输出')}
        for text, expected in examples.items():
            facts, unresolved = service._parse_component_reasons(text)
            self.assertEqual(unresolved, [], text)
            self.assertEqual([(f['owner'], f['mode']) for f in facts], [expected], text)
        facts, unresolved = service._parse_component_reasons('导线断线、焊点处虚焊')
        self.assertEqual([(f['owner'], f['mode']) for f in facts], [('导线', '断线'), ('焊点处', '虚焊')])
        self.assertEqual(unresolved, [])
        for text in ('断路', '混频错误', '电磁铁未异常', '检查先导腔供气异常'):
            facts, unresolved = service._parse_component_reasons(text)
            self.assertEqual(facts, [], text)
            self.assertTrue(unresolved, text)

    def test_natural_causes_preserve_alternatives_and_do_not_guess(self):
        facts, unresolved = service._parse_component_reasons('连接器故障或导线故障')
        self.assertEqual([(f['owner'], f['mode'], f['alternative']) for f in facts],
                         [('连接器', '故障', True), ('导线', '故障', True)])
        self.assertEqual(unresolved, [])
        facts, unresolved = service._parse_component_reasons('发控信号接线断开')
        self.assertEqual([(f['owner'], f['mode'], f['alternative']) for f in facts],
                         [('发控信号接线', '断开', False)])
        for text in ('导线未断开', '可能导线断开', '原因不明', '检查连接器故障', '连接器故障和导线故障'):
            facts, unresolved = service._parse_component_reasons(text)
            self.assertEqual(facts, [], text)
            self.assertTrue(unresolved, text)
        facts, unresolved = service._parse_component_reasons('连接器故障或原因待确认')
        self.assertEqual(len(facts), 1)
        self.assertTrue(facts[0]['alternative'])
        self.assertEqual(unresolved, ['原因待确认'])

    def test_candidate_semantics_survive_both_export_paths(self):
        graph = service._collect_table_graph([{
            'machine_name': '电缆网', 'unit_failure_mode': '短路',
            'component_reason_raw': '连接器故障或导线故障'}])
        fault_edges = [r for r in graph['tripleRows'] if r['subjectType'] == service.COMPONENT_FAULT]
        self.assertEqual({r['predicate'] for r in fault_edges}, {'可能导致'})
        self.assertEqual({r['subject'] for r in fault_edges}, {'故障'})
        payloads = [service._build_structured_triple_definition(graph, 'test.csv', {}, 1, 1, 1),
                    normalize_extraction_result_to_triple_payload({'sourceType': 'table', **graph})]
        for payload in payloads:
            relation_names = {r['id']: r['name'] for r in payload['relations']}
            self.assertEqual(sum(relation_names[t['predicate_id']] == '候选项' for t in payload['triples']), 2)
            self.assertIn('候选原因（或）', relation_names.values())
            self.assertNotIn('导致', relation_names.values())
            self.assertTrue(any(e['name'] == '连接器故障或导线故障' and e['type'] == '故障原因组' for e in payload['entities']))

    def test_component_identifiers_and_grouped_names(self):
        text = '1:敏感元件N1：失效 2:电容C13、C14、C15、C16 ：开路 (共2个故障原因）'
        self.assertEqual(service._split_prefixed_pairs(text), [
            ('敏感元件N1', '失效'), ('电容C13、C14、C15、C16', '开路')])
        self.assertEqual(service._split_prefixed_pairs('1.电阻R6：开路'), [('电阻R6', '开路')])

    def test_partial_cell_is_reported_and_known_facts_survive(self):
        record = {key: '' for key in PARSER['REQUIRED_HEADERS']}
        record.update({'系统树节点': '电缆网', '故障模式名称': '短路',
                       '故障原因': '连接器：短路；原因待确认', '功能': '信号传输',
                       '高一层级影响': '测控系统：采集异常', '最终影响': '推迟发射'})
        record = PARSER['SourceRecord'](record, row_number=27)
        rows = PARSER['serialize_rows'](PARSER['build_graph_rows']([record], preserve_partial=True))
        rows = list({row['row_number']: row for row in rows}.values())
        graph = service._collect_table_graph(rows)
        self.assertIn(('电缆网', '存在故障', '短路'), [(r['subject'], r['predicate'], r['object']) for r in graph['tripleRows']])
        report = service._build_row_report([record], rows, None)
        self.assertEqual(report['retainedRows'], 1)
        self.assertEqual(report['rows'][0]['rowNumber'], 27)
        self.assertEqual(report['rows'][0]['omissions'][0]['rawText'], '连接器：短路；原因待确认')

    def test_standalone_machine_survives_export_and_normalization(self):
        graph = service._collect_table_graph([{'machine_name': '电缆网'}])
        payload = normalize_extraction_result_to_triple_payload({'sourceType': 'table', **graph})
        exported = service._build_structured_triple_definition(graph, 'test.csv', {}, 1, 1, 1)
        self.assertEqual([e['name'] for e in payload['entities']], ['电缆网'])
        self.assertEqual([e['name'] for e in exported['entities']], ['电缆网'])

    def test_source_row_numbers_survive_sparse_sheet(self):
        header = PARSER['SourceRecord']({'A': '系统树节点', 'B': '故障模式'}, row_number=1)
        row = PARSER['SourceRecord']({'A': '电缆网', 'B': '短路'}, row_number=27)
        records = PARSER['rows_to_records']([header, row], True, False)
        self.assertEqual(records[0].row_number, 27)
        self.assertEqual(records[0]['故障模式名称'], '短路')

    def test_real_workbook_retains_all_rows_and_exports_report(self):
        source = ROOT / '动力测控电缆网故障分析.xlsx'
        if not source.exists():
            self.skipTest('Local FMEA fixture is unavailable')
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(service, 'TRIPLE_EXPORT_DIR', Path(directory)), patch.object(service, 'PROJECT_ROOT', Path(directory)):
                result = service.get_table_extraction_result(source.name, source.read_bytes())
            report = result['rowReport']
            self.assertEqual((report['inputRows'], report['retainedRows'], report['skippedRows']), (59, 59, 0))
            self.assertEqual(report['issueRows'], 0)
            machines = {e['name'] for e in result['entities'] if e['type'] == '单机'}
            self.assertEqual(len(machines), 5)
            self.assertIn('助推CZ7-9-4/14振动传感器', machines)
            self.assertIn('动力测控地面电缆网', machines)
            exported = json.loads((Path(directory) / result['tripleJsonPath']).read_text(encoding='utf-8'))
            self.assertEqual(exported['rowReport'], report)
            payload = normalize_extraction_result_to_triple_payload(result)
            self.assertEqual({e['name'] for e in payload['entities'] if e['type'] == '单机'}, machines)


if __name__ == '__main__':
    unittest.main()
