from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest
import yaml

from cognite_toolkit.cdf_tk.templates import (
    check_yaml_semantics,
    create_local_config,
    flatten_dict,
    split_config,
)
from cognite_toolkit.cdf_tk.templates.data_classes import InitConfigYAML, YAMLComment

PYTEST_PROJECT = Path(__file__).parent / "project_for_test"


def dict_keys(d: dict[str, Any]) -> set[str]:
    keys = set()
    for k, v in d.items():
        keys.add(k)
        if isinstance(v, dict):
            keys.update(dict_keys(v))
    return keys


@pytest.fixture(scope="session")
def config_yaml() -> str:
    return (PYTEST_PROJECT / "config.dev.yaml").read_text()


class TestConfigYAML:
    def test_producing_correct_keys(self, config_yaml: str) -> None:
        expected_keys = set(flatten_dict(yaml.safe_load(config_yaml)))
        # Custom keys are not loaded from the module folder.
        # This custom key is added o the dev.config.yaml for other tests.
        expected_keys.remove(("modules", "custom_modules", "my_example_module", "transformation_is_paused"))
        # Skip all environment variables
        expected_keys = {k for k in expected_keys if not k[0] == "environment"}

        config = InitConfigYAML().load_defaults(PYTEST_PROJECT)

        actual_keys = set(config.keys())
        missing = expected_keys - actual_keys
        assert not missing, f"Missing keys: {missing}"
        extra = actual_keys - expected_keys
        assert not extra, f"Extra keys: {extra}"

    def test_extract_extract_config_yaml_comments(self, config_yaml: str) -> None:
        expected_comments = {
            ("modules", "cognite_modules", "a_module", "readonly_source_id"): YAMLComment(
                above=["This is a comment in the middle of the file"], after=[]
            ),
            ("modules", "cognite_modules", "another_module", "default_location"): YAMLComment(
                above=["This is a comment at the beginning of the module."]
            ),
            ("modules", "cognite_modules", "another_module", "source_asset"): YAMLComment(
                after=["This is an extra comment added to the config only 'lore ipsum'"]
            ),
            ("modules", "cognite_modules", "another_module", "source_files"): YAMLComment(
                after=["This is a comment after a variable"]
            ),
        }

        actual_comments = InitConfigYAML._extract_comments(config_yaml)

        assert actual_comments == expected_comments

    @pytest.mark.parametrize(
        "raw_file, key_prefix, expected_comments",
        [
            pytest.param(
                """---
# This is a module comment
variable: value # After variable comment
# Before variable comment
variable2: value2
variable3: 'value with #in it'
variable4: "value with #in it" # But a comment after
""",
                tuple("super_module.module_a".split(".")),
                {
                    ("super_module", "module_a", "variable"): YAMLComment(
                        after=["After variable comment"], above=["This is a module comment"]
                    ),
                    ("super_module", "module_a", "variable2"): YAMLComment(above=["Before variable comment"]),
                    ("super_module", "module_a", "variable4"): YAMLComment(after=["But a comment after"]),
                },
                id="module comments",
            )
        ],
    )
    def test_extract_default_config_comments(
        self, raw_file: str, key_prefix: tuple[str, ...], expected_comments: dict[str, Any]
    ):
        actual_comments = InitConfigYAML._extract_comments(raw_file, key_prefix)
        assert actual_comments == expected_comments

    def test_persist_variable_with_comment(self, config_yaml: str) -> None:
        custom_comment = "This is an extra comment added to the config only 'lore ipsum'"

        config = InitConfigYAML().load_defaults(PYTEST_PROJECT).load_existing(config_yaml)

        dumped = config.dump_yaml_with_comments(active=(True, False))
        loaded = yaml.safe_load(dumped)
        assert loaded["modules"]["cognite_modules"]["another_module"]["source_asset"] == "my_new_workmate"
        assert custom_comment in dumped

    def test_added_and_removed_variables(self, config_yaml: str) -> None:
        existing_config_yaml = yaml.safe_load(config_yaml)
        # Added = Exists in the BUILD_CONFIG directory default.config.yaml files but not in config.yaml
        existing_config_yaml["modules"]["cognite_modules"]["another_module"].pop("source_asset")
        # Removed = Exists in config.yaml but not in the BUILD_CONFIG directory default.config.yaml files
        existing_config_yaml["modules"]["cognite_modules"]["another_module"]["removed_variable"] = "old_value"

        config = InitConfigYAML().load_defaults(PYTEST_PROJECT).load_existing(yaml.safe_dump(existing_config_yaml))

        removed = [v for v in config.values() if v.default_value is None]
        # There is already a custom variable in the config.yaml file
        assert len(removed) == 2
        assert ("modules", "cognite_modules", "another_module", "removed_variable") in [v.key_path for v in removed]

        added = [v for v in config.values() if v.current_value is None]
        assert len(added) == 1
        assert added[0].key_path == ("modules", "cognite_modules", "another_module", "source_asset")

    def test_load_variables(self) -> None:
        expected = {
            ("modules", "cognite_modules", "a_module", "readonly_source_id"),
            # default_location is used in two modules and is moved to the top level
            ("modules", "cognite_modules", "default_location"),
            ("modules", "cognite_modules", "another_module", "source_files"),
            ("modules", "cognite_modules", "parent_module", "child_module", "source_asset"),
        }

        config = InitConfigYAML().load_variables(PYTEST_PROJECT, propagate_reused_variables=True)

        missing = expected - set(config.keys())
        assert not missing, f"Missing keys: {missing}"
        extra = set(config.keys()) - expected
        assert not extra, f"Extra keys: {extra}"


