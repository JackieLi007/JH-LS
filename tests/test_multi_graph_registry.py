from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import sys


try:
    import flask  # noqa: F401
except ModuleNotFoundError:
    flask_stub = ModuleType("flask")
    flask_stub.g = SimpleNamespace()
    flask_stub.has_request_context = lambda: False
    flask_stub.request = SimpleNamespace()
    sys.modules["flask"] = flask_stub

try:
    import neo4j  # noqa: F401
except ModuleNotFoundError:
    neo4j_stub = ModuleType("neo4j")
    neo4j_stub.GraphDatabase = SimpleNamespace(driver=None)
    sys.modules["neo4j"] = neo4j_stub

from backend import graph_registry
from backend.kg_pipeline_service import list_kg_versions
from kg_tool.versioning import record_triple_version


class _FakeResult:
    def consume(self) -> None:
        return None


class _FakeSession:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def __enter__(self) -> "_FakeSession":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def run(self, statement: str) -> _FakeResult:
        self.statements.append(statement)
        return _FakeResult()


class _FakeDriver:
    def __init__(self) -> None:
        self.session_instance = _FakeSession()

    def session(self, **_kwargs: object) -> _FakeSession:
        return self.session_instance

    def close(self) -> None:
        return None


class MultiGraphRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.root_patch = patch.object(graph_registry, "GRAPH_ARTIFACT_ROOT", self.root)
        self.registry_patch = patch.object(graph_registry, "GRAPH_REGISTRY_PATH", self.root / "registry.json")
        self.root_patch.start()
        self.registry_patch.start()

    def tearDown(self) -> None:
        self.registry_patch.stop()
        self.root_patch.stop()
        self.temp_dir.cleanup()

    def test_default_graph_and_request_selection_are_isolated(self) -> None:
        default = graph_registry.default_graph()
        self.assertEqual(default["database"], graph_registry.configured_default_database())

        created = self._create_graph("CZ-8A 型号")
        with (
            patch.object(graph_registry, "has_request_context", return_value=True),
            patch.object(graph_registry, "_request_graph_reference", return_value=created["database"]),
            patch.object(graph_registry, "g", SimpleNamespace()),
        ):
            selected = graph_registry.select_request_graph()
            self.assertEqual(selected["database"], created["database"])
            self.assertEqual(graph_registry.request_graph_database(), created["database"])

        self.assertNotEqual(default["database"], created["database"])
        self.assertEqual(len(graph_registry.list_registered_graphs()), 2)

    def test_versions_use_a_separate_history_file_for_each_graph(self) -> None:
        first = self._create_graph("CZ-8A 型号")
        second = self._create_graph("CZ-12 型号")
        for index in range(11):
            record_triple_version(
                {"fileName": f"cz8-{index}.xlsx", "entities": [], "relations": [], "triples": []},
                {"created_nodes": 1},
                history_path=graph_registry.graph_version_history_path(first["database"]),
            )

        first_versions = list_kg_versions(graph_database=first["database"])["versions"]
        second_versions = list_kg_versions(graph_database=second["database"])["versions"]
        self.assertEqual(len(first_versions), 10)
        self.assertEqual(first_versions[0]["fileName"], "cz8-10.xlsx")
        self.assertEqual(second_versions, [])
        self.assertNotEqual(
            graph_registry.graph_version_history_path(first["database"]),
            graph_registry.graph_version_history_path(second["database"]),
        )

    def test_deleting_user_graph_drops_database_and_graph_artifacts(self) -> None:
        created = self._create_graph("CZ-8A")
        artifact_dir = graph_registry.graph_artifact_dir(created["database"])
        artifact_dir.mkdir(parents=True)
        (artifact_dir / "history.json").write_text("{}", encoding="utf-8")

        fake_driver = _FakeDriver()
        with patch.object(graph_registry.GraphDatabase, "driver", return_value=fake_driver):
            deleted = graph_registry.delete_registered_graph(created["database"])

        self.assertEqual(deleted["database"], created["database"])
        self.assertFalse(artifact_dir.exists())
        self.assertTrue(any("DROP DATABASE" in statement for statement in fake_driver.session_instance.statements))
        self.assertEqual(len(graph_registry.list_registered_graphs()), 1)

    def test_default_graph_cannot_be_deleted(self) -> None:
        with self.assertRaises(graph_registry.GraphRegistryError):
            graph_registry.delete_registered_graph(graph_registry.default_graph()["database"])

    def _create_graph(self, name: str) -> dict[str, object]:
        fake_driver = _FakeDriver()
        with patch.object(graph_registry.GraphDatabase, "driver", return_value=fake_driver):
            graph = graph_registry.create_registered_graph(name)
        self.assertTrue(any("CREATE DATABASE" in statement for statement in fake_driver.session_instance.statements))
        return graph


if __name__ == "__main__":
    unittest.main()
