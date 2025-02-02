from abc import ABC, abstractmethod
from collections.abc import Hashable, Iterable, Iterator
from pathlib import Path
from typing import Generic

import questionary
from cognite.client import data_modeling as dm
from cognite.client.data_classes._base import (
    CogniteResourceList,
)
from cognite.client.data_classes.data_modeling import DataModelId
from cognite.client.data_classes.workflows import (
    Workflow,
    WorkflowList,
    WorkflowTriggerList,
    WorkflowVersion,
    WorkflowVersionId,
    WorkflowVersionList,
)
from cognite.client.exceptions import CogniteAPIError
from questionary import Choice
from rich import print
from rich.panel import Panel

from cognite_toolkit._cdf_tk.client import ToolkitClient
from cognite_toolkit._cdf_tk.exceptions import (
    ResourceRetrievalError,
    ToolkitMissingResourceError,
    ToolkitResourceMissingError,
)
from cognite_toolkit._cdf_tk.loaders import (
    ContainerLoader,
    DataModelLoader,
    ResourceLoader,
    SpaceLoader,
    ViewLoader,
    WorkflowLoader,
    WorkflowTriggerLoader,
    WorkflowVersionLoader,
)
from cognite_toolkit._cdf_tk.loaders._base_loaders import T_ID
from cognite_toolkit._cdf_tk.tk_warnings import FileExistsWarning, MediumSeverityWarning
from cognite_toolkit._cdf_tk.utils import humanize_collection
from cognite_toolkit._cdf_tk.utils.file import safe_rmtree, safe_write, yaml_safe_dump

from ._base import ToolkitCommand


class ResourceFinder(Iterable, ABC, Generic[T_ID]):
    def __init__(self, client: ToolkitClient, identifier: T_ID | None = None):
        self.client = client
        self.identifier = identifier

    def _selected(self) -> T_ID:
        return self.identifier or self._interactive_select()

    @abstractmethod
    def __iter__(self) -> Iterator[tuple[list[Hashable], CogniteResourceList | None, ResourceLoader, None | str]]:
        raise NotImplementedError

    @abstractmethod
    def _interactive_select(self) -> T_ID:
        raise NotImplementedError

    @abstractmethod
    def update(self, resources: CogniteResourceList) -> None:
        raise NotImplementedError


class DataModelFinder(ResourceFinder[DataModelId]):
    def __init__(self, client: ToolkitClient, identifier: DataModelId | None = None):
        super().__init__(client, identifier)
        self.data_model: dm.DataModel[dm.ViewId] | None = None
        self.view_ids: set[dm.ViewId] = set()
        self.container_ids: set[dm.ContainerId] = set()
        self.space_ids: set[str] = set()

    def _interactive_select(self) -> DataModelId:
        include_global = False
        spaces = self.client.data_modeling.spaces.list(limit=-1, include_global=include_global)
        selected_space: str = questionary.select(
            "In which space is your data model located?", [space.space for space in spaces]
        ).ask()

        data_model_ids = self.client.data_modeling.data_models.list(
            space=selected_space, all_versions=False, limit=-1, include_global=include_global
        ).as_ids()

        if not data_model_ids:
            raise ToolkitMissingResourceError(f"No data models found in space {selected_space}")

        selected_data_model: DataModelId = questionary.select(
            "Which data model would you like to dump?", [Choice(f"{model!r}", value=model) for model in data_model_ids]
        ).ask()

        data_models = self.client.data_modeling.data_models.list(
            space=selected_space,
            all_versions=True,
            limit=-1,
            include_global=include_global,
            inline_views=False,
        )
        data_model_ids = data_models.as_ids()
        data_model_versions = [
            model.version
            for model in data_model_ids
            if (model.space, model.external_id) == (selected_data_model.space, selected_data_model.external_id)
            and model.version is not None
        ]

        if (
            len(data_model_versions) == 1
            or not questionary.confirm(
                f"Would you like to select a different version than {selected_data_model.version} of the data model",
                default=False,
            ).ask()
        ):
            self.data_model = data_models[0]
            return selected_data_model

        selected_version = questionary.select("Which version would you like to dump?", data_model_versions).ask()
        for model in data_models:
            if model.as_id() == (selected_space, selected_data_model.external_id, selected_version):
                self.data_model = model
                break
        return DataModelId(selected_space, selected_data_model.external_id, selected_version)

    def update(self, resources: CogniteResourceList) -> None:
        if isinstance(resources, dm.DataModelList):
            self.view_ids |= {
                view.as_id() if isinstance(view, dm.View) else view for item in resources for view in item.views
            }
        elif isinstance(resources, dm.ViewList):
            self.container_ids |= resources.referenced_containers()
        elif isinstance(resources, dm.SpaceList):
            return
        self.space_ids |= {item.space for item in resources}

    def __iter__(self) -> Iterator[tuple[list[Hashable], CogniteResourceList | None, ResourceLoader, None | str]]:
        selected = self._selected()
        if self.data_model:
            yield [], dm.DataModelList([self.data_model]), DataModelLoader.create_loader(self.client), None
        else:
            yield [selected], None, DataModelLoader.create_loader(self.client), None
        yield list(self.view_ids), None, ViewLoader.create_loader(self.client), "views"
        yield list(self.container_ids), None, ContainerLoader.create_loader(self.client), "containers"
        yield list(self.space_ids), None, SpaceLoader.create_loader(self.client), None


