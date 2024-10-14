"""
Approval test takes a snapshot of the results and then compare them to last run, ref https://approvaltests.com/,
and fails if they have changed.

If the changes are desired, you can update the snapshot by running `pytest tests/ --force-regen`.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path

import pytest
import typer
from pytest import MonkeyPatch

from cognite_toolkit._cdf_tk.apps import CoreApp
from cognite_toolkit._cdf_tk.commands import BuildCommand
from cognite_toolkit._cdf_tk.constants import BUILTIN_MODULES_PATH
from cognite_toolkit._cdf_tk.data_classes import ModuleDirectories
from cognite_toolkit._cdf_tk.loaders import LOADER_BY_FOLDER_NAME, Loader
from cognite_toolkit._cdf_tk.utils import CDFToolConfig, humanize_collection, iterate_modules
from tests.data import COMPLETE_ORG
from tests.test_unit.approval_client import ApprovalToolkitClient
from tests.test_unit.utils import mock_read_yaml_file

THIS_DIR = Path(__file__).resolve().parent
SNAPSHOTS_DIR = THIS_DIR / "test_build_deploy_snapshots"
SNAPSHOTS_DIR.mkdir(exist_ok=True)
SNAPSHOTS_DIR_CLEAN = THIS_DIR / "test_build_clean_snapshots"
SNAPSHOTS_DIR_CLEAN.mkdir(exist_ok=True)


def find_all_modules() -> Iterator[Path]:
    for module, _ in iterate_modules(BUILTIN_MODULES_PATH):
        if module.name == "references":  # this particular module should never be built or deployed
            continue
        yield pytest.param(module, id=f"{module.parent.name}/{module.name}")


def mock_environments_yaml_file(module_path: Path, monkeypatch: MonkeyPatch) -> None:
    return mock_read_yaml_file(
        {
            "config.dev.yaml": {
                "environment": {
                    "name": "dev",
                    "project": "pytest-project",
                    "type": "dev",
                    "selected": [module_path.name],
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
    toolkit_client_approval: ApprovalToolkitClient,
    cdf_tool_mock: CDFToolConfig,
    typer_context: typer.Context,
    organization_dir: Path,
    data_regression,
) -> None:
    app = CoreApp()

    cmd = BuildCommand(skip_tracking=True, silent=True)
    cmd.execute(
        verbose=False,
        organization_dir=organization_dir,
        build_dir=build_tmp_path,
        selected=[module_path.name],
        build_env_name="dev",
        no_clean=False,
        ToolGlobals=cdf_tool_mock,
        on_error="raise",
    )

    app.deploy(
        typer_context,
        build_dir=build_tmp_path,
        build_env_name="dev",
        drop=True,
        dry_run=False,
        include=[],
    )

    not_mocked = toolkit_client_approval.not_mocked_calls()
    assert not not_mocked, (
        f"The following APIs have been called without being mocked: {not_mocked}, "
        "Please update the list _API_RESOURCES in tests/approval_client.py"
    )

    dump = toolkit_client_approval.dump()
    data_regression.check(dump, fullpath=SNAPSHOTS_DIR / f"{module_path.name}.yaml")

    for group_calls in toolkit_client_approval.auth_create_group_calls():
        lost_capabilities = group_calls.capabilities_all_calls - group_calls.last_created_capabilities
        assert (
            not lost_capabilities
        ), f"The group {group_calls.name!r} has lost the capabilities: {', '.join(lost_capabilities)}"


@pytest.mark.parametrize("module_path", list(find_all_modules()))
def test_build_deploy_with_dry_run(
    module_path: Path,
    build_tmp_path: Path,
    monkeypatch: MonkeyPatch,
    toolkit_client_approval: ApprovalToolkitClient,
    cdf_tool_mock: CDFToolConfig,
    typer_context: typer.Context,
    organization_dir: Path,
) -> None:
    mock_environments_yaml_file(module_path, monkeypatch)

    app = CoreApp()
    app.build(
        typer_context,
        organization_dir=organization_dir,
        build_dir=build_tmp_path,
        selected=None,
        build_env_name="dev",
        no_clean=False,
    )
    app.deploy(
        typer_context,
        build_dir=build_tmp_path,
        build_env_name="dev",
        drop=True,
        dry_run=True,
        include=[],
    )

    create_result = toolkit_client_approval.create_calls()
    assert not create_result, f"No resources should be created in dry run: got these calls: {create_result}"
    delete_result = toolkit_client_approval.delete_calls()
    assert not delete_result, f"No resources should be deleted in dry run: got these calls: {delete_result}"


@pytest.mark.parametrize("module_path", list(find_all_modules()))
def test_init_build_clean(
    module_path: Path,
    build_tmp_path: Path,
    monkeypatch: MonkeyPatch,
    toolkit_client_approval: ApprovalToolkitClient,
    cdf_tool_mock: CDFToolConfig,
    typer_context: typer.Context,
    organization_dir: Path,
    data_regression,
) -> None:
    mock_environments_yaml_file(module_path, monkeypatch)

    app = CoreApp()
    app.build(
        typer_context,
        organization_dir=organization_dir,
        build_dir=build_tmp_path,
        selected=None,
        build_env_name="dev",
        no_clean=False,
    )
    app.clean(
        typer_context,
        build_dir=build_tmp_path,
        build_env_name="dev",
        dry_run=False,
        include=[],
    )

    not_mocked = toolkit_client_approval.not_mocked_calls()
    assert not not_mocked, (
        f"The following APIs have been called without being mocked: {not_mocked}, "
        "Please update the list _API_RESOURCES in tests/approval_client.py"
    )
    dump = toolkit_client_approval.dump()
    data_regression.check(dump, fullpath=SNAPSHOTS_DIR_CLEAN / f"{module_path.name}.yaml")


def test_build_deploy_complete_org(
    build_tmp_path: Path,
    monkeypatch: MonkeyPatch,
    toolkit_client_approval: ApprovalToolkitClient,
    cdf_tool_mock: CDFToolConfig,
    typer_context: typer.Context,
    data_regression,
) -> None:
    app = CoreApp()
    app.build(
        typer_context,
        organization_dir=COMPLETE_ORG,
        build_dir=build_tmp_path,
        selected=None,
        build_env_name="dev",
        no_clean=False,
    )
    app.deploy(
        typer_context,
        build_dir=build_tmp_path,
        build_env_name="dev",
        drop=True,
        dry_run=False,
        include=[],
    )

    not_mocked = toolkit_client_approval.not_mocked_calls()
    assert not not_mocked, (
        f"The following APIs have been called without being mocked: {not_mocked}, "
        "Please update the list _API_RESOURCES in tests/approval_client.py"
    )

    dump = toolkit_client_approval.dump()
    data_regression.check(dump, fullpath=SNAPSHOTS_DIR / f"{COMPLETE_ORG.name}.yaml")

    for group_calls in toolkit_client_approval.auth_create_group_calls():
        lost_capabilities = group_calls.capabilities_all_calls - group_calls.last_created_capabilities
        assert (
            not lost_capabilities
        ), f"The group {group_calls.name!r} has lost the capabilities: {', '.join(lost_capabilities)}"


def test_complete_org_is_complete() -> None:
    modules = ModuleDirectories.load(COMPLETE_ORG)
    used_loader_by_folder_name: dict[str, set[type[Loader]]] = defaultdict(set)

    for module in modules:
        for resource_folder, files in module.source_paths_by_resource_folder.items():
            for loader in LOADER_BY_FOLDER_NAME[resource_folder]:
                if any(loader.is_supported_file(file) for file in files):
                    used_loader_by_folder_name[resource_folder].add(loader)

    unused_loaders = {
        loader
        for folder, loaders in LOADER_BY_FOLDER_NAME.items()
        for loader in loaders
        if loader not in used_loader_by_folder_name[folder]
    }

    # If this assertion fails, it means that the complete_org is not complete.
    # This typically happens when you have just added a new loader and forgotten to add
    # example data for the new resource type in the tests/data/complete_org.
    assert not unused_loaders, f"The following {len(unused_loaders)} loaders are not used: {humanize_collection([loader.__name__ for loader in unused_loaders])}"
