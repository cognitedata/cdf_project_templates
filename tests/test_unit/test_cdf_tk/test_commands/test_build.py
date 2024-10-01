from __future__ import annotations

from pathlib import Path

import pytest
from _pytest.monkeypatch import MonkeyPatch

from cognite_toolkit._cdf_tk.commands.build import BuildCommand
from cognite_toolkit._cdf_tk.data_classes import Environment
from cognite_toolkit._cdf_tk.exceptions import (
    ToolkitMissingModuleError,
)
from cognite_toolkit._cdf_tk.hints import ModuleDefinition
from cognite_toolkit._cdf_tk.loaders import TransformationLoader
from cognite_toolkit._cdf_tk.tk_warnings import LowSeverityWarning
from tests import data


@pytest.fixture(scope="session")
def dummy_environment() -> Environment:
    return Environment(
        name="dev",
        project="my_project",
        build_type="dev",
        selected=["none"],
    )


class TestBuildCommand:
    def test_module_not_found_error(self, tmp_path: Path) -> None:
        with pytest.raises(ToolkitMissingModuleError):
            BuildCommand(print_warning=False).execute(
                verbose=False,
                build_dir=tmp_path,
                organization_dir=data.PROJECT_WITH_BAD_MODULES,
                selected=None,
                build_env_name="no_module",
                no_clean=False,
            )

    def test_module_with_non_resource_directories(self, tmp_path: Path) -> None:
        cmd = BuildCommand(print_warning=False)
        cmd.execute(
            verbose=False,
            build_dir=tmp_path,
            organization_dir=data.PROJECT_WITH_BAD_MODULES,
            selected=None,
            build_env_name="ill_module",
            no_clean=False,
        )

        assert len(cmd.warning_list) >= 1
        assert (
            LowSeverityWarning(
                f"Module 'ill_made_module' has non-resource directories: ['spaces']. {ModuleDefinition.short()}"
            )
            in cmd.warning_list
        )

    def test_custom_project_no_warnings(self, tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
        cmd = BuildCommand(print_warning=False)
        monkeypatch.setenv("CDF_PROJECT", "some-project")
        cmd.execute(
            verbose=False,
            build_dir=tmp_path,
            organization_dir=data.PROJECT_NO_COGNITE_MODULES,
            selected=None,
            build_env_name="dev",
            no_clean=False,
        )

        assert not cmd.warning_list, f"No warnings should be raised. Got warnings: {cmd.warning_list}"
        # There are two transformations in the project, expect two transformation files
        transformation_files = [
            f
            for f in (tmp_path / "transformations").iterdir()
            if f.is_file() and TransformationLoader.is_supported_file(f)
        ]
        assert len(transformation_files) == 2
        sql_files = [f for f in (tmp_path / "transformations").iterdir() if f.is_file() and f.suffix == ".sql"]
        assert len(sql_files) == 2
