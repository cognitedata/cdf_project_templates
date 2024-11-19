from __future__ import annotations

from pathlib import Path

import yaml

from cognite_toolkit._cdf_tk.data_classes import BuildVariables, ModuleLocation


class TestBuildVariables:
    def test_replace_preserve_data_type(self) -> None:
        source_yaml = """text: {{ my_text }}
bool: {{ my_bool }}
integer: {{ my_integer }}
float: {{ my_float }}
digit_string: {{ my_digit_string }}
quoted_string: "{{ my_quoted_string }}"
list: {{ my_list }}
null_value: {{ my_null_value }}
single_quoted_string: '{{ my_single_quoted_string }}'
composite: 'some_prefix_{{ my_composite }}'
prefix_text: {{ my_prefix_text }}
suffix_text: {{ my_suffix_text }}
"""
        variables = BuildVariables.load_raw(
            {
                "my_text": "some text",
                "my_bool": True,
                "my_integer": 123,
                "my_float": 123.456,
                "my_digit_string": "123",
                "my_quoted_string": "456",
                "my_list": ["one", "two", "three"],
                "my_null_value": None,
                "my_single_quoted_string": "789",
                "my_composite": "the suffix",
                "my_prefix_text": "prefix:",
                "my_suffix_text": ":suffix",
            },
            available_modules=set(),
            selected_modules=set(),
        )

        result = variables.replace(source_yaml)

        loaded = yaml.safe_load(result)
        assert loaded == {
            "text": "some text",
            "bool": True,
            "integer": 123,
            "float": 123.456,
            "digit_string": "123",
            "quoted_string": "456",
            "list": ["one", "two", "three"],
            "null_value": None,
            "single_quoted_string": "789",
            "composite": "some_prefix_the suffix",
            "prefix_text": "prefix:",
            "suffix_text": ":suffix",
        }

    def test_replace_not_preserve_type(self) -> None:
        source_yaml = """dataset_id('{{dataset_external_id}}')"""
        variables = BuildVariables.load_raw(
            {
                "dataset_external_id": "ds_external_id",
            },
            available_modules=set(),
            selected_modules=set(),
        )

        result = variables.replace(source_yaml, file_suffix=".sql")

        assert result == "dataset_id('ds_external_id')"

    def test_get_module_variables_variable_preference_order(self) -> None:
        source_yaml = """
modules:
  industry_apps:
      module_version: '1'
      pause_transformations: true
      apm_datamodel_space: APM_SourceData
      apm_sourcedata_model_version: '1.2.1'

      industry_apps_crna_common:
        apm_sourcedata_model_version: '1'
"""
        selected = {
            Path("."),
            Path("modules"),
            Path("modules/industry_apps"),
            Path("modules/industry_apps/industry_apps_crna_common"),
        }

        variables = BuildVariables.load_raw(
            yaml.safe_load(source_yaml), available_modules=selected, selected_modules=selected
        )

        assert len(variables) == 5
        location = ModuleLocation(
            Path("modules/industry_apps/industry_apps_crna_common"), Path("."), source_paths=[], is_selected=True
        )
        local_variables = variables.get_module_variables(location)

        assert len(local_variables) == 4
        apm_sourcedata_model_version = next(
            (variable for variable in local_variables if variable.key == "apm_sourcedata_model_version"), None
        )
        assert apm_sourcedata_model_version.value == "1"
