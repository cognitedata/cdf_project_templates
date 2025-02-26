from __future__ import annotations

import warnings
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, cast

import pandas as pd
import questionary
from cognite.client.data_classes import (
    Asset,
    DataSetWrite,
    DataSetWriteList,
    EventFilter,
    EventList,
)
from cognite.client.data_classes.filters import Equals
from cognite.client.exceptions import CogniteAPIError
from rich.progress import Progress, TaskID, track

from cognite_toolkit._cdf_tk.client import ToolkitClient
from cognite_toolkit._cdf_tk.commands._base import ToolkitCommand
from cognite_toolkit._cdf_tk.exceptions import (
    ToolkitFileExistsError,
    ToolkitIsADirectoryError,
    ToolkitMissingResourceError,
    ToolkitValueError,
)
from cognite_toolkit._cdf_tk.loaders import DataSetsLoader, EventLoader
from cognite_toolkit._cdf_tk.utils.file import safe_rmtree, yaml_safe_dump

EVENT_FOLDER_NAME = EventLoader.folder_name


class DumpEventCommand(ToolkitCommand):
    # 128 MB
    buffer_size = 128 * 1024 * 1024
    # Note the size in memory is not the same as the size on disk,
    # so the resulting file size will vary.
    encoding = "utf-8"
    newline = "\n"

    def __init__(self, print_warning: bool = True, skip_tracking: bool = False):
        super().__init__(print_warning, skip_tracking)
        self.asset_external_id_by_id: dict[int, str] = {}
        self.events_external_id_by_id: dict[int, str] = {}
        self.data_set_by_id: dict[int, DataSetWrite] = {}

        self.asset_by_id: dict[int, str] = {}
        self._used_assets: set[int] = set()

        self._used_data_sets: set[int] = set()
        self._available_data_sets: dict[int, DataSetWrite] | None = None
        self._available_hierarchies: dict[int, Asset] | None = None

        self._written_files: list[Path] = []
        self._used_columns: set[str] = set()

    def execute(
        self,
        client: ToolkitClient,
        data_set: list[str] | None,
        hierarchy: list[str] | None,
        output_dir: Path,
        clean: bool,
        limit: int | None = None,
        format_: Literal["yaml", "csv", "parquet"] = "csv",
        verbose: bool = False,
    ) -> None:
        if format_ not in {"yaml", "csv", "parquet"}:
            raise ToolkitValueError(f"Unsupported format {format_}. Supported formats are yaml, csv, parquet.")
        if output_dir.exists() and clean:
            safe_rmtree(output_dir)
        elif output_dir.exists():
            raise ToolkitFileExistsError(f"Output directory {output_dir!s} already exists. Use --clean to remove it.")
        elif output_dir.suffix:
            raise ToolkitIsADirectoryError(f"Output directory {output_dir!s} is not a directory.")
        is_interactive = hierarchy is None and data_set is None
        hierarchies, data_sets = self._select_data_set(client, hierarchy, data_set, is_interactive)
        if not hierarchies and not data_sets:
            raise ToolkitValueError("No hierarchy or data set provided")

        if missing := set(data_sets) - {item.external_id for item in self.data_set_by_id.values() if item.external_id}:
            try:
                retrieved = client.data_sets.retrieve_multiple(external_ids=list(missing))
            except CogniteAPIError as e:
                raise ToolkitMissingResourceError(f"Failed to retrieve data sets {data_sets}: {e}")

            self.data_set_by_id.update({item.id: item.as_write() for item in retrieved if item.id})

        (output_dir / EVENT_FOLDER_NAME).mkdir(parents=True, exist_ok=True)

        total_events = client.events.aggregate_count(
            filter=EventFilter(
                data_set_ids=[{"externalId": item} for item in data_sets] or None,
                asset_subtree_ids=[{"externalId": item} for item in hierarchies] or None,
            )
        )
        if limit:
            total_events = min(total_events, limit)

        with Progress() as progress:
            retrieved_events = progress.add_task("Retrieving events", total=total_events)
            write_to_file = progress.add_task("Writing events to file(s)", total=total_events)

            events_iterator = client.events(
                chunk_size=1000,
                data_set_external_ids=data_sets or None,
                asset_subtree_external_ids=hierarchies or None,
                limit=limit,
            )
            events_iterator = self._log_retrieved(events_iterator, progress, retrieved_events)
            writeable = self._to_write(events_iterator, client, expand_metadata=True)

            count = 0
            if format_ == "yaml":
                for events in writeable:
                    file_path = output_dir / EVENT_FOLDER_NAME / f"Event.{format_}"
                    if file_path.exists():
                        with file_path.open("a", encoding=self.encoding, newline=self.newline) as f:
                            f.write("\n")
                            f.write(yaml_safe_dump(events))
                    else:
                        with file_path.open("w", encoding=self.encoding, newline=self.newline) as f:
                            f.write(yaml_safe_dump(events))
                    count += len(events)
                    progress.advance(write_to_file, advance=len(events))
            elif format_ in {"csv", "parquet"}:
                file_count: int = 0  # Counter()
                for df in self._buffer(writeable):
                    folder_path = output_dir / EVENT_FOLDER_NAME
                    folder_path.mkdir(parents=True, exist_ok=True)
                    file_path = folder_path / f"part-{file_count:04}.Event.{format_}"
                    # Standardize column order
                    df.sort_index(axis=1, inplace=True)
                    if format_ == "csv":
                        df.to_csv(
                            file_path,
                            index=False,
                            encoding=self.encoding,
                            lineterminator=self.newline,
                        )
                    elif format_ == "parquet":
                        df.to_parquet(file_path, index=False)
                    file_count += 1
                    if verbose:
                        print(f"Dumped {len(df):,} events to {file_path}")
                    count += len(df)
                    self._written_files.append(file_path)
                    self._used_columns.update(df.columns)
                    progress.advance(write_to_file, advance=len(df))
            else:
                raise ToolkitValueError(f"Unsupported format {format_}. Supported formats are yaml, csv, parquet. ")

        if format_ in {"csv", "parquet"} and len(self._written_files) > 1:
            # Standardize columns across all files
            for file_path in track(
                self._written_files, total=len(self._written_files), description="Standardizing columns"
            ):
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    if format_ == "csv":
                        df = pd.read_csv(file_path, encoding=self.encoding, lineterminator=self.newline)
                    else:
                        df = pd.read_parquet(file_path)
                for missing_column in self._used_columns - set(df.columns):
                    df[missing_column] = None
                # Standardize column order
                df.sort_index(axis=1, inplace=True)
                if format_ == "csv":
                    df.to_csv(file_path, index=False, encoding=self.encoding, lineterminator=self.newline)
                elif format_ == "parquet":
                    df.to_parquet(file_path, index=False)

        print(f"Dumped {count:,} events to {output_dir}")

        if self._used_data_sets:
            used_datasets = DataSetWriteList(
                [self.data_set_by_id[used_dataset] for used_dataset in self._used_data_sets]
            )
            to_dump = used_datasets.dump_yaml()
            file_path = output_dir / DataSetsLoader.folder_name / "events.DataSet.yaml"
            file_path.parent.mkdir(parents=True, exist_ok=True)
            if file_path.exists():
                with file_path.open("a", encoding=self.encoding, newline=self.newline) as f:
                    f.write("\n")
                    f.write(to_dump)
            else:
                with file_path.open("w", encoding=self.encoding, newline=self.newline) as f:
                    f.write(to_dump)

            print(f"Dumped {len(used_datasets):,} data sets to {file_path}")

    def _buffer(self, events_iterator: Iterator[list[dict[str, Any]]]) -> Iterator[pd.DataFrame]:
        """Iterates over events until the buffer reaches the filesize."""
        stored_events = pd.DataFrame()
        for events in events_iterator:
            stored_events = pd.concat(
                [stored_events, pd.DataFrame(events)],
                ignore_index=True,
            )
            if stored_events.memory_usage().sum() > self.buffer_size:
                yield stored_events
                # reset of the buffer required
                stored_events = pd.DataFrame()
        if not stored_events.empty:
            yield stored_events

    @lru_cache
    def get_timeseries_choice_count_by_dataset(self, item_id: int, client: ToolkitClient) -> int:
        """Using LRU decorator w/o limit instead of another lookup map."""
        return client.events.aggregate_count(advanced_filter=Equals("dataSetId", item_id))

    @lru_cache
    def get_timeseries_choice_count_by_root_id(self, item_id: int, client: ToolkitClient) -> int:
        """Using LRU decorator w/o limit instead of another lookup map."""
        return client.events.aggregate_count(filter=EventFilter(asset_subtree_ids=[{"id": item_id}]))

    def _create_choice(self, item_id: int, item: Asset | DataSetWrite, client: ToolkitClient) -> questionary.Choice:
        """
        Choice with `title` including name and external_id if they differ.
        Adding `value` as external_id for the choice.
        `item_id` and `item` came in separate as item is DataSetWrite w/o `id`.
        """

        if isinstance(item, DataSetWrite):
            ts_count = self.get_timeseries_choice_count_by_dataset(item_id, client)
        elif isinstance(item, Asset):
            ts_count = self.get_timeseries_choice_count_by_root_id(item_id, client)
        else:
            raise TypeError(f"Unsupported item type: {type(item)}")

        return questionary.Choice(
            title=f"{item.name} ({item.external_id}) [{ts_count:,}]"
            if item.name != item.external_id
            else f"({item.external_id}) [{ts_count:,}]",
            value=item.external_id,
        )

    def _get_choice_title(self, choice: str | questionary.Choice | dict[str, Any]) -> str:
        """
        Accommodates for the fact that the choice, string or a dict, when `sorted(key=..)` is called.
        So assert confirm the type of the choice and choice.title and then return the title.
        """
        assert isinstance(choice, questionary.Choice)
        assert isinstance(choice.title, str)  # minimum external_id is set
        return choice.title.casefold()  # superior to lower case like `ß>ss` in German

    def _select_data_set(
        self,
        client: ToolkitClient,
        hierarchy: list[str] | None,
        data_set: list[str] | None,
        interactive: bool,
    ) -> tuple[list[str], list[str]]:
        if not interactive:
            return hierarchy or [], data_set or []

        hierarchies: set[str] = set()
        data_sets: set[str] = set()
        while True:
            selected = []
            if hierarchies:
                selected.append(f"Selected hierarchies: {sorted(hierarchies)}")
            else:
                selected.append("No hierarchy selected.")
            if data_sets:
                selected.append(f"Selected data sets: {sorted(data_sets)}")
            else:
                selected.append("No data set selected.")
            selected_str = "\n".join(selected)
            what = questionary.select(
                f"\n{selected_str}\nSelect a hierarchy or data set to dump",
                choices=["Hierarchy", "Data Set", "Done", "Abort"],
            ).ask()

            if what == "Done":
                break
            elif what == "Abort":
                return [], []
            elif what == "Hierarchy":
                _available_hierarchies = self._get_available_hierarchies(client)
                selected_hierarchy = questionary.checkbox(
                    "Select a hierarchy listed as 'name (external_id) [count]'",
                    choices=sorted(
                        [
                            self._create_choice(item_id, item, client)
                            for (item_id, item) in _available_hierarchies.items()
                            if item.external_id not in hierarchies
                        ],
                        key=self._get_choice_title,
                        # sorted cannot find the proper overload
                    ),  # type: ignore
                ).ask()
                if selected_hierarchy:
                    hierarchies.update(selected_hierarchy)
                else:
                    print("No hierarchy selected.")
            elif what == "Data Set":
                _available_data_sets = self._get_available_data_sets(client)
                selected_data_set = questionary.checkbox(
                    "Select a data set listed as 'name (external_id) [count]'",
                    choices=sorted(
                        [
                            self._create_choice(item_id, item, client)
                            for (item_id, item) in _available_data_sets.items()
                            if item.external_id not in data_sets
                        ],
                        # sorted cannot find the proper overload
                        key=self._get_choice_title,
                    ),  # type: ignore
                ).ask()
                if selected_data_set:
                    data_sets.update(selected_data_set)
                else:
                    print("No data set selected.")
        return list(hierarchies), list(data_sets)

    def _get_available_data_sets(self, client: ToolkitClient) -> dict[int, DataSetWrite]:
        if self._available_data_sets is None:
            self.data_set_by_id.update({item.id: item.as_write() for item in client.data_sets})
            # filter out data sets without external_id
            self._available_data_sets = {
                item_id: item for (item_id, item) in self.data_set_by_id.items() if item.external_id
            }
        return self._available_data_sets

    def _get_available_hierarchies(self, client: ToolkitClient) -> dict[int, Asset]:
        if self._available_hierarchies is None:
            self._available_hierarchies = {}
            for item in client.assets(root=True):
                if item.id and item.external_id:
                    self.asset_external_id_by_id[item.id] = item.external_id
                if item.external_id:
                    self._available_hierarchies.update({item.id: item})
        return self._available_hierarchies

    def _to_write(
        self,
        events_lists: Iterator[EventList],
        client: ToolkitClient,
        expand_metadata: bool,
    ) -> Iterator[list[Any]]:
        for events_list in events_lists:
            write_events: list[dict[str, Any]] = []
            for events in events_list:
                write = events.as_write().dump(camel_case=True)
                if "dataSetId" in write:
                    data_set_id = write.pop("dataSetId")
                    self._used_data_sets.add(data_set_id)
                    write["dataSetExternalId"] = self._get_data_set_external_id(client, data_set_id)
                if "assetId" in write:
                    asset_id = write.pop("assetId")
                    self._used_assets.add(asset_id)
                    write["assetExternalId"] = self._get_asset_external_id(client, asset_id)
                if expand_metadata and "metadata" in write:
                    metadata = write.pop("metadata")
                    for key, value in metadata.items():
                        write[f"metadata.{key}"] = value
                write_events.append(write)
            yield write_events

    def _get_events_external_id(self, client: ToolkitClient, root_id: int) -> str:
        if root_id in self.events_external_id_by_id:
            return self.events_external_id_by_id[root_id]
        try:
            events = client.events.retrieve(id=root_id)
        except CogniteAPIError as e:
            raise ToolkitMissingResourceError(f"Failed to retrieve events {root_id}: {e}")
        if events is None:
            raise ToolkitMissingResourceError(f"Event {root_id} does not exist")
        if not events.external_id:
            raise ToolkitValueError(f"Event {root_id} does not have an external id")
        self.events_external_id_by_id[root_id] = events.external_id
        return events.external_id

    def _get_data_set_external_id(self, client: ToolkitClient, data_set_id: int) -> str:
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

    def _get_asset_external_id(self, client: ToolkitClient, asset_id: int) -> str:
        if asset_id in self.asset_by_id:
            return self.asset_by_id[asset_id]
        try:
            asset = client.assets.retrieve(id=asset_id)
        except CogniteAPIError as e:
            raise ToolkitMissingResourceError(f"Failed to retrieve data set {asset_id}: {e}")
        if asset is None:
            raise ToolkitMissingResourceError(f"Data set {asset_id} does not exist")
        if not asset.external_id:
            raise ToolkitValueError(f"Data set {asset_id} does not have an external id")
        self.asset_by_id[asset_id] = asset.external_id
        return asset.external_id

    @staticmethod
    def _log_retrieved(events_iterator: Iterator[EventList], progress: Progress, task: TaskID) -> Iterator[EventList]:
        for events_list in events_iterator:
            progress.advance(task, advance=len(events_list))
            yield events_list
