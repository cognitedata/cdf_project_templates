from __future__ import annotations

import shutil
from collections import Counter, defaultdict
from collections.abc import Iterator
from itertools import groupby
from pathlib import Path
from typing import Any, Literal, cast

import pandas as pd
import questionary
import yaml
from cognite.client import CogniteClient
from cognite.client.data_classes import AssetList, DataSetWrite, DataSetWriteList
from cognite.client.exceptions import CogniteAPIError

from cognite_toolkit._cdf_tk.commands._base import ToolkitCommand
from cognite_toolkit._cdf_tk.exceptions import (
    ToolkitFileExistsError,
    ToolkitIsADirectoryError,
    ToolkitMissingResourceError,
    ToolkitValueError,
)
from cognite_toolkit._cdf_tk.loaders import DataSetsLoader
from cognite_toolkit._cdf_tk.prototypes.resource_loaders import AssetLoader
from cognite_toolkit._cdf_tk.utils import CDFToolConfig, to_directory_compatible


class DumpAssetsCommand(ToolkitCommand):
    # 128 MB
    filesize = 128 * 1024 * 1024

    def __init__(self, print_warning: bool = True, skip_tracking: bool = False):
        super().__init__(print_warning, skip_tracking)
        self.asset_external_id_by_id: dict[int, str] = {}
        self.data_set_by_id: dict[int, DataSetWrite] = {}
        self._available_data_sets: set[str] | None = None
        self._available_hierarchies: set[str] | None = None

    def execute(
        self,
        ToolGlobals: CDFToolConfig,
        hierarchy: list[str] | None,
        data_set: list[str] | None,
        interactive: bool,
        output_dir: Path,
        clean: bool,
        limit: int | None = None,
        format_: Literal["yaml", "csv", "parquet"] = "yaml",
        verbose: bool = False,
    ) -> None:
        if format_ not in {"yaml", "csv", "parquet"}:
            raise ToolkitValueError(f"Unsupported format {format_}. Supported formats are yaml, csv, parquet.")
        if output_dir.exists() and clean:
            shutil.rmtree(output_dir)
        elif output_dir.exists():
            raise ToolkitFileExistsError(f"Output directory {output_dir!s} already exists. Use --clean to remove it.")
        elif output_dir.suffix:
            raise ToolkitIsADirectoryError(f"Output directory {output_dir!s} is not a directory.")

        hierarchies, data_sets = self._select_hierarchy_and_data_set(
            ToolGlobals.client, hierarchy, data_set, interactive
        )
        if not hierarchies and not data_sets:
            raise ToolkitValueError("No hierarchy or data set provided")

        if missing := set(data_sets) - {item.external_id for item in self.data_set_by_id.values() if item.external_id}:
            try:
                retrieved = ToolGlobals.client.data_sets.retrieve_multiple(external_ids=list(missing))
            except CogniteAPIError as e:
                raise ToolkitMissingResourceError(f"Failed to retrieve data sets {data_sets}: {e}")

            self.data_set_by_id.update({item.id: item.as_write() for item in retrieved if item.id})

        (output_dir / AssetLoader.folder_name).mkdir(parents=True, exist_ok=True)
        (output_dir / DataSetsLoader.folder_name).mkdir(parents=True, exist_ok=True)

        asset_iterator: Iterator[AssetList] = ToolGlobals.client.assets(
            chunk_size=1000,
            asset_subtree_external_ids=hierarchies or None,
            data_set_external_ids=data_set or None,
            limit=limit,
        )
        asset_hierarchies = self._group_by_hierarchy(asset_iterator, ToolGlobals.client)
        writeable = self._to_write(asset_hierarchies, ToolGlobals.client, expand_metadata=True)

        count = 0
        if format_ == "yaml":
            for hierarchy_str, assets in writeable:
                clean_name = to_directory_compatible(hierarchy_str)
                file_path = output_dir / AssetLoader.folder_name / f"{clean_name}.Asset.{format_}"
                if file_path.exists():
                    with file_path.open("a") as f:
                        f.write("\n")
                        f.write(yaml.safe_dump(assets, sort_keys=False))
                else:
                    file_path.write_text(yaml.safe_dump(assets, sort_keys=False))
                count += len(assets)
        elif format_ in {"csv", "parquet"}:
            file_count_by_hierarchy: dict[str, int] = Counter()
            for hierarchy_str, df in self._buffer(writeable):
                folder_path = output_dir / AssetLoader.folder_name / to_directory_compatible(hierarchy_str)
                folder_path.mkdir(parents=True, exist_ok=True)
                file_count = file_count_by_hierarchy[hierarchy_str]
                file_path = folder_path / f"part-{file_count:04}.Asset.{format_}"
                if format_ == "csv":
                    df.to_csv(file_path, index=False)
                elif format_ == "parquet":
                    df.to_parquet(file_path, index=False)
                file_count_by_hierarchy[hierarchy_str] += 1
                if verbose:
                    print(f"Dumped {len(df)} assets in {hierarchy_str} hierarchy to {file_path}")
                count += len(df)
        else:
            raise ToolkitValueError(f"Unsupported format {format_}. Supported formats are yaml, csv, parquet. ")

        print(f"Dumped {count} assets to {output_dir}")

        if self.data_set_by_id:
            to_dump = DataSetWriteList(self.data_set_by_id.values()).dump_yaml()
            file_path = output_dir / DataSetsLoader.folder_name / "hierarchies.DataSet.yaml"
            if file_path.exists():
                with file_path.open("a") as f:
                    f.write("\n")
                    f.write(to_dump)
            else:
                file_path.write_text(to_dump)

            print(f"Dumped {len(self.data_set_by_id)} data sets to {file_path}")

    def _buffer(self, asset_iterator: Iterator[tuple[str, list[dict[str, Any]]]]) -> Iterator[tuple[str, pd.DataFrame]]:
        """Iterates over assets util the buffer reaches the filesize."""
        stored_assets: dict[str, pd.DataFrame] = defaultdict(pd.DataFrame)
        for hierarchy, assets in asset_iterator:
            stored_assets[hierarchy] = pd.concat([stored_assets[hierarchy], pd.DataFrame(assets)], ignore_index=True)
            if stored_assets[hierarchy].memory_usage().sum() > self.filesize:
                yield hierarchy, stored_assets.pop(hierarchy)
        for hierarchy, df in stored_assets.items():
            if not df.empty:
                yield hierarchy, df

    def _select_hierarchy_and_data_set(
        self, client: CogniteClient, hierarchy: list[str] | None, data_set: list[str] | None, interactive: bool
    ) -> tuple[list[str], list[str]]:
        if not interactive:
            return hierarchy or [], data_set or []

        hierarchies: set[str] = set()
        data_sets: set[str] = set()
        while True:
            what = questionary.select(
                f"\nSelected hierarchies: {sorted(hierarchies)}\nSelected dataSets: {sorted(data_sets)}\nSelect a hierarchy or data set to dump",
                choices=[
                    "Hierarchy",
                    "Data Set",
                    "Done",
                ],
            ).ask()

            if what == "Done":
                break
            elif what == "Hierarchy":
                _available_hierarchies = self._get_available_hierarchies(client)
                selected_hierarchy = questionary.checkbox(
                    "Select a hierarchy",
                    choices=sorted(item for item in _available_hierarchies if item not in hierarchies),
                ).ask()
                if selected_hierarchy:
                    hierarchies.update(selected_hierarchy)
                else:
                    print("No hierarchy selected.")
            elif what == "Data Set":
                _available_data_sets = self._get_available_data_sets(client)
                selected_data_set = questionary.checkbox(
                    "Select a data set",
                    choices=sorted(item for item in _available_data_sets if item not in data_sets),
                ).ask()
                if selected_data_set:
                    data_sets.update(selected_data_set)
                else:
                    print("No data set selected.")
        return list(hierarchies), list(data_sets)

    def _get_available_data_sets(self, client: CogniteClient) -> set[str]:
        if self._available_data_sets is None:
            self.data_set_by_id.update({item.id: item.as_write() for item in client.data_sets})
            self._available_data_sets = {item.external_id for item in self.data_set_by_id.values() if item.external_id}
        return self._available_data_sets

    def _get_available_hierarchies(self, client: CogniteClient) -> set[str]:
        if self._available_hierarchies is None:
            self._available_hierarchies = set()
            for item in client.assets(root=True):
                if item.id and item.external_id:
                    self.asset_external_id_by_id[item.id] = item.external_id
                if item.external_id:
                    self._available_hierarchies.add(item.external_id)
        return self._available_hierarchies

    def _group_by_hierarchy(
        self, assets: Iterator[AssetList], client: CogniteClient
    ) -> Iterator[tuple[str, AssetList]]:
        for asset_list in assets:
            for root_id, hierarchy_asset in groupby(sorted(asset_list, key=lambda a: a.root_id), lambda a: a.root_id):
                yield self._get_asset_external_id(client, root_id), AssetList(list(hierarchy_asset))

    def _to_write(
        self, assets: Iterator[tuple[str, AssetList]], client: CogniteClient, expand_metadata: bool
    ) -> Iterator[tuple[str, list[dict[str, Any]]]]:
        for hierarchy, asset_list in assets:
            write_assets: list[dict[str, Any]] = []
            for asset in asset_list:
                write = asset.as_write().dump(camel_case=True)
                write.pop("parentId", None)
                if "dataSetId" in write:
                    data_set_id = write.pop("dataSetId")
                    write["dataSetExternalId"] = self._get_data_set_external_id(client, data_set_id)
                if expand_metadata and "metadata" in write:
                    metadata = write.pop("metadata")
                    for key, value in metadata.items():
                        write[f"metadata.{key}"] = value
                if "rootId" in write:
                    write.pop("rootId")
                    write["rootExternalId"] = hierarchy
                write_assets.append(write)
            yield hierarchy, write_assets

    def _get_asset_external_id(self, client: CogniteClient, root_id: int) -> str:
        if root_id in self.asset_external_id_by_id:
            return self.asset_external_id_by_id[root_id]
        try:
            asset = client.assets.retrieve(id=root_id)
        except CogniteAPIError as e:
            raise ToolkitMissingResourceError(f"Failed to retrieve asset {root_id}: {e}")
        if asset is None:
            raise ToolkitMissingResourceError(f"Asset {root_id} does not exist")
        if not asset.external_id:
            raise ToolkitValueError(f"Asset {root_id} does not have an external id")
        self.asset_external_id_by_id[root_id] = asset.external_id
        return asset.external_id

    def _get_data_set_external_id(self, client: CogniteClient, data_set_id: int) -> str:
        if data_set_id in self.data_set_by_id:
            return cast(str, self.data_set_by_id[data_set_id].external_id)
        try:
            data_set = client.data_sets.retrieve(id=data_set_id)
        except CogniteAPIError as e:
            raise ToolkitMissingResourceError(f"Failed to retrieve data set {data_set_id}: {e}")
        if data_set is None:
            raise ToolkitMissingResourceError(f"Data set {data_set_id} does not exist")
        if not data_set.external_id:
            raise ToolkitValueError(f"Data set {data_set_id} does not have an external id")
        self.data_set_by_id[data_set_id] = data_set.as_write()
        return data_set.external_id
