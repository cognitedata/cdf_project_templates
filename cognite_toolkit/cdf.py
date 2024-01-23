#!/usr/bin/env python
# The Typer parameters get mixed up if we use the __future__ import annotations
import os
import shutil
import sys
import tempfile
import urllib
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from graphlib import TopologicalSorter
from importlib import resources
from pathlib import Path
from typing import Annotated, Optional, Union, cast

import sentry_sdk
import typer
import yaml
from dotenv import load_dotenv
from rich import print
from rich.panel import Panel

from cognite_toolkit import _version
from cognite_toolkit.cdf_tk import bootstrap
from cognite_toolkit.cdf_tk.describe import describe_datamodel
from cognite_toolkit.cdf_tk.load import (
    LOADER_BY_FOLDER_NAME,
    AuthLoader,
    DataSetsLoader,
    DeployResults,
    ResourceLoader,
)
from cognite_toolkit.cdf_tk.run import run_transformation
from cognite_toolkit.cdf_tk.templates import (
    BUILD_ENVIRONMENT_FILE,
    COGNITE_MODULES,
    CUSTOM_MODULES,
    build_config,
    iterate_modules,
)
from cognite_toolkit.cdf_tk.templates.data_classes import BuildEnvironment, ConfigYAMLs, EnvironmentConfig, GlobalConfig
from cognite_toolkit.cdf_tk.utils import CDFToolConfig, read_yaml_file

if "pytest" not in sys.modules and os.environ.get("SENTRY_ENABLED", "true").lower() == "true":
    sentry_sdk.init(
        dsn="https://ea8b03f98a675ce080056f1583ed9ce7@o124058.ingest.sentry.io/4506429021093888",
        # Set traces_sample_rate to 1.0 to capture 100%
        # of transactions for performance monitoring.
        traces_sample_rate=1.0,
    )

app = typer.Typer(pretty_exceptions_short=False, pretty_exceptions_show_locals=False, pretty_exceptions_enable=False)
auth_app = typer.Typer(
    pretty_exceptions_short=False, pretty_exceptions_show_locals=False, pretty_exceptions_enable=False
)
describe_app = typer.Typer(
    pretty_exceptions_short=False, pretty_exceptions_show_locals=False, pretty_exceptions_enable=False
)
run_app = typer.Typer(
    pretty_exceptions_short=False, pretty_exceptions_show_locals=False, pretty_exceptions_enable=False
)
app.add_typer(auth_app, name="auth")
app.add_typer(describe_app, name="describe")
app.add_typer(run_app, name="run")


_AVAILABLE_DATA_TYPES: tuple[str, ...] = tuple(LOADER_BY_FOLDER_NAME)


