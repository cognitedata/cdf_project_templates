"""
Approval test takes a snapshot of the results and then compare them to last run, ref https://approvaltests.com/,
and fails if they have changed.

If the changes are desired, you can update the snapshot by running `pytest tests/ --force-regen`.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
import typer
from pytest import MonkeyPatch

from cognite_toolkit._cdf import build, clean, deploy, main_init
from cognite_toolkit._cdf_tk.constants import COGNITE_MODULES
from cognite_toolkit._cdf_tk.utils import CDFToolConfig, iterate_modules
from tests.constants import REPO_ROOT
from tests.tests_unit.approval_client import ApprovalCogniteClient
from tests.tests_unit.utils import mock_read_yaml_file

THIS_DIR = Path(__file__).resolve().parent
SNAPSHOTS_DIR = THIS_DIR / "test_build_deploy_snapshots"
SNAPSHOTS_DIR.mkdir(exist_ok=True)
SNAPSHOTS_DIR_CLEAN = THIS_DIR / "test_build_clean_snapshots"
SNAPSHOTS_DIR_CLEAN.mkdir(exist_ok=True)


def find_all_modules() -> Iterator[Path]:
    for module, _ in iterate_modules(REPO_ROOT / "cognite_toolkit" / COGNITE_MODULES):
        yield pytest.param(module, id=f"{module.parent.name}/{module.name}")


def mock_environments_yaml_file(module_path: Path, monkeypatch: MonkeyPatch) -> None:
    return mock_read_yaml_file(
        {
            "config.dev.yaml": {
                "environment": {
                    "name": "dev",
                    "project": "pytest-project",
                    "type": "dev",
                    "selected_modules_and_packages": [module_path.name],
                }
            }
        },
        monkeypatch,
        modify=True,
    )


@pytest.mark.parametrize("module_path", list(find_all_modules()))
def test_build_deploy_module(
    module_path: Path,
    build_tmp_path: Path,
    monkeypatch: MonkeyPatch,
    cognite_client_approval: ApprovalCogniteClient,
    cdf_tool_config: CDFToolConfig,
    typer_context: typer.Context,
    init_project: Path,
    data_regression,
) -> None:
    mock_environments_yaml_file(module_path, monkeypatch)

    build(
        typer_context,
        source_dir=str(init_project),
        build_dir=str(build_tmp_path),
        build_env_name="dev",
        no_clean=False,
    )
    deploy(
        typer_context,
        build_dir=str(build_tmp_path),
        build_env_name="dev",
        interactive=False,
        drop=True,
        dry_run=False,
        include=[],
    )

    not_mocked = cognite_client_approval.not_mocked_calls()
    assert not not_mocked, (
        f"The following APIs have been called without being mocked: {not_mocked}, "
        "Please update the list _API_RESOURCES in tests/approval_client.py"
    )

    dump = cognite_client_approval.dump()
    data_regression.check(dump, fullpath=SNAPSHOTS_DIR / f"{module_path.name}.yaml")

    for group_calls in cognite_client_approval.auth_create_group_calls():
        lost_capabilities = group_calls.capabilities_all_calls - group_calls.last_created_capabilities
        assert (
            not lost_capabilities
        ), f"The group {group_calls.name!r} has lost the capabilities: {', '.join(lost_capabilities)}"


@pytest.mark.parametrize("module_path", list(find_all_modules()))
def test_build_deploy_with_dry_run(
    module_path: Path,
    build_tmp_path: Path,
    monkeypatch: MonkeyPatch,
    cognite_client_approval: ApprovalCogniteClient,
    cdf_tool_config: CDFToolConfig,
    typer_context: typer.Context,
    init_project: Path,
) -> None:
    mock_environments_yaml_file(module_path, monkeypatch)

    build(
        typer_context,
        source_dir=str(init_project),
        build_dir=str(build_tmp_path),
        build_env_name="dev",
        no_clean=False,
    )
    deploy(
        typer_context,
        build_dir=str(build_tmp_path),
        build_env_name="dev",
        interactive=False,
        drop=True,
        dry_run=True,
        include=[],
    )

    create_result = cognite_client_approval.create_calls()
    assert not create_result, f"No resources should be created in dry run: got these calls: {create_result}"
    delete_result = cognite_client_approval.delete_calls()
    assert not delete_result, f"No resources should be deleted in dry run: got these calls: {delete_result}"


@pytest.mark.parametrize("module_path", list(find_all_modules()))
def test_init_build_clean(
    module_path: Path,
    build_tmp_path: Path,
    local_tmp_project_path_immutable: Path,
    monkeypatch: MonkeyPatch,
    cognite_client_approval: ApprovalCogniteClient,
    cdf_tool_config: CDFToolConfig,
    typer_context: typer.Context,
    data_regression,
) -> None:
    mock_environments_yaml_file(module_path, monkeypatch)

    main_init(
        typer_context,
        dry_run=False,
        upgrade=False,
        git_branch=None,
        init_dir=str(local_tmp_project_path_immutable),
        no_backup=True,
        clean=True,
    )

    build(
        typer_context,
        source_dir=str(local_tmp_project_path_immutable),
        build_dir=str(build_tmp_path),
        build_env_name="dev",
        no_clean=False,
    )
    clean(
        typer_context,
        build_dir=str(build_tmp_path),
        build_env_name="dev",
        interactive=False,
        dry_run=False,
        include=[],
    )

    not_mocked = cognite_client_approval.not_mocked_calls()
    assert not not_mocked, (
        f"The following APIs have been called without being mocked: {not_mocked}, "
        "Please update the list _API_RESOURCES in tests/approval_client.py"
    )
    dump = cognite_client_approval.dump()
    data_regression.check(dump, fullpath=SNAPSHOTS_DIR_CLEAN / f"{module_path.name}.yaml")
