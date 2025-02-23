from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from typing import Any

from cognite_toolkit._cdf_tk.builders import Builder
from cognite_toolkit._cdf_tk.client.data_classes.raw import RawDatabase
from cognite_toolkit._cdf_tk.data_classes import (
    BuildDestinationFile,
    BuildSourceFile,
    ModuleLocation,
    SourceLocation,
    SourceLocationEager,
)
from cognite_toolkit._cdf_tk.loaders import RawDatabaseLoader, RawTableLoader, ResourceLoader
from cognite_toolkit._cdf_tk.tk_warnings import ToolkitWarning
from cognite_toolkit._cdf_tk.utils import calculate_str_or_file_hash
from cognite_toolkit._cdf_tk.utils.file import yaml_safe_dump


class RawBuilder(Builder):
    _resource_folder = RawDatabaseLoader.folder_name

    def build(
        self,
        source_files: list[BuildSourceFile],
        module: ModuleLocation,
        console: Callable[[str], None] | None = None,
        accept_invalid_files: bool = False,
    ) -> Iterable[BuildDestinationFile | Sequence[ToolkitWarning]]:
        for source_file in source_files:
            loaded = source_file.loaded
            if loaded is None:
                continue
            loaded_list = loaded if isinstance(loaded, list) else [loaded]
            seen_databases: set[tuple] = set()
            entry_by_loader: dict[type[ResourceLoader], list[dict[str, Any]]] = defaultdict(list)
            has_split_table_and_database = False

            for item in loaded_list:
                try:
                    table_id = RawTableLoader.get_id(item)
                except KeyError:
                    seen_databases.add(tuple(item.items()))
                    entry_by_loader[RawDatabaseLoader].append(item)
                else:
                    entry_by_loader[RawTableLoader].append(item)
                    db_item = RawDatabaseLoader.dump_id(RawDatabase(table_id.db_name))
                    hashable_db_item = tuple(db_item.items())
                    if hashable_db_item not in seen_databases:
                        seen_databases.add(hashable_db_item)
                        entry_by_loader[RawDatabaseLoader].append(db_item)
                        has_split_table_and_database = True

            for loader, entries in entry_by_loader.items():
                if not entries:
                    continue
                destination_path = self._create_destination_path(source_file.source.path, loader.kind)

                if loader is RawDatabaseLoader and has_split_table_and_database:
                    # We have inferred the database from a Table file, so we need to recalculate the hash
                    # in case we also inferred the database from another Table file
                    new_hash = calculate_str_or_file_hash(
                        yaml_safe_dump(sorted(entries, key=lambda entry: entry["dbName"])),
                        shorten=True,
                    )
                    source: SourceLocation = SourceLocationEager(path=source_file.source.path, _hash=new_hash)
                else:
                    source = source_file.source

                yield BuildDestinationFile(
                    path=destination_path,
                    loaded=entries,
                    loader=loader,
                    source=source,
                    extra_sources=None,
                )