# Common parameters handled in common callback
@dataclass
class Common:
    override_env: bool
    verbose: bool
    cluster: Union[str, None]
    project: Union[str, None]
    mockToolGlobals: Union[CDFToolConfig, None]


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"CDF-Toolkit version: {_version.__version__}.")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def common(
    ctx: typer.Context,
    verbose: Annotated[
        bool,
        typer.Option(
            help="Turn on to get more verbose output when running the commands",
        ),
    ] = False,
    override_env: Annotated[
        bool,
        typer.Option(
            help="Load the .env file in this or the parent directory, but also override currently set environment variables",
        ),
    ] = False,
    env_path: Annotated[
        Optional[str],
        typer.Option(
            help="Path to .env file to load. Defaults to .env in current or parent directory.",
        ),
    ] = None,
    cluster: Annotated[
        Optional[str],
        typer.Option(
            envvar="CDF_CLUSTER",
            help="The Cognite Data Fusion cluster to use. Can also be set with the CDF_CLUSTER environment variable.",
        ),
    ] = None,
    project: Annotated[
        Optional[str],
        typer.Option(
            envvar="CDF_PROJECT",
            help="The Cognite Data Fusion project to use. Can also be set with the CDF_PROJECT environment variable.",
        ),
    ] = None,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            help="See which version of the tooklit and the templates are installed.",
            callback=_version_callback,
        ),
    ] = False,
) -> None:
    """The cdf-tk tool is used to build and deploy Cognite Data Fusion project configurations from the command line or through CI/CD pipelines.

    Each of the main commands has a separate help, e.g. `cdf-tk build --help` or `cdf-tk deploy --help`.

    You can find the documation at https://developer.cognite.com/sdks/toolkit/
    and the template reference documentation at https://developer.cognite.com/sdks/toolkit/references/configs
    """
    if ctx.invoked_subcommand is None:
        print(
            "[bold]A tool to manage and deploy Cognite Data Fusion project configurations from the command line or through CI/CD pipelines.[/]"
        )
        print("[bold yellow]Usage:[/] cdf-tk [OPTIONS] COMMAND [ARGS]...")
        print("       Use --help for more information.")
        return
    if override_env:
        print("  [bold yellow]WARNING:[/] Overriding environment variables with values from .env file...")
        if cluster is not None or project is not None:
            print("            --cluster or --project is set and will override .env file values.")

    if env_path is not None:
        if not (dotenv_file := Path(env_path)).is_file():
            print(f"  [bold red]ERROR:[/] {env_path} does not exist.")
            exit(1)
    else:
        if not (dotenv_file := Path.cwd() / ".env").is_file():
            if not (dotenv_file := Path.cwd().parent / ".env").is_file():
                print("[bold yellow]WARNING:[/] No .env file found in current or parent directory.")

    if dotenv_file.is_file():
        if verbose:
            try:
                path_str = dotenv_file.relative_to(Path.cwd())
            except ValueError:
                path_str = dotenv_file.absolute()
            print(f"Loading .env file: {path_str!s}")
        load_dotenv(dotenv_file, override=override_env)

    ctx.obj = Common(
        verbose=verbose,
        override_env=override_env,
        cluster=cluster,
        project=project,
        mockToolGlobals=None,
    )


@app.command("build")
def build(
    ctx: typer.Context,
    source_dir: Annotated[
        str,
        typer.Argument(
            help="Where to find the module templates to build from",
            allow_dash=True,
        ),
    ] = "./",
    build_dir: Annotated[
        str,
        typer.Option(
            "--build-dir",
            "-b",
            help="Where to save the built module files",
        ),
    ] = "./build",
    build_env: Annotated[
        str,
        typer.Option(
            "--env",
            "-e",
            help="Build environment to build for",
        ),
    ] = "dev",
    clean: Annotated[
        bool,
        typer.Option(
            "--clean",
            "-c",
            help="Delete the build directory before building the configurations",
        ),
    ] = False,
) -> None:
    """Build configuration files from the module templates to a local build directory."""
    source_path = Path(source_dir)
    if not source_path.is_dir():
        print(f"  [bold red]ERROR:[/] {source_path} does not exist")
        exit(1)
    global_config = GlobalConfig.load_from_directory(source_path, build_env)
    config = EnvironmentConfig.load_from_directory(source_path, build_env)
    print(
        Panel(
            f"[bold]Building config files from templates into {build_dir!s} for environment {build_env} using {source_path!s} as sources...[/bold]"
            f"\n[bold]Config file:[/] '{config.filepath.absolute()!s}' \n[bold]Global config file:[/] '{global_config.filepath.absolute()!s}'"
        )
    )
    config.set_environment_variables()

    build_config(
        build_dir=Path(build_dir),
        source_dir=source_path,
        config=config,
        global_config=global_config,
        clean=clean,
        verbose=ctx.obj.verbose,
    )


