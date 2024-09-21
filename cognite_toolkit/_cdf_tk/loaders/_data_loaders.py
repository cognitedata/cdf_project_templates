from __future__ import annotations

import io
import re
from collections.abc import Iterable
from pathlib import Path
from typing import final, TYPE_CHECKING, cast

import pandas as pd
import yaml
from cognite.client.data_classes import FileMetadataWrite, FileMetadataWriteList

from cognite_toolkit._cdf_tk.client import ToolkitClient
from cognite_toolkit._cdf_tk.constants import INDEX_PATTERN
from cognite_toolkit._cdf_tk.utils import CDFToolConfig, safe_read

from ._base_loaders import DataLoader
from ._resource_loaders import FileMetadataLoader, RawDatabaseLoader, RawTableLoader, TimeSeriesLoader
from .data_classes import RawDatabaseTable

if TYPE_CHECKING:
    from cognite_toolkit._cdf_tk.data_classes import DeployEnvironment

@final
class DatapointsLoader(DataLoader):
    item_name = "datapoints"
    folder_name = "timeseries"
    kind = "Datapoints"
    filetypes = frozenset({"csv", "parquet"})
    dependencies = frozenset({TimeSeriesLoader})
    _doc_url = "Time-series/operation/postMultiTimeSeriesDatapoints"

    def upload(self, state: DeployEnvironment, ToolGlobals: CDFToolConfig, dry_run: bool) -> Iterable[tuple[str, int]]:
        if datafile.suffix == ".csv":
            # The replacement is used to ensure that we read exactly the same file on Windows and Linux
            file_content = datafile.read_bytes().replace(b"\r\n", b"\n").decode("utf-8")
            data = pd.read_csv(io.StringIO(file_content), parse_dates=True, index_col=0)
            data.index = pd.DatetimeIndex(data.index)
        elif datafile.suffix == ".parquet":
            data = pd.read_parquet(datafile, engine="pyarrow")
        else:
            raise ValueError(f"Unsupported file type {datafile.suffix} for {datafile.name}")
        timeseries_ids = list(data.columns)
        if len(timeseries_ids) == 1:
            ts_str = timeseries_ids[0]
        elif len(timeseries_ids) <= 10:
            ts_str = str(timeseries_ids)
        else:
            ts_str = f"{len(timeseries_ids):,} timeseries"

        if dry_run:
            return (
                f" Would insert '{len(data):,}x{len(data.columns):,}' datapoints from '{datafile!s}' into {ts_str}",
                len(data) * len(data.columns),
            )
        else:
            self.client.time_series.data.insert_dataframe(data)

            return f" Inserted '{len(data):,}x{len(data.columns):,}' datapoints from '{datafile!s}' into {ts_str}", len(
                data
            ) * len(data.columns)


@final
class FileLoader(DataLoader):
    item_name = "file contents"
    folder_name = "files"
    kind = "File"
    filetypes = frozenset()
    exclude_filetypes = frozenset({"yml", "yaml"})
    dependencies = frozenset({FileMetadataLoader})
    _doc_url = "Files/operation/initFileUpload"

    @property
    def display_name(self) -> str:
        return "file contents"

    def __init__(self, client: ToolkitClient, build_dir: Path) -> None:
        super().__init__(client, build_dir)
        self.meta_data_list = FileMetadataWriteList([])
        self.has_loaded_metadata = False

    def upload(self, state: DeployEnvironment, ToolGlobals: CDFToolConfig, dry_run: bool) -> Iterable[tuple[str, int]]:
        if not self.has_loaded_metadata:
            meta_loader = FileMetadataLoader(self.client, self.resource_build_path and self.resource_build_path.parent)
            yaml_files = list(datafile.parent.glob("*.yml")) + list(datafile.parent.glob("*.yaml"))
            for yaml_file in yaml_files:
                loaded = meta_loader.load_resource(yaml_file, ToolGlobals, dry_run)
                if isinstance(loaded, FileMetadataWrite):
                    self.meta_data_list.append(loaded)
                elif isinstance(loaded, FileMetadataWriteList):
                    self.meta_data_list.extend(loaded)
            self.has_loaded_metadata = True
        source_file_name = INDEX_PATTERN.sub("", datafile.name)
        meta_data = next((meta for meta in self.meta_data_list if meta.name == source_file_name), None)
        if meta_data is None:
            raise ValueError(
                f"Missing metadata for file {source_file_name}. Please provide a yaml file with metadata "
                "with an entry with the same name."
            )
        external_id = meta_data.external_id
        if dry_run:
            return f" Would upload file '{datafile!s}' to file with external_id={external_id!r}", 1
        else:
            self.client.files.upload(path=str(datafile), overwrite=True, external_id=external_id)
            return f" Uploaded file '{datafile!s}' to file with external_id={external_id!r}", 1


@final
class RawFileLoader(DataLoader):
    item_name = "rows"
    folder_name = "raw"
    filetypes = frozenset({"csv", "parquet"})
    kind = "Raw"
    dependencies = frozenset({RawDatabaseLoader, RawTableLoader})
    _doc_url = "Raw/operation/postRows"



    @property
    def display_name(self) -> str:
        return "raw.rows"

    def upload(self, state: DeployEnvironment, ToolGlobals: CDFToolConfig, dry_run: bool) -> Iterable[tuple[str, int]]:
        if not self.folder_name in state.deployed_resources:
            return

        for resource in state.deployed_resources[self.folder_name]:
            if resource.kind != RawTableLoader.kind:
                continue
            table = cast(RawDatabaseTable, resource.identifier)
            datafile = next((resource.location.path.with_suffix(f".{file_type}") for file_type in self.filetypes), None)
            if datafile is None:
                # No adjacent data file found
                continue

            if datafile.suffix == ".csv":
                # The replacement is used to ensure that we read exactly the same file on Windows and Linux
                file_content = datafile.read_bytes().replace(b"\r\n", b"\n").decode("utf-8")
                data = pd.read_csv(io.StringIO(file_content), dtype=str)
                data.fillna("", inplace=True)
                if not data.columns.empty and data.columns[0] == "key":
                    print(f"Setting index to 'key' for {datafile.name}")
                    data.set_index("key", inplace=True)
            elif datafile.suffix == ".parquet":
                data = pd.read_parquet(datafile, engine="pyarrow")
            else:
                raise ValueError(f"Unsupported file type {datafile.suffix} for {datafile.name}")

            if data.empty:
                yield (
                    f" No rows to insert from '{datafile!s}' into {table!r}.",
                    0,
                )

            if dry_run:
                yield (
                    f" Would insert {len(data):,} rows of {len(data.columns):,} columns from '{datafile!s}' "
                    f"into {table!r}."
                ), len(data)

            if table.table_name is None:
                # This should never happen
                raise ValueError(f"Missing table name for {datafile.name}")
            self.client.raw.rows.insert_dataframe(
                db_name=table.db_name, table_name=table.table_name, dataframe=data, ensure_parent=False
            )
            yield (
                f" Inserted {len(data):,} rows of {len(data.columns):,} columns from '{datafile!s}' "
                f"into {table!r}."
            ), len(data)
