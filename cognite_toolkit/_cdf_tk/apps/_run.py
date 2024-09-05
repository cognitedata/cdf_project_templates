from pathlib import Path
from typing import Annotated, Any, Optional

import typer
from rich import print

from cognite_toolkit._cdf_tk.cdf_toml import CDFToml
from cognite_toolkit._cdf_tk.commands import (
    RunFunctionCommand,
    RunTransformationCommand,
)
from cognite_toolkit._cdf_tk.utils import CDFToolConfig

CDF_TOML = CDFToml.load(Path.cwd())


class RunApp(typer.Typer):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.callback(invoke_without_command=True)(self.main)
        self.command("transformation")(self.run_transformation)
        self.add_typer(RunFunctionApp(*args, **kwargs), name="function")

    @staticmethod
    def main(ctx: typer.Context) -> None:
        """Commands to execute processes in CDF."""
        if ctx.invoked_subcommand is None:
            print("Use [bold yellow]cdf run --help[/] for more information.")

    @staticmethod
    def run_transformation(
        ctx: typer.Context,
        external_id: Annotated[
            str,
            typer.Option(
                "--external-id",
                "-e",
                prompt=True,
                help="External id of the transformation to run.",
            ),
        ],
    ) -> None:
        """This command will run the specified transformation using a one-time session."""
        cmd = RunTransformationCommand()
        cmd.run(lambda: cmd.run_transformation(CDFToolConfig.from_context(ctx), external_id))


class RunFunctionApp(typer.Typer):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.callback(invoke_without_command=True)(self.main)
        self.command("local")(self.run_local)
        self.command("live")(self.run_cdf)

    @staticmethod
    def main(ctx: typer.Context) -> None:
        """Commands to execute function."""
        if ctx.invoked_subcommand is None:
            print("Use [bold yellow]cdf run function --help[/] for more information.")

    @staticmethod
    def run_local(
        ctx: typer.Context,
        external_id: Annotated[
            str,
            typer.Argument(
                help="External id of the function to run.",
            ),
        ],
        organization_dir: Annotated[
            Path,
            typer.Option(
                "--organization-dir",
                "-o",
                help="Path to project directory with the modules. This is used to search for available functions.",
            ),
        ] = CDF_TOML.cdf.organization_dir,
        env_name: Annotated[
            str,
            typer.Option(
                "--env",
                "-e",
                help="Name of the build environment to use. If not provided, the default environment will be used.",
            ),
        ] = CDF_TOML.cdf.default_env,
        schedule: Annotated[
            Optional[str],
            typer.Option(
                "--schedule",
                "-s",
                help="Schedule to run the function with (if any). The data and credentials will be taken from the schedule.",
            ),
        ] = None,
        rebuild_env: Annotated[
            bool,
            typer.Option(
                "--rebuild-env",
                help="Whether to rebuild the environment before running the function.",
            ),
        ] = False,
    ) -> None:
        """This command will run the specified function locally."""
        cmd = RunFunctionCommand()
        cmd.run(
            lambda: cmd.execute(
                CDFToolConfig.from_context(ctx),
                external_id,
                schedule,
                False,
                True,
                rebuild_env,
                False,
                str(organization_dir),
                schedule,
                env_name,
                False,
            )
        )

    @staticmethod
    def run_cdf(
        ctx: typer.Context,
        external_id: Annotated[
            Optional[str],
            typer.Argument(
                help="External id of the function to run. If not provided, the function "
                "will be selected interactively.",
            ),
        ] = None,
        organization_dir: Annotated[
            Path,
            typer.Option(
                "--organization-dir",
                "-o",
                help="Path to organization directory with the modules. This is used to search for available functions.",
            ),
        ] = CDF_TOML.cdf.organization_dir,
        env_name: Annotated[
            str,
            typer.Option(
                "--env",
                "-e",
                help="Name of the build environment to use. If not provided, the default environment will be used.",
            ),
        ] = CDF_TOML.cdf.default_env,
        schedule: Annotated[
            Optional[str],
            typer.Option(
                "--schedule",
                "-s",
                help="The name of the schedule to pick the data from",
            ),
        ] = None,
        wait: Annotated[
            bool,
            typer.Option(
                "--wait",
                "-w",
                help="Whether to wait for the function to complete.",
            ),
        ] = False,
    ) -> None:
        """This command will run the specified function (assuming it is deployed) in CDF."""
        cmd = RunFunctionCommand()
        cmd.run(
            lambda: cmd.run_cdf(
                CDFToolConfig.from_context(ctx), organization_dir, env_name, external_id, schedule, wait
            )
        )