@app.command("deploy")
def deploy(
    ctx: typer.Context,
    build_dir: Annotated[
        str,
        typer.Argument(
            help="Where to find the module templates to deploy from. Defaults to current directory.",
            allow_dash=True,
        ),
    ] = "./build",
    build_env: Annotated[
        str,
        typer.Option(
            "--env",
            "-e",
            help="CDF project environment to build for. Defined in environments.yaml.",
        ),
    ] = "dev",
    interactive: Annotated[
        bool,
        typer.Option(
            "--interactive",
            "-i",
            help="Whether to use interactive mode when deciding which modules to deploy.",
        ),
    ] = False,
    drop: Annotated[
        bool,
        typer.Option(
            "--drop",
            "-d",
            help="Whether to drop existing configurations, drop per resource if present.",
        ),
    ] = False,
    drop_data: Annotated[
        bool,
        typer.Option(
            "--drop-data",
            help="Whether to drop existing data in data model containers and spaces.",
        ),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            "-r",
            help="Whether to do a dry-run, do dry-run if present.",
        ),
    ] = False,
    include: Annotated[
        Optional[list[str]],
        typer.Option(
            "--include",
            "-i",
            help=f"Specify which resources to deploy, available options: {_AVAILABLE_DATA_TYPES}.",
        ),
    ] = None,
) -> None:
    """Deploy one or more resource types from the built configurations to a CDF project environment of your choice (as set in environments.yaml)."""
    # Override cluster and project from the options/env variables
    if ctx.obj.mockToolGlobals is not None:
        ToolGlobals = ctx.obj.mockToolGlobals
    else:
        ToolGlobals = CDFToolConfig(cluster=ctx.obj.cluster, project=ctx.obj.project)

    build_ = BuildEnvironment.load(read_yaml_file(Path(build_dir) / BUILD_ENVIRONMENT_FILE), build_env, "deploy")
    build_.set_environment_variables()

    print(Panel(f"[bold]Deploying config files from {build_dir} to environment {build_env}...[/]"))
    build_path = Path(build_dir)
    if not build_path.is_dir():
        typer.echo(
            f"  [bold yellow]WARNING:[/] {build_dir} does not exists. Did you forget to run `cdf-tk build` first?"
        )
        exit(1)

    include = _process_include(include, interactive)
    print(ToolGlobals.as_string())

    # The 'auth' loader is excluded, as it is run twice,
    # once with all_scoped_only and once with resource_scoped_only
    selected_loaders = {
        LoaderCls: LoaderCls.dependencies
        for folder_name, loader_classes in LOADER_BY_FOLDER_NAME.items()
        if folder_name in include and folder_name != "auth" and (build_path / folder_name).is_dir()
        for LoaderCls in loader_classes
    }
    results = DeployResults([], "deploy", dry_run=dry_run)
    ordered_loaders = list(TopologicalSorter(selected_loaders).static_order())
    if len(ordered_loaders) > len(selected_loaders):
        print("[bold yellow]WARNING:[/] Some resources were added due to dependencies.")
    if drop or drop_data:
        # Drop has to be done in the reverse order of deploy.
        if drop and drop_data:
            print(Panel("[bold] Cleaning resources as --drop and --drop-data are passed[/]"))
        elif drop:
            print(Panel("[bold] Cleaning resources as --drop is passed[/]"))
        elif drop_data:
            print(Panel("[bold] Cleaning resources as --drop-data is passed[/]"))
        for LoaderCls in reversed(ordered_loaders):
            if not issubclass(LoaderCls, ResourceLoader):
                continue
            loader = LoaderCls.create_loader(ToolGlobals)
            result = loader.clean_resources(
                build_path / LoaderCls.folder_name,
                ToolGlobals,
                drop=drop,
                dry_run=dry_run,
                drop_data=drop_data,
                verbose=ctx.obj.verbose,
            )
            if result:
                results[result.name] = result
            if ToolGlobals.failed:
                print(f"[bold red]ERROR: [/] Failure to clean {LoaderCls.folder_name} as expected.")
                exit(1)
        if "auth" in include and (directory := (Path(build_dir) / "auth")).is_dir():
            result = AuthLoader.create_loader(ToolGlobals, target_scopes="all").clean_resources(
                directory,
                ToolGlobals,
                drop=drop,
                dry_run=dry_run,
                verbose=ctx.obj.verbose,
            )
            if result:
                results[result.name] = result
            if ToolGlobals.failed:
                print("[bold red]ERROR: [/] Failure to clean auth as expected.")
                exit(1)

        print("[bold]...Cleaning Complete[/]")
    arguments = dict(
        ToolGlobals=ToolGlobals,
        dry_run=dry_run,
        has_done_drop=drop,
        has_dropped_data=drop_data,
        verbose=ctx.obj.verbose,
    )
    if drop or drop_data:
        print(Panel("[bold]DEPLOYING resources...[/]"))
    if "auth" in include and (directory := (Path(build_dir) / "auth")).is_dir():
        # First, we need to get all the generic access, so we can create the rest of the resources.
        result = AuthLoader.create_loader(ToolGlobals, target_scopes="all_scoped_only").deploy_resources(
            directory,
            **arguments,
        )
        if ToolGlobals.failed:
            print("[bold red]ERROR: [/] Failure to deploy auth (groups) with ALL scope as expected.")
            exit(1)
        if result:
            results[result.name] = result
        if ctx.obj.verbose:
            # Extra newline
            print("")
    for LoaderCls in ordered_loaders:
        result = LoaderCls.create_loader(ToolGlobals).deploy_resources(  # type: ignore[assignment]
            build_path / LoaderCls.folder_name,
            **arguments,
        )
        if ToolGlobals.failed:
            if results and results.has_counts:
                print(results.counts_table())
            if results and results.has_uploads:
                print(results.uploads_table())
            print(f"[bold red]ERROR: [/] Failure to load {LoaderCls.folder_name} as expected.")
            exit(1)
        if result:
            results[result.name] = result
        if ctx.obj.verbose:
            # Extra newline
            print("")

    if "auth" in include and (directory := (Path(build_dir) / "auth")).is_dir():
        # Last, we create the Groups again, but this time we do not filter out any capabilities
        # and we do not skip validation as the resources should now have been created.
        loader = AuthLoader.create_loader(ToolGlobals, target_scopes="resource_scoped_only")
        result = loader.deploy_resources(
            directory,
            **arguments,
        )
        if ToolGlobals.failed:
            print("[bold red]ERROR: [/] Failure to deploy auth (groups) scoped to resources as expected.")
            exit(1)
        if result:
            results[result.name] = result
    if results.has_counts:
        print(results.counts_table())
    if results.has_uploads:
        print(results.uploads_table())
    if ToolGlobals.failed:
        print("[bold red]ERROR: [/] Failure to deploy auth (groups) scoped to resources as expected.")
        exit(1)


