from pathlib import Path
from typing import Annotated, Any, Optional, Union

import typer
from cognite.client.data_classes import WorkflowVersionId
from cognite.client.data_classes.data_modeling import DataModelId, ViewId
from rich import print

from cognite_toolkit._cdf_tk.commands import (
    DumpAssetsCommand,
    DumpEventCommand,
    DumpFileMetadataCommand,
    DumpResourceCommand,
    DumpTimeSeriesCommand,
)
from cognite_toolkit._cdf_tk.commands.dump_resource import (
    DataModelFinder,
    GroupFinder,
    NodeFinder,
    TransformationFinder,
    WorkflowFinder,
)
from cognite_toolkit._cdf_tk.exceptions import ToolkitRequiredValueError
from cognite_toolkit._cdf_tk.feature_flags import Flags
from cognite_toolkit._cdf_tk.utils.auth import EnvironmentVariables


class DumpApp(typer.Typer):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.callback(invoke_without_command=True)(self.dump_main)
        self.command("datamodel")(self.dump_datamodel_cmd)
        self.command("asset")(self.dump_asset_cmd)
        self.command("timeseries")(self.dump_timeseries_cmd)
        self.command("file")(self.dump_filemetadata_cmd)
        self.command("event")(self.dump_event_cmd)

        if Flags.DUMP_EXTENDED.is_enabled():
            self.command("workflow")(self.dump_workflow)
            self.command("transformation")(self.dump_transformation)
            self.command("group")(self.dump_group)
            self.command("node")(self.dump_node)

    def dump_main(self, ctx: typer.Context) -> None:
        """Commands to dump resource configurations from CDF into a temporary directory."""
        if ctx.invoked_subcommand is None:
            print("Use [bold yellow]cdf dump --help[/] for more information.")
        return None

    @staticmethod
    def dump_datamodel_cmd(
        ctx: typer.Context,
        data_model_id: Annotated[
            Optional[list[str]],
            typer.Argument(
                help="Data model ID to dump. Format: space external_id version. Example: 'my_space my_external_id v1'. "
                "Note that version is optional and defaults to the latest published version. If nothing is provided,"
                "an interactive prompt will be shown to select the data model.",
            ),
        ] = None,
        output_dir: Annotated[
            Path,
            typer.Option(
                "--output-dir",
                "-o",
                help="Where to dump the datamodel files.",
                allow_dash=True,
            ),
        ] = Path("tmp"),
        clean: Annotated[
            bool,
            typer.Option(
                "--clean",
                "-c",
                help="Delete the output directory before dumping the datamodel.",
            ),
        ] = False,
        verbose: Annotated[
            bool,
            typer.Option(
                "--verbose",
                "-v",
                help="Turn on to get more verbose output when running the command",
            ),
        ] = False,
    ) -> None:
        """This command will dump the selected data model as yaml to the folder specified, defaults to /tmp."""
        selected_data_model: Union[DataModelId, None] = None
        if data_model_id is not None:
            if len(data_model_id) <= 2:
                raise ToolkitRequiredValueError(
                    "Data model ID must have at least 2 parts: space, external_id, and, optionally, version."
                )
            selected_data_model = DataModelId(*data_model_id)
        client = EnvironmentVariables.create_from_environment().get_client()

        cmd = DumpResourceCommand()
        cmd.run(
            lambda: cmd.dump_to_yamls(
                DataModelFinder(client, selected_data_model),
                output_dir=output_dir,
                clean=clean,
                verbose=verbose,
            )
        )

    @staticmethod
    def dump_workflow(
        ctx: typer.Context,
        workflow_id: Annotated[
            Optional[list[str]],
            typer.Argument(
                help="Workflow ID to dump. Format: external_id version. Example: 'my_external_id v1'. "
                "If nothing is provided, an interactive prompt will be shown to select the workflow",
            ),
        ] = None,
        output_dir: Annotated[
            Path,
            typer.Option(
                "--output-dir",
                "-o",
                help="Where to dump the workflow files.",
                allow_dash=True,
            ),
        ] = Path("tmp"),
        clean: Annotated[
            bool,
            typer.Option(
                "--clean",
                "-c",
                help="Delete the output directory before dumping the workflow.",
            ),
        ] = False,
        verbose: Annotated[
            bool,
            typer.Option(
                "--verbose",
                "-v",
                help="Turn on to get more verbose output when running the command",
            ),
        ] = False,
    ) -> None:
        """This command will dump the selected workflow as yaml to the folder specified, defaults to /tmp."""
        selected_workflow: Union[WorkflowVersionId, None] = None
        if workflow_id is not None:
            if len(workflow_id) <= 1:
                raise ToolkitRequiredValueError(
                    "Workflow ID must have at least 1 part: external_id and, optionally, version."
                )
            selected_workflow = WorkflowVersionId(*workflow_id)
        client = EnvironmentVariables.create_from_environment().get_client()

        cmd = DumpResourceCommand()
        cmd.run(
            lambda: cmd.dump_to_yamls(
                WorkflowFinder(client, selected_workflow),
                output_dir=output_dir,
                clean=clean,
                verbose=verbose,
            )
        )

    @staticmethod
    def dump_transformation(
        ctx: typer.Context,
        transformation_id: Annotated[
            Optional[str],
            typer.Argument(
                help="Transformation ID to dump. Format: external_id. Example: 'my_external_id'. "
                "If nothing is provided, an interactive prompt will be shown to select the transformation.",
            ),
        ] = None,
        output_dir: Annotated[
            Path,
            typer.Option(
                "--output-dir",
                "-o",
                help="Where to dump the transformation files.",
                allow_dash=True,
            ),
        ] = Path("tmp"),
        clean: Annotated[
            bool,
            typer.Option(
                "--clean",
                "-c",
                help="Delete the output directory before dumping the transformation.",
            ),
        ] = False,
        verbose: Annotated[
            bool,
            typer.Option(
                "--verbose",
                "-v",
                help="Turn on to get more verbose output when running the command",
            ),
        ] = False,
    ) -> None:
        """This command will dump the selected transformation as yaml to the folder specified, defaults to /tmp."""
        client = EnvironmentVariables.create_from_environment().get_client()

        cmd = DumpResourceCommand()
        cmd.run(
            lambda: cmd.dump_to_yamls(
                TransformationFinder(client, transformation_id),
                output_dir=output_dir,
                clean=clean,
                verbose=verbose,
            )
        )

    @staticmethod
    def dump_group(
        ctx: typer.Context,
        group_name: Annotated[
            Optional[str],
            typer.Argument(
                help="Group name to dump. Format: name. Example: 'my_group'. "
                "If nothing is provided, an interactive prompt will be shown to select the group.",
            ),
        ] = None,
        output_dir: Annotated[
            Path,
            typer.Option(
                "--output-dir",
                "-o",
                help="Where to dump the group files.",
                allow_dash=True,
            ),
        ] = Path("tmp"),
        clean: Annotated[
            bool,
            typer.Option(
                "--clean",
                "-c",
                help="Delete the output directory before dumping the group.",
            ),
        ] = False,
        verbose: Annotated[
            bool,
            typer.Option(
                "--verbose",
                "-v",
                help="Turn on to get more verbose output when running the command",
            ),
        ] = False,
    ) -> None:
        """This command will dump the selected group as yaml to the folder specified, defaults to /tmp."""
        client = EnvironmentVariables.create_from_environment().get_client()

        cmd = DumpResourceCommand()
        cmd.run(
            lambda: cmd.dump_to_yamls(
                GroupFinder(client, group_name),
                output_dir=output_dir,
                clean=clean,
                verbose=verbose,
            )
        )

    @staticmethod
    def dump_node(
        ctx: typer.Context,
        view_id: Annotated[
            Optional[list[str]],
            typer.Argument(
                help="The view with the node properties you want to dump. Format: space externalId version. Example: 'my_space my_external_id version'. "
                "If nothing is provided, an interactive prompt will be shown to select the view.",
            ),
        ] = None,
        output_dir: Annotated[
            Path,
            typer.Option(
                "--output-dir",
                "-o",
                help="Where to dump the node files.",
                allow_dash=True,
            ),
        ] = Path("tmp"),
        clean: Annotated[
            bool,
            typer.Option(
                "--clean",
                "-c",
                help="Delete the output directory before dumping the node.",
            ),
        ] = False,
        verbose: Annotated[
            bool,
            typer.Option(
                "--verbose",
                "-v",
                help="Turn on to get more verbose output when running the command",
            ),
        ] = False,
    ) -> None:
        """This command will dump the selected node as yaml to the folder specified, defaults to /tmp.
        The intended use case is to dump nodes which are used as configuration. It is not intended to dump
        large amounts of data.
        """
        client = EnvironmentVariables.create_from_environment().get_client()
        selected_view_id: Union[None, ViewId] = None
        if view_id is not None:
            if len(view_id) <= 2:
                raise ToolkitRequiredValueError(
                    "View ID must have at least 2 parts: space, external_id and, optionally, version."
                )
            selected_view_id = ViewId(*view_id)

        cmd = DumpResourceCommand()
        cmd.run(
            lambda: cmd.dump_to_yamls(
                NodeFinder(client, selected_view_id),
                output_dir=output_dir,
                clean=clean,
                verbose=verbose,
            )
        )

    def dump_asset_cmd(
        self,
        ctx: typer.Context,
        hierarchy: Annotated[
            Optional[list[str]],
            typer.Option(
                "--hierarchy",
                "-h",
                help="Hierarchy to dump.",
            ),
        ] = None,
        data_set: Annotated[
            Optional[list[str]],
            typer.Option(
                "--data-set",
                "-d",
                help="Data set to dump. If neither hierarchy nor data set is provided, the user will be prompted"
                "to select which assets to dump",
            ),
        ] = None,
        format_: Annotated[
            str,
            typer.Option(
                "--format",
                "-f",
                help="Format to dump the assets in. Supported formats: yaml, csv, and parquet.",
            ),
        ] = "csv",
        limit: Annotated[
            Optional[int],
            typer.Option(
                "--limit",
                "-l",
                help="Limit the number of assets to dump.",
            ),
        ] = None,
        output_dir: Annotated[
            Path,
            typer.Option(
                "--output-dir",
                "-o",
                help="Where to dump the asset files.",
                allow_dash=True,
            ),
        ] = Path("tmp"),
        clean: Annotated[
            bool,
            typer.Option(
                "--clean",
                "-c",
                help="Delete the output directory before dumping the asset.",
            ),
        ] = False,
        verbose: Annotated[
            bool,
            typer.Option(
                "--verbose",
                "-v",
                help="Turn on to get more verbose output when running the command",
            ),
        ] = False,
    ) -> None:
        """This command will dump the selected assets in the selected format to the folder specified, defaults to /tmp."""
        cmd = DumpAssetsCommand()
        client = EnvironmentVariables.create_from_environment().get_client()
        cmd.run(
            lambda: cmd.execute(
                client,
                hierarchy,
                data_set,
                output_dir,
                clean,
                limit,
                format_,  # type: ignore [arg-type]
                verbose,
            )
        )

    def dump_timeseries_cmd(
        self,
        ctx: typer.Context,
        hierarchy: Annotated[
            Optional[list[str]],
            typer.Option(
                "--hierarchy",
                "-h",
                help="Asset hierarchy (sub-trees) to dump timeseries from.",
            ),
        ] = None,
        data_set: Annotated[
            Optional[list[str]],
            typer.Option(
                "--data-set",
                "-d",
                help="Data set to dump. If neither hierarchy nor data set is provided, the user will be prompted.",
            ),
        ] = None,
        format_: Annotated[
            str,
            typer.Option(
                "--format",
                "-f",
                help="Format to dump the timeseries in. Supported formats: yaml, csv, and parquet.",
            ),
        ] = "csv",
        limit: Annotated[
            Optional[int],
            typer.Option(
                "--limit",
                "-l",
                help="Limit the number of timeseries to dump.",
            ),
        ] = None,
        output_dir: Annotated[
            Path,
            typer.Option(
                "--output-dir",
                "-o",
                help="Where to dump the timeseries files.",
                allow_dash=True,
            ),
        ] = Path("tmp"),
        clean: Annotated[
            bool,
            typer.Option(
                "--clean",
                "-c",
                help="Delete the output directory before dumping the timeseries.",
            ),
        ] = False,
        verbose: Annotated[
            bool,
            typer.Option(
                "--verbose",
                "-v",
                help="Turn on to get more verbose output when running the command",
            ),
        ] = False,
    ) -> None:
        """This command will dump the selected timeseries to the selected format in the folder specified, defaults to /tmp."""
        cmd = DumpTimeSeriesCommand()
        client = EnvironmentVariables.create_from_environment().get_client()
        cmd.run(
            lambda: cmd.execute(
                client,
                data_set,
                hierarchy,
                output_dir,
                clean,
                limit,
                format_,  # type: ignore [arg-type]
                verbose,
            )
        )

    def dump_event_cmd(
        self,
        ctx: typer.Context,
        hierarchy: Annotated[
            Optional[list[str]],
            typer.Option(
                "--hierarchy",
                "-h",
                help="Asset hierarchy (sub-trees) to dump events from.",
            ),
        ] = None,
        data_set: Annotated[
            Optional[list[str]],
            typer.Option(
                "--data-set",
                "-d",
                help="Data set to dump. If neither hierarchy nor data set is provided, the user will be prompted.",
            ),
        ] = None,
        format_: Annotated[
            str,
            typer.Option(
                "--format",
                "-f",
                help="Format to dump the events in. Supported formats: yaml, csv, and parquet.",
            ),
        ] = "csv",
        limit: Annotated[
            Optional[int],
            typer.Option(
                "--limit",
                "-l",
                help="Limit the number of events to dump.",
            ),
        ] = None,
        output_dir: Annotated[
            Path,
            typer.Option(
                "--output-dir",
                "-o",
                help="Where to dump the events files.",
                allow_dash=True,
            ),
        ] = Path("tmp"),
        clean: Annotated[
            bool,
            typer.Option(
                "--clean",
                "-c",
                help="Delete the output directory before dumping the events.",
            ),
        ] = False,
        verbose: Annotated[
            bool,
            typer.Option(
                "--verbose",
                "-v",
                help="Turn on to get more verbose output when running the command",
            ),
        ] = False,
    ) -> None:
        """This command will dump the selected events to the selected format in the folder specified, defaults to /tmp."""
        cmd = DumpEventCommand()
        client = EnvironmentVariables.create_from_environment().get_client()
        cmd.run(
            lambda: cmd.execute(
                client,
                data_set,
                hierarchy,
                output_dir,
                clean,
                limit,
                format_,  # type: ignore [arg-type]
                verbose,
            )
        )

    def dump_filemetadata_cmd(
        self,
        ctx: typer.Context,
        hierarchy: Annotated[
            Optional[list[str]],
            typer.Option(
                "--hierarchy",
                "-h",
                help="Asset hierarchy (sub-trees) to dump file-metadata from.",
            ),
        ] = None,
        data_set: Annotated[
            Optional[list[str]],
            typer.Option(
                "--data-set",
                "-d",
                help="Data set to dump. If neither hierarchy nor data set is provided, the user will be prompted.",
            ),
        ] = None,
        format_: Annotated[
            str,
            typer.Option(
                "--format",
                "-f",
                help="Format to dump the timeseries in. Supported formats: yaml, csv, and parquet.",
            ),
        ] = "csv",
        limit: Annotated[
            Optional[int],
            typer.Option(
                "--limit",
                "-l",
                help="Limit the number of file-metadata to dump.",
            ),
        ] = None,
        output_dir: Annotated[
            Path,
            typer.Option(
                "--output-dir",
                "-o",
                help="Where to dump the file-metadata files.",
                allow_dash=True,
            ),
        ] = Path("tmp"),
        clean: Annotated[
            bool,
            typer.Option(
                "--clean",
                "-c",
                help="Delete the output directory before dumping the file-metadata.",
            ),
        ] = False,
        verbose: Annotated[
            bool,
            typer.Option(
                "--verbose",
                "-v",
                help="Turn on to get more verbose output when running the command",
            ),
        ] = False,
    ) -> None:
        """This command will dump the selected file-metadata to the selected format in the folder specified, defaults to /tmp."""
        cmd = DumpFileMetadataCommand()
        client = EnvironmentVariables.create_from_environment().get_client()
        cmd.run(
            lambda: cmd.execute(
                client,
                data_set,
                hierarchy,
                output_dir,
                clean,
                limit,
                format_,  # type: ignore [arg-type]
                verbose,
            )
        )
