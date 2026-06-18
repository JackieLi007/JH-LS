from __future__ import annotations

import json
from typing import Any

from flask import Flask, jsonify, request

from backend.demo_data import (
    get_entity_relation_schema,
    get_extraction_result,
    get_parse_configuration,
)
from backend.document_extract_service import (
    get_document_extraction_result,
    get_document_parse_configuration,
)
from backend.image_extract_service import (
    get_image_extraction_result,
    get_image_parse_configuration,
)
from backend.kg_pipeline_service import (
    build_kg_from_extraction_result_safe,
    kg_auto_build_enabled,
    list_kg_versions,
    rollback_latest_kg_version,
)
from backend.table_extract_service import (
    get_table_extraction_result,
    get_table_parse_configuration,
)


def register_fknow_routes(app: Flask) -> None:
    """Register the knowledge extraction routes from the fknow backend."""

    def with_kg_build(result: dict[str, Any]) -> dict[str, Any]:
        if not kg_auto_build_enabled():
            return result
        if str(result.get('sourceType') or '').strip().lower() not in {'table', 'document'}:
            return result
        enriched = dict(result)
        enriched['kgBuild'] = build_kg_from_extraction_result_safe(enriched)
        return enriched

    @app.get('/api/schema')
    def fknow_schema() -> Any:
        return jsonify(get_entity_relation_schema())

    @app.route('/api/parse-preview', methods=['POST', 'OPTIONS'])
    def fknow_parse_preview() -> Any:
        if request.method == 'OPTIONS':
            return ('', 204)

        if request.content_type and 'multipart/form-data' in request.content_type:
            source_type = request.form.get('sourceType', 'document')
            primary_file = request.files.get('file')
            extra_file = request.files.get('extraFile')
            if primary_file is None or not primary_file.filename:
                return jsonify({'error': '缺少上传文件。'}), 400

            if source_type == 'document':
                try:
                    return jsonify(get_document_parse_configuration(primary_file.filename, primary_file.read()))
                except Exception as exc:
                    return jsonify({'error': str(exc)}), 400

            if source_type == 'image':
                try:
                    return jsonify(get_image_parse_configuration(primary_file.filename, primary_file.read()))
                except Exception as exc:
                    return jsonify({'error': str(exc)}), 400

            if source_type == 'table':
                try:
                    return jsonify(
                        get_table_parse_configuration(
                            primary_file.filename,
                            primary_file.read(),
                            extra_file.filename if extra_file and extra_file.filename else None,
                            extra_file.read() if extra_file and extra_file.filename else None,
                        )
                    )
                except Exception as exc:
                    return jsonify({'error': str(exc)}), 400

        payload = request.get_json(silent=True) or {}
        source_type = payload.get('sourceType', 'document')
        file_name = payload.get('fileName', '')
        return jsonify(get_parse_configuration(source_type, file_name))

    @app.route('/api/extract', methods=['POST', 'OPTIONS'])
    def fknow_extract() -> Any:
        if request.method == 'OPTIONS':
            return ('', 204)

        if request.content_type and 'multipart/form-data' in request.content_type:
            source_type = request.form.get('sourceType', 'document')
            primary_file = request.files.get('file')
            extra_file = request.files.get('extraFile')
            mappings_raw = request.form.get('mappings', '[]')
            ontology_raw = request.form.get('ontology', '{}')
            if primary_file is None or not primary_file.filename:
                return jsonify({'error': '缺少上传文件。'}), 400

            if source_type == 'document':
                try:
                    ontology = json.loads(ontology_raw) if ontology_raw.strip() else None
                    result = get_document_extraction_result(primary_file.filename, primary_file.read(), ontology)
                    return jsonify(with_kg_build(result))
                except Exception as exc:
                    return jsonify({'error': str(exc)}), 400

            if source_type == 'image':
                try:
                    result = get_image_extraction_result(primary_file.filename, primary_file.read())
                    return jsonify(with_kg_build(result))
                except Exception as exc:
                    return jsonify({'error': str(exc)}), 400

            if source_type == 'table':
                try:
                    result = get_table_extraction_result(
                        primary_file.filename,
                        primary_file.read(),
                        json.loads(mappings_raw),
                        extra_file.filename if extra_file and extra_file.filename else None,
                        extra_file.read() if extra_file and extra_file.filename else None,
                    )
                    return jsonify(with_kg_build(result))
                except Exception as exc:
                    return jsonify({'error': str(exc)}), 400

        payload = request.get_json(silent=True) or {}
        source_type = payload.get('sourceType', 'document')
        file_name = payload.get('fileName', '')
        mappings = payload.get('mappings', [])
        return jsonify(with_kg_build(get_extraction_result(source_type, file_name, mappings)))

    @app.route('/api/kg/build', methods=['POST', 'OPTIONS'])
    def fknow_kg_build() -> Any:
        if request.method == 'OPTIONS':
            return ('', 204)

        payload = request.get_json(silent=True) or {}
        extraction_result = payload.get('extractionResult') if isinstance(payload.get('extractionResult'), dict) else payload
        result = build_kg_from_extraction_result_safe(
            extraction_result,
            neo4j_overrides=payload.get('neo4j') if isinstance(payload.get('neo4j'), dict) else None,
            record_version=payload.get('recordVersion', True),
        )
        status = 200 if result.get('status') in {'ok', 'skipped'} else 500
        return jsonify(result), status

    @app.get('/api/kg/versions')
    def fknow_kg_versions() -> Any:
        try:
            limit = int(request.args.get('limit', 10))
        except (TypeError, ValueError):
            limit = 10
        return jsonify(list_kg_versions(max(1, min(limit, 10))))

    @app.route('/api/kg/rollback', methods=['POST', 'OPTIONS'])
    def fknow_kg_rollback() -> Any:
        if request.method == 'OPTIONS':
            return ('', 204)

        try:
            return jsonify(rollback_latest_kg_version())
        except Exception as exc:
            return jsonify({'status': 'failed', 'error': str(exc)}), 500