@app.command("clean")
def clean(
    ctx: typer.Context,
    build_dir: Annotated[
        str,
        typer.Argument(
            help="Where to find the module templates to clean from. Defaults to ./build directory.",
            allow_dash=True,
        ),
    ] = "./build",
    build_env: Annotated[
        str,
        typer.Option(
            "--env",
            "-e",
            help="CDF project environment to use for cleaning.",
        ),
    ] = "dev",
    interactive: Annotated[
        bool,
        typer.Option(
            "--interactive",
            "-i",
            help="Whether to use interactive mode when deciding which resource types to clean.",
        ),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            "-r",
            help="Whether to do a dry-run, do dry-run if present",
        ),
    ] = False,
    include: Annotated[
        Optional[list[str]],
        typer.Option(
            "--include",
            "-i",
            help=f"Specify which resource types to deploy, supported types: {_AVAILABLE_DATA_TYPES}",
        ),
    ] = None,
) -> None:
    """Clean up a CDF environment as set in environments.yaml restricted to the entities in the configuration files in the build directory."""
    # Override cluster and project from the options/env variables
    if ctx.obj.mockToolGlobals is not None:
        ToolGlobals = ctx.obj.mockToolGlobals
    else:
        ToolGlobals = CDFToolConfig(cluster=ctx.obj.cluster, project=ctx.obj.project)

    build_ = BuildEnvironment.load(read_yaml_file(Path(build_dir) / BUILD_ENVIRONMENT_FILE), build_env, "clean")
    build_.set_environment_variables()

    Panel(f"[bold]Cleaning environment {build_env} based on config files from {build_dir}...[/]")
    build_path = Path(build_dir)
    if not build_path.is_dir():
        typer.echo(
            f"  [bold yellow]WARNING:[/] {build_dir} does not exists. Did you forget to run `cdf-tk build` first?"
        )
        exit(1)

    include = _process_include(include, interactive)

    # The 'auth' loader is excluded, as it is run at the end.
    selected_loaders = {
        LoaderCls: LoaderCls.dependencies
        for folder_name, loader_classes in LOADER_BY_FOLDER_NAME.items()
        if folder_name in include and folder_name != "auth" and (build_path / folder_name).is_dir()
        for LoaderCls in loader_classes
    }

    print(ToolGlobals.as_string())
    if ToolGlobals.failed:
        print("[bold red]ERROR: [/] Failure to delete data models as expected.")
        exit(1)
    results = DeployResults([], "clean", dry_run=dry_run)
    resolved_list = list(TopologicalSorter(selected_loaders).static_order())
    if len(resolved_list) > len(selected_loaders):
        print("[bold yellow]WARNING:[/] Some resources were added due to dependencies.")
    for LoaderCls in reversed(resolved_list):
        if not issubclass(LoaderCls, ResourceLoader):
            continue
        loader = LoaderCls.create_loader(ToolGlobals)
        if type(loader) is DataSetsLoader:
            print("[bold yellow]WARNING:[/] Dataset cleaning is not supported, skipping...")
            continue
        result = loader.clean_resources(
            build_path / LoaderCls.folder_name,
            ToolGlobals,
            drop=True,
            dry_run=dry_run,
            drop_data=True,
            verbose=ctx.obj.verbose,
        )
        if result:
            results[result.name] = result
        if ToolGlobals.failed:
            if results and results.has_counts:
                print(results.counts_table())
            if results and results.has_uploads:
                print(results.uploads_table())
            print(f"[bold red]ERROR: [/] Failure to clean {LoaderCls.folder_name} as expected.")
            exit(1)
    if "auth" in include and (directory := (Path(build_dir) / "auth")).is_dir():
        result = AuthLoader.create_loader(ToolGlobals, target_scopes="all").clean_resources(
            directory,
            ToolGlobals,
            drop=True,
            dry_run=dry_run,
            verbose=ctx.obj.verbose,
        )
        if ToolGlobals.failed:
            print("[bold red]ERROR: [/] Failure to clean auth as expected.")
            exit(1)
        if result:
            results[result.name] = result
    if results.has_counts:
        print(results.counts_table())
    if results.has_uploads:
        print(results.uploads_table())
    if ToolGlobals.failed:
        print("[bold red]ERROR: [/] Failure to clean auth as expected.")
        exit(1)


