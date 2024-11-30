from __future__ import annotations

import uuid
from collections.abc import Hashable
from graphlib import TopologicalSorter

import questionary
from cognite.client.data_classes import DataSetUpdate
from rich import print

from cognite_toolkit._cdf_tk.client import ToolkitClient
from cognite_toolkit._cdf_tk.data_classes import DeployResults, ResourceDeployResult
from cognite_toolkit._cdf_tk.exceptions import ToolkitMissingResourceError, ToolkitValueError
from cognite_toolkit._cdf_tk.loaders import (
    RESOURCE_LOADER_LIST,
    DataSetsLoader,
    FunctionLoader,
    GraphQLLoader,
    GroupAllScopedLoader,
    GroupLoader,
    GroupResourceScopedLoader,
    HostedExtractorDestinationLoader,
    ResourceLoader,
    SpaceLoader,
    StreamlitLoader,
)
from cognite_toolkit._cdf_tk.utils import CDFToolConfig

from ._base import ToolkitCommand


class PurgeCommand(ToolkitCommand):
    def space(
        self,
        ToolGlobals: CDFToolConfig,
        space: str | None = None,
        include_space: bool = False,
        dry_run: bool = False,
        verbose: bool = False,
    ) -> None:
        """Purge a space and all its content"""
        selected_space = self._get_selected_space(space, ToolGlobals.toolkit_client)
        if space is None:
            # Interactive mode
            include_space = questionary.confirm(
                "Do you want to delete the space itself after the purge?", default=False
            ).ask()
            dry_run = questionary.confirm("Dry run?", default=True).ask()

        loaders = self._get_dependencies(SpaceLoader, exclude={GraphQLLoader})
        self._purge(ToolGlobals, loaders, selected_space, dry_run=dry_run, verbose=verbose)
        if include_space:
            space_loader = SpaceLoader.create_loader(ToolGlobals, None)
            if dry_run:
                print(f"Would delete space {selected_space}")
            else:
                space_loader.delete([selected_space])
                print(f"Space {selected_space} deleted")

        if not dry_run:
            print(f"Purge space {selected_space!r} completed.")

    @staticmethod
    def _get_dependencies(
        loader_cls: type[ResourceLoader], exclude: set[type[ResourceLoader]] | None = None
    ) -> dict[type[ResourceLoader], frozenset[type[ResourceLoader]]]:
        return {
            dep_cls: dep_cls.dependencies
            for dep_cls in RESOURCE_LOADER_LIST
            if loader_cls in dep_cls.dependencies and (exclude is None or dep_cls not in exclude)
        }

    @staticmethod
    def _get_selected_space(space: str | None, client: ToolkitClient) -> str:
        if space is None:
            spaces = client.data_modeling.spaces.list(limit=-1, include_global=False)
            selected_space = questionary.select(
                "Which space are you going to purge"
                " (delete all data models, views, containers, nodes and edges in space)?",
                [space.space for space in spaces],
            ).ask()
        else:
            retrieved = client.data_modeling.spaces.retrieve(space)
            if retrieved is None:
                raise ToolkitMissingResourceError(f"Space {space} does not exist")
            selected_space = space

        if selected_space is None:
            raise ToolkitValueError("No space selected")
        return selected_space

    def dataset(
        self,
        ToolGlobals: CDFToolConfig,
        external_id: str | None = None,
        include_dataset: bool = False,
        dry_run: bool = False,
        verbose: bool = False,
    ) -> None:
        """Purge a dataset and all its content"""
        selected_dataset = self._get_selected_dataset(external_id, ToolGlobals.toolkit_client)
        if external_id is None:
            # Interactive mode
            include_dataset = questionary.confirm(
                "Do you want to archive the dataset itself after the purge?", default=False
            ).ask()
            dry_run = questionary.confirm("Dry run?", default=True).ask()

        loaders = self._get_dependencies(
            DataSetsLoader,
            exclude={
                GroupLoader,
                GroupResourceScopedLoader,
                GroupAllScopedLoader,
                StreamlitLoader,
                HostedExtractorDestinationLoader,
                FunctionLoader,
            },
        )
        self._purge(ToolGlobals, loaders, selected_data_set=selected_dataset, dry_run=dry_run, verbose=verbose)
        if include_dataset:
            if dry_run:
                print(f"Would have archived {selected_dataset}")
            else:
                archived = (
                    DataSetUpdate(external_id=selected_dataset)
                    .external_id.set(uuid.uuid4())
                    .metadata.add({"archived": "true"})
                    .write_protected.set(True)
                )
                ToolGlobals.toolkit_client.data_sets.update(archived)
                print(f"DataSet {selected_dataset} archived")

        if not dry_run:
            print(f"Purged dataset {selected_dataset!r} completed")

    @staticmethod
    def _get_selected_dataset(external_id: str | None, client: ToolkitClient) -> str:
        if external_id is None:
            datasets = client.data_sets.list(limit=-1)
            selected_dataset: str = questionary.select(
                "Which space are you going to purge" " (delete all resources in dataset)?",
                [dataset.external_id for dataset in datasets if dataset.external_id],
            ).ask()
        else:
            retrieved = client.data_sets.retrieve(external_id=external_id)
            if retrieved is None:
                raise ToolkitMissingResourceError(f"DataSet {external_id!r} does not exist")
            selected_dataset = external_id

        if selected_dataset is None:
            raise ToolkitValueError("No space selected")
        return selected_dataset

    def _purge(
        self,
        ToolGlobals: CDFToolConfig,
        loaders: dict[type[ResourceLoader], frozenset[type[ResourceLoader]]],
        selected_space: str | None = None,
        selected_data_set: str | None = None,
        dry_run: bool = False,
        verbose: bool = False,
        batch_size: int = 1000,
    ) -> None:
        results = DeployResults([], "purge", dry_run=dry_run)
        loader_cls: type[ResourceLoader]
        for loader_cls in reversed(list(TopologicalSorter(loaders).static_order())):
            if loader_cls not in loaders:
                # Dependency that is included
                continue
            loader = loader_cls.create_loader(ToolGlobals, None)
            # Child loaders are, for example, WorkflowTriggerLoader, WorkflowVersionLoader for WorkflowLoader
            # These must delete all resources that are connected to the resource that the loader is deleting
            # Exclude loaders that we are already iterating over
            child_loader_classes = self._get_dependencies(loader_cls, exclude=set(loaders))
            child_loaders = [
                child_loader.create_loader(ToolGlobals, None)
                for child_loader in reversed(list(TopologicalSorter(child_loader_classes).static_order()))
                # Necessary as the toplogical sort includes dependencies that are not in the loaders
                if child_loader in child_loader_classes
            ]
            count = 0
            batch_ids: list[Hashable] = []
            for resource in loader.iterate(data_set_external_id=selected_data_set, space=selected_space):
                batch_ids.append(loader.get_id(resource))
                if len(batch_ids) >= batch_size:
                    child_deletion = self._delete_children(batch_ids, child_loaders, dry_run, verbose)
                    count += self._delete_batch(batch_ids, dry_run, loader, verbose)
                    batch_ids = []
                    # The DeployResults is overloaded such that the below accumulates the counts
                    for name, child_count in child_deletion.items():
                        results[name] = ResourceDeployResult(name, deleted=child_count, total=child_count)

            if batch_ids:
                child_deletion = self._delete_children(batch_ids, child_loaders, dry_run, verbose)
                count += self._delete_batch(batch_ids, dry_run, loader, verbose)
                for name, child_count in child_deletion.items():
                    results[name] = ResourceDeployResult(name, deleted=child_count, total=child_count)

            results[loader.display_name] = ResourceDeployResult(
                name=loader.display_name,
                deleted=count,
                total=count,
            )
        print(results.counts_table())

    @staticmethod
    def _delete_batch(batch_ids: list[Hashable], dry_run: bool, loader: ResourceLoader, verbose: bool) -> int:
        if dry_run:
            deleted = len(batch_ids)
        else:
            deleted = loader.delete(batch_ids)

        if verbose:
            prefix = "Would delete" if dry_run else "Deleted"
            print(f"{prefix} {deleted:,} {loader.display_name}")
        return deleted

    @staticmethod
    def _delete_children(
        parent_ids: list[Hashable], child_loaders: list[ResourceLoader], dry_run: bool, verbose: bool
    ) -> dict[str, int]:
        child_deletion: dict[str, int] = {}
        for child_loader in child_loaders:
            child_ids = set()
            for child in child_loader.iterate(parent_ids=parent_ids):
                child_ids.add(child_loader.get_id(child))
            count = 0
            if child_ids:
                if dry_run:
                    count = len(child_ids)
                else:
                    count = child_loader.delete(list(child_ids))

                if verbose:
                    prefix = "Would delete" if dry_run else "Deleted"
                    print(f"{prefix} {count:,} {child_loader.display_name}")
            child_deletion[child_loader.display_name] = count
        return child_deletion
