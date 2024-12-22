import os
import sys
from pathlib import Path
from typing import Any

import pytest
from cognite.client.data_classes.data_modeling import NodeId
from mypy.checkexpr import defaultdict

from cognite_toolkit._cdf_tk.commands import BuildCommand, DeployCommand, PullCommand
from cognite_toolkit._cdf_tk.data_classes import BuiltModuleList, ResourceDeployResult
from cognite_toolkit._cdf_tk.loaders import (
    LOADER_BY_FOLDER_NAME,
    RESOURCE_LOADER_LIST,
    HostedExtractorDestinationLoader,
    HostedExtractorSourceLoader,
    ResourceLoader,
    ResourceWorker,
)
from cognite_toolkit._cdf_tk.utils import CDFToolConfig
from cognite_toolkit._cdf_tk.utils.file import remove_trailing_newline
from tests import data


@pytest.mark.skipif(
    sys.version_info < (3, 11), reason="We only run this test on Python 3.11+ to avoid parallelism issues"
)
def test_deploy_complete_org(cdf_tool_config: CDFToolConfig, build_dir: Path) -> None:
    build = BuildCommand(silent=True, skip_tracking=True)

    built_modules = build.execute(
        verbose=False,
        organization_dir=data.COMPLETE_ORG,
        build_dir=build_dir,
        build_env_name="dev",
        no_clean=False,
        selected=None,
        ToolGlobals=cdf_tool_config,
    )

    deploy_command = DeployCommand(silent=False, skip_tracking=True)
    cdf_tool_config._environ["EVENTHUB_CLIENT_ID"] = os.environ["IDP_CLIENT_ID"]
    cdf_tool_config._environ["EVENTHUB_CLIENT_SECRET"] = os.environ["IDP_CLIENT_SECRET"]

    deploy_command.execute(
        cdf_tool_config,
        build_dir=build_dir,
        build_env_name="dev",
        dry_run=False,
        drop=False,
        drop_data=False,
        force_update=False,
        include=list(LOADER_BY_FOLDER_NAME.keys()),
        verbose=True,
    )

    changed_resources = get_changed_resources(cdf_tool_config, build_dir)
    assert not changed_resources, "Redeploying the same resources should not change anything"

    changed_source_files = get_changed_source_files(cdf_tool_config, build_dir, built_modules)
    assert not changed_source_files, "Pulling the same source should not change anything"


@pytest.mark.skipif(
    sys.version_info < (3, 11), reason="We only run this test on Python 3.11+ to avoid parallelism issues"
)
def test_deploy_complete_org_alpha(cdf_tool_config: CDFToolConfig, build_dir: Path) -> None:
    build = BuildCommand(silent=True, skip_tracking=True)

    built_modules = build.execute(
        verbose=False,
        organization_dir=data.COMPLETE_ORG_ALPHA_FLAGS,
        build_dir=build_dir,
        build_env_name="dev",
        no_clean=False,
        selected=None,
        ToolGlobals=cdf_tool_config,
    )

    deploy_command = DeployCommand(silent=False, skip_tracking=True)
    cdf_tool_config._environ["EVENTHUB_CLIENT_ID"] = os.environ["IDP_CLIENT_ID"]
    cdf_tool_config._environ["EVENTHUB_CLIENT_SECRET"] = os.environ["IDP_CLIENT_SECRET"]

    deploy_command.execute(
        cdf_tool_config,
        build_dir=build_dir,
        build_env_name="dev",
        dry_run=False,
        drop=False,
        drop_data=False,
        force_update=False,
        include=list(LOADER_BY_FOLDER_NAME.keys()),
        verbose=True,
    )

    changed_resources = get_changed_resources(cdf_tool_config, build_dir)
    assert not changed_resources, "Redeploying the same resources should not change anything"

    changed_source_files = get_changed_source_files(cdf_tool_config, build_dir, built_modules)
    assert not changed_source_files, "Pulling the same source should not change anything"


def get_changed_resources(cdf_tool_config: CDFToolConfig, build_dir: Path) -> dict[str, set[Any]]:
    changed_resources: dict[str, set[Any]] = {}
    for loader_cls in RESOURCE_LOADER_LIST:
        if loader_cls in {HostedExtractorSourceLoader, HostedExtractorDestinationLoader}:
            # These two we have no way of knowing if they have changed. So they are always redeployed.
            continue
        loader = loader_cls.create_loader(cdf_tool_config, build_dir)
        worker = ResourceWorker(loader)
        files = worker.load_files()
        _, to_update, *__ = worker.load_resources(files, environment_variables=cdf_tool_config.environment_variables())
        if changed := (set(loader.get_ids(to_update)) - {NodeId("sp_nodes", "MyExtendedFile")}):
            # We do not have a way to get CogniteFile extensions. This is a workaround to avoid the test failing.
            changed_resources[loader.display_name] = changed

    return changed_resources


def get_changed_source_files(
    cdf_tool_config: CDFToolConfig, build_dir: Path, built_modules: BuiltModuleList
) -> dict[str, set[Path]]:
    # This is a modified copy of the PullCommand._pull_build_dir and PullCommand._pull_resources methods
    # This will likely be hard to maintain, but if the pull command changes, should be refactored to be more
    # maintainable.
    cmd = PullCommand(silent=True, skip_tracking=True)
    changed_source_files: dict[str, set[Path]] = defaultdict(set)
    selected_loaders = cmd._clean_command.get_selected_loaders(build_dir, read_resource_folders=set(), include=None)
    for loader_cls in selected_loaders:
        if (not issubclass(loader_cls, ResourceLoader)) or (
            loader_cls in {HostedExtractorSourceLoader, HostedExtractorDestinationLoader}
        ):
            continue
        loader = loader_cls.create_loader(cdf_tool_config, build_dir)
        resources = built_modules.get_resources(None, loader.folder_name, loader.kind)
        if not resources:
            continue
        cdf_resources = loader.retrieve(resources.identifiers)
        cdf_resource_by_id = {loader.get_id(r): r for r in cdf_resources}

        resources_by_file = resources.by_file()
        file_results = ResourceDeployResult(loader.display_name)
        environment_variables = (
            cdf_tool_config.environment_variables() if loader.do_environment_variable_injection else {}
        )
        for source_file, resources in resources_by_file.items():
            local_resource_by_id = cmd._get_local_resource_dict_by_id(resources, loader, environment_variables)
            _, to_write = cmd._get_to_write(local_resource_by_id, cdf_resource_by_id, file_results, loader)
            original_content = remove_trailing_newline(source_file.read_text())
            new_content, extra_files = cmd._to_write_content(
                original_content, to_write, resources, environment_variables, loader
            )
            new_content = remove_trailing_newline(new_content)
            if new_content != original_content:
                changed_source_files[loader.display_name].add(source_file)
            for path, new_extra_content in extra_files.items():
                new_extra_content = remove_trailing_newline(new_extra_content)
                original_extra_content = remove_trailing_newline(path.read_text())
                if new_extra_content != original_extra_content:
                    changed_source_files[loader.display_name].add(path)

    return changed_source_files