@auth_app.callback(invoke_without_command=True)
def auth_main(ctx: typer.Context) -> None:
    """Test, validate, and configure authentication and authorization for CDF projects."""
    if ctx.invoked_subcommand is None:
        print("Use [bold yellow]cdf-tk auth --help[/] for more information.")
    return None


@auth_app.command("verify")
def auth_verify(
    ctx: typer.Context,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            "-r",
            help="Whether to do a dry-run, do dry-run if present.",
        ),
    ] = False,
    interactive: Annotated[
        bool,
        typer.Option(
            "--interactive",
            "-i",
            help="Will run the verification in interactive mode, prompting for input. Used to bootstrap a new project.",
        ),
    ] = False,
    group_file: Annotated[
        Optional[str],
        typer.Option(
            "--group-file",
            "-f",
            help="Path to group yaml configuration file to use for group verification. Defaults to readwrite.all.group.yaml from the cdf_auth_readwrite_all common module.",
        ),
    ] = None,
    update_group: Annotated[
        int,
        typer.Option(
            "--update-group",
            "-u",
            help="Used to update an existing group with the configurations from the configuration file. Set to the group id to update or 1 to update the default write-all group (if the tool is only member of one group).",
        ),
    ] = 0,
    create_group: Annotated[
        Optional[str],
        typer.Option(
            "--create-group",
            "-c",
            help="Used to create a new group with the configurations from the configuration file. Set to the source id that the new group should be configured with.",
        ),
    ] = None,
) -> None:
    """When you have the necessary information about your identity provider configuration,
    you can use this command to configure the tool and verify that the token has the correct access rights to the project.
    It can also create a group with the correct access rights, defaulting to write-all group
    meant for an admin/CICD pipeline.

    As a minimum, you need the CDF project name, the CDF cluster, an identity provider token URL, and a service account client ID
    and client secret (or an OAuth2 token set in CDF_TOKEN environment variable).

    Needed capabilites for bootstrapping:
    "projectsAcl": ["LIST", "READ"],
    "groupsAcl": ["LIST", "READ", "CREATE", "UPDATE", "DELETE"]

    The default bootstrap group configuration is readwrite.all.group.yaml from the cdf_auth_readwrite_all common module.
    """
    if create_group is not None and update_group != 0:
        print("[bold red]ERROR: [/] --create-group and --update-group are mutually exclusive.")
        exit(1)
    if ctx.obj.mockToolGlobals is not None:
        ToolGlobals = ctx.obj.mockToolGlobals
    else:
        ToolGlobals = CDFToolConfig(cluster=ctx.obj.cluster, project=ctx.obj.project)
    if group_file is None:
        template_dir = cast(Path, resources.files("cognite_toolkit"))
        group_path = template_dir.joinpath(
            Path(f"./{COGNITE_MODULES}/common/cdf_auth_readwrite_all/auth/readwrite.all.group.yaml")
        )
    else:
        group_path = Path(group_file)
    bootstrap.check_auth(
        ToolGlobals,
        group_file=group_path,
        update_group=update_group,
        create_group=create_group,
        interactive=interactive,
        dry_run=dry_run,
        verbose=ctx.obj.verbose,
    )
    if ToolGlobals.failed:
        print("[bold red]ERROR: [/] Failure to verify access rights.")
        exit(1)


