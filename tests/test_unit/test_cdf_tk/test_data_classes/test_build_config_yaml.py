from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from cognite_toolkit._cdf_tk.commands import BuildCommand
from cognite_toolkit._cdf_tk.data_classes import BuildConfigYAML, Environment, SystemYAML
from cognite_toolkit._cdf_tk.loaders import LOADER_BY_FOLDER_NAME
from cognite_toolkit._cdf_tk.utils import iterate_modules
from tests.data import PYTEST_PROJECT
from tests.tests_unit.test_cdf_tk.constants import BUILD_DIR


class TestBuildConfigYAML:
    def test_build_config_create_valid_build_folder(self, config_yaml: str) -> None:
        build_env_name = "dev"
        system_config = SystemYAML.load_from_directory(PYTEST_PROJECT, build_env_name)
        config = BuildConfigYAML.load_from_directory(PYTEST_PROJECT, build_env_name)
        available_modules = {module.name for module, _ in iterate_modules(PYTEST_PROJECT)}
        config.environment.selected = list(available_modules)

        BuildCommand().build_config(
            BUILD_DIR, PYTEST_PROJECT, config=config, system_config=system_config, clean=True, verbose=False
        )

        # The resulting build folder should only have subfolders that are matching the folder name
        # used by the loaders.
        invalid_resource_folders = [
            dir_.name for dir_ in BUILD_DIR.iterdir() if dir_.is_dir() and dir_.name not in LOADER_BY_FOLDER_NAME
        ]
        assert not invalid_resource_folders, f"Invalid resource folders after build: {invalid_resource_folders}"

    @pytest.mark.parametrize(
        "modules, expected_available_modules",
        [
            pytest.param({"another_module": {}}, ["another_module"], id="Single module"),
            pytest.param(
                {
                    "cognite_modules": {
                        "top_variable": "my_top_variable",
                        "a_module": {
                            "source_id": "123-456-789",
                        },
                        "parent_module": {
                            "parent_variable": "my_parent_variable",
                            "child_module": {
                                "dataset_external_id": "ds_my_dataset",
                            },
                        },
                        "module_without_variables": {},
                    }
                },
                ["a_module", "child_module", "module_without_variables"],
                id="Multiple nested modules",
            ),
        ],
    )
    def test_available_modules(
        self, modules: dict[str, Any], expected_available_modules: list[str], dummy_environment: Environment
    ) -> None:
        config = BuildConfigYAML(dummy_environment, filepath=Path("dummy"), variables=modules)

        assert sorted(config.available_modules) == sorted(expected_available_modules)
