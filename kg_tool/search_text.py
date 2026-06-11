from __future__ import annotations

from typing import Any, Mapping


SYNONYM_GROUPS = (
    ('打不开', '无法打开', '不能打开', '开不了', '开启失效', '开启失败', '一次打不开'),
    ('泄漏', '渗漏', '外漏', '漏液', '漏油'),
    ('动力下降', '推力下降', '压力下降', '比冲过小', '无推力'),
    ('卡滞', '卡死', '卡住'),
)


def _text_values(value: Any) -> list[str]:
    values = value if isinstance(value, (list, tuple, set)) else [value]
    return [str(item).strip() for item in values if str(item or '').strip()]


def build_search_text(
    properties: Mapping[str, Any],
    node_type: str = '',
) -> str:
    values: list[str] = []
    for key in (
        'name', 'alias', 'aliases', 'type', 'description', 'rawText', 'raw_text',
        'owner', 'key', 'status', 'semantic_role',
    ):
        values.extend(_text_values(properties.get(key)))
    values.extend(_text_values(node_type))

    corpus = ' '.join(values).lower()
    for group in SYNONYM_GROUPS:
        if any(term.lower() in corpus for term in group):
            values.extend(group)

    return ' '.join(dict.fromkeys(value for value in values if value))