@app.command("init")
def main_init(
    ctx: typer.Context,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            "-r",
            help="Whether to do a dry-run, do dry-run if present.",
        ),
    ] = False,
    upgrade: Annotated[
        bool,
        typer.Option(
            "--upgrade",
            "-u",
            help="Will upgrade templates in place without overwriting existing config.yaml and other files.",
        ),
    ] = False,
    git_branch: Annotated[
        Optional[str],
        typer.Option(
            "--git",
            "-g",
            help="Will download the latest templates from the git repository branch specified. Use `main` to get the very latest templates.",
        ),
    ] = None,
    no_backup: Annotated[
        bool,
        typer.Option(
            "--no-backup",
            help="Will skip making a backup before upgrading.",
        ),
    ] = False,
    clean: Annotated[
        bool,
        typer.Option(
            "--clean",
            help="Will delete the new_project directory before starting.",
        ),
    ] = False,
    init_dir: Annotated[
        str,
        typer.Argument(
            help="Directory path to project to initialize or upgrade with templates.",
        ),
    ] = "new_project",
) -> None:
    """Initialize or upgrade a new CDF project with templates."""
    project_dir = Path.cwd() / f"{init_dir}"

    target_dir_display = f"'{project_dir.relative_to(Path.cwd())!s}'"

    template_source = Path(resources.files("cognite_toolkit"))  # type: ignore[arg-type]
    if upgrade and git_branch is not None:
        template_source = _download_templates(git_branch, dry_run)

    files_to_copy: list[str] = [
        "README.md",
        ".gitignore",
        ".env.tmpl",
    ]
    root_modules: list[str] = [
        COGNITE_MODULES,
        CUSTOM_MODULES,
    ]

    if project_dir.exists():
        if upgrade:
            print(f"[bold]Upgrading directory {target_dir_display}...[/b]")
        elif clean and dry_run:
            print(f"Would clean out directory {target_dir_display}...")
        elif clean:
            print(f"Cleaning out directory {target_dir_display}...")
            shutil.rmtree(project_dir)
        else:
            print(f"Directory {target_dir_display} already exists.")
            exit(1)
    elif not project_dir.exists() and upgrade:
        print(f"Found no directory {target_dir_display} to upgrade.")
        exit(1)

    if not dry_run and not upgrade:
        project_dir.mkdir(exist_ok=True)

    if upgrade:
        print("  Will upgrade modules and files in place.")

    copy_prefix = "Would" if dry_run else "Will"
    print(f"{copy_prefix} copy these files to {target_dir_display}:")
    print(files_to_copy)
    modules_by_root: dict[str, list[str]] = {}
    for root_module in root_modules:
        modules_by_root[root_module] = [
            f"{module.relative_to(template_source)!s}" for module, _ in iterate_modules(template_source / root_module)
        ]

        print(f"{copy_prefix} copy these modules to {target_dir_display} from {root_module}:")
        print(modules_by_root[root_module])

    copy_prefix = "Would copy" if dry_run else "Copying"
    for filename in files_to_copy:
        if ctx.obj.verbose:
            print(f"{copy_prefix} file {filename} to {target_dir_display}")
        if not dry_run:
            shutil.copyfile(template_source / filename, project_dir / filename)

    if upgrade and not no_backup:
        prefix = "Would have backed up" if dry_run else "Backing up"
        if ctx.obj.verbose:
            print(f"{prefix} {target_dir_display}")
        if not dry_run:
            backup_dir = tempfile.mkdtemp(prefix=f"{project_dir.name}.", suffix=".bck", dir=Path.cwd())
            shutil.copytree(project_dir, Path(backup_dir), dirs_exist_ok=True)
    elif upgrade:
        print(
            f"[bold yellow]WARNING:[/] --no-backup is specified, no backup {'would have been' if dry_run else 'will be'} be."
        )

    for root_module in root_modules:
        if ctx.obj.verbose:
            print(f"{copy_prefix} the following modules from  {root_module} to {target_dir_display}")
            print(modules_by_root[root_module])
        if not dry_run:
            (Path(project_dir) / root_module).mkdir(exist_ok=True)
            # Default files are not copied, as they are only used to setup the config.yaml.
            shutil.copytree(
                template_source / root_module,
                project_dir / root_module,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("default.*"),
            )

    if not dry_run and upgrade:
        print(f"You project in {target_dir_display} was upgraded.")
    elif not dry_run:
        print(f"A new project was created in {target_dir_display}.")

    # Creating the [environment].config.yaml files
    environment_default = template_source / COGNITE_MODULES / "default.environments.yaml"
    if not environment_default.is_file():
        print(
            f"  [bold red]ERROR:[/] Could not find default.environments.yaml in {environment_default.parent.relative_to(Path.cwd())!s}. "
            f"There is something wrong with your installation, try to reinstall `cognite-tk`, and if the problem persists, please contact support."
        )
        exit(1)
    if upgrade and not clean:
        existing_environments = list(project_dir.glob("*.config.yaml"))
        if len(existing_environments) >= 1:
            config_yamls = ConfigYAMLs.load_existing_environments(existing_environments)
        else:
            print("  [bold yellow]WARNING:[/] No existing [env].config.yaml files found, creating from the defaults.")
            config_yamls = ConfigYAMLs.load_default_environments(yaml.safe_load(environment_default.read_text()))
    else:
        config_yamls = ConfigYAMLs.load_default_environments(yaml.safe_load(environment_default.read_text()))

    if not upgrade:
        config_yamls.load_default_variables(template_source)

    config_yamls.load_variables(project_dir)

    print(f"Loaded variables from {len(config_yamls)} environments: {list(config_yamls.keys())}")

    for environment, config_yaml in config_yamls.items():
        config_filepath = project_dir / f"{environment}.config.yaml"
        print(f"Loaded config for environment {environment}:")
        print(str(config_yaml))
        if ctx.obj.verbose and upgrade:
            # If we are not upgrading, all variables are added.
            for added in config_yaml.added:
                print(f"  [bold green]ADDED:[/] {added}")

        if dry_run:
            print(f"Would write {config_filepath.name} to {target_dir_display}")
        else:
            config_filepath.write_text(config_yaml.dump_yaml_with_comments(indent_size=2))
            print(f"Wrote {config_filepath.name} file to {target_dir_display}")

    if not upgrade or clean:
        global_default = template_source / COGNITE_MODULES / "default.global.yaml"
        if not global_default.is_file():
            print(
                f"  [bold red]ERROR:[/] Could not find default.global.yaml in {global_default.parent.relative_to(Path.cwd())!s}. "
                f"There is something wrong with your installation, try to reinstall `cognite-tk`, and if the problem persists, please contact support."
            )
            exit(1)

        global_config = project_dir / "global.yaml"
        prefix = "Would write" if dry_run else "Writing"
        print(f"{prefix} global.yaml to {target_dir_display}")
        if not dry_run:
            shutil.copyfile(global_default, global_config)


