import contextlib
import os
import platform
import shutil
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import yaml
from dotenv import load_dotenv
from packaging.version import Version
from packaging.version import parse as parse_version
from rich import print
from rich.panel import Panel

from cognite_toolkit._cdf_tk.commands import BuildCommand, DeployCommand
from cognite_toolkit._cdf_tk.constants import ROOT_MODULES, SUPPORT_MODULE_UPGRADE_FROM_VERSION
from cognite_toolkit._cdf_tk.loaders import LOADER_BY_FOLDER_NAME
from cognite_toolkit._cdf_tk.prototypes.commands import ModulesCommand
from cognite_toolkit._cdf_tk.prototypes.commands._changes import ManualChange
from cognite_toolkit._cdf_tk.prototypes.commands.modules import CLICommands
from cognite_toolkit._cdf_tk.utils import CDFToolConfig, module_from_path
from cognite_toolkit._version import __version__

TEST_DIR_ROOT = Path(__file__).resolve().parent
PROJECT_INIT_DIR = TEST_DIR_ROOT / "project_inits"
PROJECT_INIT_DIR.mkdir(exist_ok=True)


def run() -> None:
    only_first = len(sys.argv) > 1 and sys.argv[1] == "--only-first"

    versions = get_versions_since(SUPPORT_MODULE_UPGRADE_FROM_VERSION)
    for version in versions:
        create_project_init(str(version))

    print(
        Panel(
            "All projects inits created successfully.",
            expand=False,
            title="cdf-tk init executed for all past versions.",
        )
    )

    print(
        Panel(
            "Running module upgrade for all supported versions.",
            expand=False,
            title="cdf-tk module upgrade",
        )
    )
    if only_first:
        versions = versions[-1:]
    for version in versions:
        with local_tmp_project_path() as project_path, local_build_path() as build_path, tool_globals() as cdf_tool_config:
            run_modules_upgrade(version, project_path, build_path, cdf_tool_config)


def get_versions_since(support_upgrade_from_version: str) -> list[Version]:
    result = subprocess.run("pip index versions cognite-toolkit --pre".split(), stdout=subprocess.PIPE)
    lines = result.stdout.decode().split("\n")
    for line in lines:
        if line.startswith("Available versions:"):
            raw_version_str = line.split(":", maxsplit=1)[1]
            supported_from = parse_version(support_upgrade_from_version)
            return [
                parsed
                for version in raw_version_str.split(",")
                if (parsed := parse_version(version.strip())) >= supported_from
            ]
    else:
        raise ValueError("Could not find available versions.")


def create_project_init(version: str) -> None:
    project_init = PROJECT_INIT_DIR / f"project_{version}"
    if project_init.exists():
        print(f"Project init for version {version} already exists.")
        return

    environment_directory = f".venv{version}"
    if (TEST_DIR_ROOT / environment_directory).exists():
        print(f"Environment for version {version} already exists")
    else:
        with chdir(TEST_DIR_ROOT):
            print(f"Creating environment for version {version}")
            create_venv = subprocess.run(["python", "-m", "venv", environment_directory])
            if create_venv.returncode != 0:
                raise ValueError(f"Failed to create environment for version {version}")

            if platform.system() == "Windows":
                install_toolkit = subprocess.run(
                    [f"{environment_directory}/Scripts/pip", "install", f"cognite-toolkit=={version}"]
                )
            else:
                install_toolkit = subprocess.run(
                    [f"{environment_directory}/bin/pip", "install", f"cognite-toolkit=={version}"]
                )

            if install_toolkit.returncode != 0:
                raise ValueError(f"Failed to install toolkit version {version}")
            print(f"Environment for version {version} created")

    modified_env_variables = os.environ.copy()
    repo_root = TEST_DIR_ROOT.parent
    if "PYTHONPATH" in modified_env_variables:
        # Need to remove the repo root from PYTHONPATH to avoid importing the wrong version of the toolkit
        # (This is typically set by the IDE, for example, PyCharm sets it when running tests).
        modified_env_variables["PYTHONPATH"] = modified_env_variables["PYTHONPATH"].replace(str(repo_root), "")
    if platform.system() == "Windows":
        old_version_script_dir = Path(f"{environment_directory}/Scripts/")
    else:
        old_version_script_dir = Path(f"{environment_directory}/bin/")
    with chdir(TEST_DIR_ROOT):
        cmd = [
            str(old_version_script_dir / "cdf-tk"),
            "init",
            f"{PROJECT_INIT_DIR.name}/{project_init.name}",
            "--clean",
        ]
        output = subprocess.run(
            cmd,
            capture_output=True,
            shell=True if platform.system() == "Windows" else False,
            env=modified_env_variables,
        )

        if output.returncode != 0:
            print(output.stderr.decode())
            raise ValueError(f"Failed to create project init for version {version}.")

    print(f"Project init for version {version} created.")
    with chdir(TEST_DIR_ROOT):
        shutil.rmtree(environment_directory)


