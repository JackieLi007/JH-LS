from __future__ import annotations

import unittest

from backend.kg_pipeline_service import normalize_extraction_result_to_triple_payload
from backend.table_extract_service import _collect_table_graph, _split_prefixed_pairs


class TableFailureScopingTest(unittest.TestCase):
    def test_numbered_component_failures_drop_trailing_count_note(self) -> None:
        text = (
            '1.外管组件：结构破坏  2.主弹簧：疲劳破坏导致阀芯不能回位。'
            '3.密封圈：老化开裂。（共3种故障模式）'
        )
        self.assertEqual(
            _split_prefixed_pairs(text),
            [
                ('外管组件', '结构破坏'),
                ('主弹簧', '疲劳破坏导致阀芯不能回位'),
                ('密封圈', '老化开裂'),
            ],
        )

    def test_same_failure_name_is_scoped_to_its_owner(self) -> None:
        rows = [
            {
                'machine_name': '液氧阀',
                'unit_failure_mode': '打不开',
                'component_reason_raw': '',
                'system_effect_raw': '',
                'extra_columns': {},
            },
            {
                'machine_name': '密闭箱',
                'unit_failure_mode': '打不开',
                'component_reason_raw': '',
                'system_effect_raw': '',
                'extra_columns': {},
            },
        ]
        graph = _collect_table_graph(rows)
        payload = normalize_extraction_result_to_triple_payload({
            'fileName': 'test.xlsx',
            'sourceType': 'table',
            **graph,
        })
        failures = [item for item in payload['entities'] if item['type'] == '单机级故障模式']
        self.assertEqual([item['name'] for item in failures], ['打不开', '打不开'])
        self.assertEqual(len({item['id'] for item in failures}), 2)

    def test_legacy_first_component_does_not_duplicate_clean_numbered_name(self) -> None:
        graph = _collect_table_graph([{
            'machine_name': '二级贮箱传感器',
            'unit_failure_mode': '信号异常',
            'component_name': '1.外管组件',
            'component_failure_mode': '结构破坏  2.主弹簧：疲劳破坏导致阀芯不能回位',
            'component_reason_raw': (
                '1.外管组件：结构破坏  2.主弹簧：疲劳破坏导致阀芯不能回位。'
                '3.密封圈：老化开裂。（共3种故障模式）'
            ),
            'system_effect_raw': '',
            'extra_columns': {},
        }])
        component_names = {
            item['name'] for item in graph['entities'] if item['type'] == '零部组件'
        }
        self.assertEqual(component_names, {'外管组件', '主弹簧', '密封圈'})
        self.assertNotIn('1.外管组件', component_names)


if __name__ == '__main__':
    unittest.main()