@describe_app.callback(invoke_without_command=True)
def describe_main(ctx: typer.Context) -> None:
    """Commands to describe and document configurations and CDF project state, use --project (ENV_VAR: CDF_PROJECT) to specify project to use."""
    if ctx.invoked_subcommand is None:
        print("Use [bold yellow]cdf-tk describe --help[/] for more information.")
    return None


@describe_app.command("datamodel")
def describe_datamodel_cmd(
    ctx: typer.Context,
    space: Annotated[
        Optional[str],
        typer.Option(
            "--space",
            "-s",
            prompt=True,
            help="Space where the data model to describe is located.",
        ),
    ] = None,
    data_model: Annotated[
        Optional[str],
        typer.Option(
            "--datamodel",
            "-d",
            prompt=False,
            help="Data model to describe. If not specified, the first data model found in the space will be described.",
        ),
    ] = None,
) -> None:
    """This command will describe the characteristics of a data model given the space
    name and datamodel name."""
    if space is None or len(space) == 0:
        print("[bold red]ERROR: [/] --space is required.")
        exit(1)
    if ctx.obj.mockToolGlobals is not None:
        ToolGlobals = ctx.obj.mockToolGlobals
    else:
        ToolGlobals = CDFToolConfig(cluster=ctx.obj.cluster, project=ctx.obj.project)
    describe_datamodel(ToolGlobals, space, data_model)
    return None