def run_modules_upgrade(
    previous_version: Version, project_path: Path, build_path: Path, cdf_tool_config: CDFToolConfig
) -> None:
    project_init = PROJECT_INIT_DIR / f"project_{previous_version!s}"
    # Copy the project to a temporary location as the upgrade command modifies the project.
    shutil.copytree(project_init, project_path, dirs_exist_ok=True)

    with chdir(TEST_DIR_ROOT):
        modules = ModulesCommand(print_warning=False)
        # This is to allow running the function with having uncommitted changes in the repository.
        with patch.object(CLICommands, "has_uncommitted_changes", lambda: False):
            changes = modules.upgrade(project_path)

        delete_modules_requiring_manual_changes(changes)

        # Update the config file to run include all modules.
        update_config_yaml_to_select_all_modules(project_path)

        if previous_version < parse_version("0.2.0a4"):
            # Bug in pre 0.2.0a4 versions
            pump_view = (
                project_path
                / "cognite_modules"
                / "experimental"
                / "example_pump_data_model"
                / "data_models"
                / "4.Pump.view.yaml"
            )
            pump_view.write_text(pump_view.read_text().replace("external_id", "externalId"))

        build = BuildCommand(print_warning=False)
        build.execute(False, project_path, build_path, build_env_name="dev", no_clean=False)

        deploy = DeployCommand(print_warning=False)
        deploy.execute(
            cdf_tool_config,
            str(build_path),
            build_env_name="dev",
            dry_run=True,
            drop=False,
            drop_data=False,
            include=list(LOADER_BY_FOLDER_NAME),
            verbose=False,
        )

    print(
        Panel(
            f"Module upgrade for version {previous_version!s} to {__version__} completed successfully.",
            expand=False,
            style="green",
        )
    )


def delete_modules_requiring_manual_changes(changes):
    for change in changes:
        if not isinstance(change, ManualChange):
            continue
        for file in change.needs_to_change():
            if file.is_dir():
                shutil.rmtree(file)
            else:
                module = module_from_path(file)
                for part in reversed(file.parts):
                    if part == module:
                        break
                    file = file.parent
                if file.exists():
                    shutil.rmtree(file)


def update_config_yaml_to_select_all_modules(project_path):
    config_yaml = project_path / "config.dev.yaml"
    assert config_yaml.exists()
    yaml_data = yaml.safe_load(config_yaml.read_text())
    yaml_data["environment"]["selected"] = []
    for root_module in ROOT_MODULES:
        if (project_path / root_module).exists() and any(
            yaml_file for yaml_file in (project_path / root_module).rglob("*.yaml")
        ):
            yaml_data["environment"]["selected"].append(f"{root_module}/")
    config_yaml.write_text(yaml.dump(yaml_data))


@contextlib.contextmanager
def chdir(new_dir: Path) -> Iterator[None]:
    """
    Change directory to new_dir and return to the original directory when exiting the context.

    Args:
        new_dir: The new directory to change to.

    """
    current_working_dir = Path.cwd()
    os.chdir(new_dir)

    try:
        yield

    finally:
        os.chdir(current_working_dir)


@contextmanager
def tool_globals() -> Iterator[CDFToolConfig]:
    load_dotenv(TEST_DIR_ROOT.parent / ".env")

    try:
        yield CDFToolConfig()
    finally:
        ...


@contextmanager
def local_tmp_project_path() -> Path:
    project_path = TEST_DIR_ROOT / "tmp-project"
    if project_path.exists():
        shutil.rmtree(project_path)
    project_path.mkdir(exist_ok=True)
    try:
        yield project_path
    finally:
        ...


@contextmanager
def local_build_path() -> Path:
    build_path = TEST_DIR_ROOT / "build"
    if build_path.exists():
        shutil.rmtree(build_path)

    build_path.mkdir(exist_ok=True)
    # This is a small hack to get 0.1.0b1-4 working
    (build_path / "file.txt").touch(exist_ok=True)
    try:
        yield build_path
    finally:
        ...


if __name__ == "__main__":
    run()