@pytest.mark.parametrize(
    "input_, expected",
    [
        pytest.param({"a": {"b": 1, "c": 2}}, {("a", "b"): 1, ("a", "c"): 2}, id="Simple"),
        pytest.param({"a": {"b": {"c": 1}}}, {("a", "b", "c"): 1}, id="Nested"),
    ],
)
def test_flatten_dict(input_: dict[str, Any], expected: dict[str, Any]) -> None:
    actual = flatten_dict(input_)

    assert actual == expected


@pytest.fixture()
def my_config():
    return {
        "top_variable": "my_top_variable",
        "module_a": {
            "readwrite_source_id": "my_readwrite_source_id",
            "readonly_source_id": "my_readonly_source_id",
        },
        "parent": {"child": {"child_variable": "my_child_variable"}},
    }


def test_split_config(my_config: dict[str, Any]) -> None:
    expected = {
        "": {"top_variable": "my_top_variable"},
        "module_a": {
            "readwrite_source_id": "my_readwrite_source_id",
            "readonly_source_id": "my_readonly_source_id",
        },
        "parent.child": {"child_variable": "my_child_variable"},
    }
    actual = split_config(my_config)

    assert actual == expected


def test_create_local_config(my_config: dict[str, Any]):
    configs = split_config(my_config)

    local_config = create_local_config(configs, Path("parent/child/auth/"))

    assert dict(local_config.items()) == {"top_variable": "my_top_variable", "child_variable": "my_child_variable"}


def valid_yaml_semantics_test_cases() -> Iterable[pytest.ParameterSet]:
    yield pytest.param(
        yaml.safe_load(
            """
- dbName: src:005:test:rawdb:state
- dbName: src:002:weather:rawdb:state
- dbName: uc:001:demand:rawdb:state
- dbName: in:all:rawdb:state
- dbName: src:001:sap:rawdb
"""
        ),
        Path("build/raw/raw.yaml"),
        id="Multiple Raw Databases",
    )

    yield pytest.param(
        yaml.safe_load(
            """
dbName: src:005:test:rawdb:state
"""
        ),
        Path("build/raw/raw.yaml"),
        id="Single Raw Database",
    )

    yield pytest.param(
        yaml.safe_load(
            """
dbName: src:005:test:rawdb:state
tableName: myTable
"""
        ),
        Path("build/raw/raw.yaml"),
        id="Single Raw Database with table",
    )

    yield pytest.param(
        yaml.safe_load(
            """
- dbName: src:005:test:rawdb:state
  tableName: myTable
- dbName: src:002:weather:rawdb:state
  tableName: myOtherTable
"""
        ),
        Path("build/raw/raw.yaml"),
        id="Multiple Raw Databases with table",
    )


class TestCheckYamlSemantics:
    @pytest.mark.parametrize("raw_yaml, source_path", list(valid_yaml_semantics_test_cases()))
    def test_valid_yaml(self, raw_yaml: dict | list, source_path: Path):
        # The build path is unused in the function
        # not sure why it is there
        build_path = Path("does_not_matter")
        assert check_yaml_semantics(raw_yaml, source_path, build_path)
