from __future__ import annotations

import unittest

from backend.app import build_fault_chain_conclusion, build_query_display_graph


def node(node_id: str, name: str, label: str) -> dict:
    return {
        'id': node_id,
        'name': name,
        'label': label,
        'level': label,
        'type': 'fault' if '故障模式' in label else 'entity',
    }


def edge(source: str, relation: str, target: str) -> dict:
    return {
        'from': source,
        'to': target,
        'label': relation,
        'relationType': relation,
    }


class FaultQueryDisplayModesTest(unittest.TestCase):
    def test_entity_shows_all_direct_faults_without_expanding_chains(self) -> None:
        graph = {
            'nodes': [
                node('machine', '液氧阀', '单机'),
                node('fault-a', '打不开', '单机级故障模式'),
                node('fault-b', '泄漏', '单机级故障模式'),
                node('fault-c', '响应迟缓', '单机级故障模式'),
                node('effect', '压力下降', '系统级故障模式'),
                node('function', '流量调节', '单机功能'),
            ],
            'edges': [
                edge('machine', '存在故障', 'fault-a'),
                edge('machine', '存在故障', 'fault-b'),
                edge('machine', '存在故障', 'fault-c'),
                edge('fault-a', '导致', 'effect'),
                edge('machine', '具有功能', 'function'),
            ],
        }
        result = build_query_display_graph(graph, 'machine', '液氧阀')
        self.assertEqual(
            {item['id'] for item in result['nodes']},
            {'machine', 'fault-a', 'fault-b', 'fault-c'},
        )
        self.assertEqual(set(result['directFaultNodeIds']), {'fault-a', 'fault-b', 'fault-c'})
        self.assertNotIn('effect', {item['id'] for item in result['nodes']})
        self.assertNotIn('function', {item['id'] for item in result['nodes']})

    def test_fault_conclusion_lists_every_direct_cause(self) -> None:
        focus = node('fault', '打不开', '单机级故障模式')
        chain = {
            'nodes': [
                focus,
                node('cause-a', '阀芯卡滞', '组件级故障模式'),
                node('cause-b', '弹簧失效', '组件级故障模式'),
                node('effect', '压力下降', '系统级故障模式'),
            ],
            'edges': [
                edge('cause-a', '导致', 'fault'),
                edge('cause-b', '导致', 'fault'),
                edge('fault', '导致', 'effect'),
            ],
            'primaryFaultNodeId': 'fault',
            'primaryChainNodeIds': ['fault', 'effect'],
            'focusCauseNodeIds': ['cause-a', 'cause-b'],
        }
        conclusion = build_fault_chain_conclusion('打不开', focus, chain)['text']
        self.assertIn('“阀芯卡滞”', conclusion)
        self.assertIn('“弹簧失效”', conclusion)
        self.assertIn('等导致了“打不开”故障', conclusion)
        self.assertIn('后续可能导致“压力下降”', conclusion)


if __name__ == '__main__':
    unittest.main()