@run_app.callback(invoke_without_command=True)
def run_main(ctx: typer.Context) -> None:
    """Commands to execute processes in CDF, use --project (ENV_VAR: CDF_PROJECT) to specify project to use."""
    if ctx.invoked_subcommand is None:
        print("Use [bold yellow]cdf-tk run --help[/] for more information.")


@run_app.command("transformation")
def run_transformation_cmd(
    ctx: typer.Context,
    external_id: Annotated[
        Optional[str],
        typer.Option(
            "--external_id",
            "-e",
            prompt=True,
            help="External id of the transformation to run.",
        ),
    ] = None,
) -> None:
    """This command will run the specified transformation using a one-time session."""
    if ctx.obj.mockToolGlobals is not None:
        ToolGlobals = ctx.obj.mockToolGlobals
    else:
        ToolGlobals = CDFToolConfig(cluster=ctx.obj.cluster, project=ctx.obj.project)
    external_id = cast(str, external_id).strip()
    run_transformation(ToolGlobals, external_id)


def _process_include(include: Optional[list[str]], interactive: bool) -> list[str]:
    if include and (invalid_types := set(include).difference(_AVAILABLE_DATA_TYPES)):
        print(
            f"  [bold red]ERROR:[/] Invalid resource types specified: {invalid_types}, available types: {_AVAILABLE_DATA_TYPES}"
        )
        exit(1)
    include = include or list(_AVAILABLE_DATA_TYPES)
    if interactive:
        include = _select_data_types(include)
    return include


def _select_data_types(include: Sequence[str]) -> list[str]:
    mapping: dict[int, str] = {}
    for i, datatype in enumerate(include):
        print(f"[bold]{i})[/] {datatype}")
        mapping[i] = datatype
    print("\na) All")
    print("q) Quit")
    answer = input("Select resource types to include: ")
    if answer.casefold() == "a":
        return list(include)
    elif answer.casefold() == "q":
        exit(0)
    else:
        try:
            return [mapping[int(answer)]]
        except ValueError:
            print(f"Invalid selection: {answer}")
            exit(1)


def _download_templates(git_branch: str, dry_run: bool) -> Path:
    toolkit_github_url = f"https://github.com/cognitedata/cdf-project-templates/archive/refs/heads/{git_branch}.zip"
    extract_dir = tempfile.mkdtemp(prefix="git.", suffix=".tmp", dir=Path.cwd())
    prefix = "Would download" if dry_run else "Downloading"
    print(f"{prefix} templates from https://github.com/cognitedata/cdf-project-templates, branch {git_branch}...")
    print(
        "  [bold yellow]WARNING:[/] You are only upgrading templates, not the cdf-tk tool. "
        "Your current version may not support the new templates."
    )
    if not dry_run:
        try:
            zip_path, _ = urllib.request.urlretrieve(toolkit_github_url)
            with zipfile.ZipFile(zip_path, "r") as f:
                f.extractall(extract_dir)
        except Exception:
            print(
                f"Failed to download templates. Are you sure that the branch {git_branch} exists in"
                + "the https://github.com/cognitedata/cdf-project-templatesrepository?\n{e}"
            )
            exit(1)
    return Path(extract_dir) / f"cdf-project-templates-{git_branch}" / "cognite_toolkit"


if __name__ == "__main__":
    app()