class WorkflowFinder(ResourceFinder[WorkflowVersionId]):
    def __init__(self, client: ToolkitClient, identifier: WorkflowVersionId | None = None):
        super().__init__(client, identifier)
        self._workflow: Workflow | None = None
        self._workflow_version: WorkflowVersion | None = None

    def _interactive_select(self) -> WorkflowVersionId:
        workflows = self.client.workflows.list(limit=-1)
        if not workflows:
            raise ToolkitMissingResourceError("No workflows found")
        selected_workflow_id: str = questionary.select(
            "Which workflow would you like to dump?",
            [Choice(workflow_id, value=workflow_id) for workflow_id in workflows.as_external_ids()],
        ).ask()
        for workflow in workflows:
            if workflow.external_id == selected_workflow_id:
                self._workflow = workflow
                break

        versions = self.client.workflows.versions.list(selected_workflow_id, limit=-1)
        if len(versions) == 0:
            raise ToolkitMissingResourceError(f"No versions found for workflow {selected_workflow_id}")
        if len(versions) == 1:
            self._workflow_version = versions[0]
            return self._workflow_version.as_id()

        selected_version: WorkflowVersionId = questionary.select(
            "Which version would you like to dump?",
            [Choice(f"{version!r}", value=version) for version in versions.as_ids()],
        ).ask()
        for version in versions:
            if version.version == selected_version.version:
                self._workflow_version = version
                break
        return selected_version

    def update(self, resources: CogniteResourceList) -> None: ...

    def __iter__(self) -> Iterator[tuple[list[Hashable], CogniteResourceList | None, ResourceLoader, None | str]]:
        selected = self._selected()
        if self._workflow:
            yield [], WorkflowList([self._workflow]), WorkflowLoader.create_loader(self.client), None
        else:
            yield [selected.workflow_external_id], None, WorkflowLoader.create_loader(self.client), None
        if self._workflow_version:
            yield (
                [],
                WorkflowVersionList([self._workflow_version]),
                WorkflowVersionLoader.create_loader(self.client),
                None,
            )
        else:
            yield [selected], None, WorkflowVersionLoader.create_loader(self.client), None
        trigger_loader = WorkflowTriggerLoader.create_loader(self.client)
        trigger_list = WorkflowTriggerList(trigger_loader.iterate(parent_ids=[selected.workflow_external_id]))
        yield [], trigger_list, trigger_loader, None


class DumpResourceCommand(ToolkitCommand):
    def dump_to_yamls(
        self,
        finder: ResourceFinder,
        output_dir: Path,
        clean: bool,
        verbose: bool,
    ) -> None:
        is_populated = output_dir.exists() and any(output_dir.iterdir())
        if is_populated and clean:
            safe_rmtree(output_dir)
            output_dir.mkdir()
            self.console(f"Cleaned existing output directory {output_dir!s}.")
        elif is_populated:
            self.warn(MediumSeverityWarning("Output directory is not empty. Use --clean to remove existing files."))
        elif not output_dir.exists():
            output_dir.mkdir(exist_ok=True)

        first_identifier = ""
        for identifiers, resources, loader, subfolder in finder:
            if not identifiers and not resources:
                # No resources to dump
                continue
            if resources is None:
                try:
                    resources = loader.retrieve(identifiers)
                except CogniteAPIError as e:
                    raise ResourceRetrievalError(f"Failed to retrieve {humanize_collection(identifiers)}: {e!s}") from e
                if len(resources) == 0:
                    raise ToolkitResourceMissingError(
                        f"Resource(s) {humanize_collection(identifiers)} not found", str(identifiers)
                    )

            if not first_identifier:
                first_identifier = repr(loader.get_id(resources[0]))
            finder.update(resources)
            resource_folder = output_dir / loader.folder_name
            if subfolder:
                resource_folder = resource_folder / subfolder
            resource_folder.mkdir(exist_ok=True, parents=True)
            for resource in resources:
                name = loader.as_str(loader.get_id(resource))
                filepath = resource_folder / f"{name}.{loader.kind}.yaml"
                if filepath.exists():
                    self.warn(FileExistsWarning(filepath, "Skipping... Use --clean to remove existing files."))
                    continue
                dumped = loader.dump_resource(resource)
                safe_write(filepath, yaml_safe_dump(dumped), encoding="utf-8")
                if verbose:
                    self.console(f"Dumped {loader.kind} {name} to {filepath!s}")

        if first_identifier:
            print(Panel(f"Dumped {first_identifier}", title="Success", style="green", expand=False))
