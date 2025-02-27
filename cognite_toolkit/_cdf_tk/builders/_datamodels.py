import shutil
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from cognite_toolkit._cdf_tk.builders import Builder
from cognite_toolkit._cdf_tk.constants import INDEX_PATTERN
from cognite_toolkit._cdf_tk.data_classes import (
    BuildDestinationFile,
    BuildSourceFile,
    ModuleLocation,
    SourceLocation,
)
from cognite_toolkit._cdf_tk.exceptions import ToolkitFileNotFoundError
from cognite_toolkit._cdf_tk.loaders import GraphQLLoader
from cognite_toolkit._cdf_tk.tk_warnings import ToolkitWarning


class DataModelBuilder(Builder):
    _resource_folder = GraphQLLoader.folder_name

    def build(
        self, source_files: list[BuildSourceFile], module: ModuleLocation, console: Callable[[str], None] | None = None
    ) -> Iterable[BuildDestinationFile | list[ToolkitWarning]]:
        graphql_files = {
            source_file.source.path: source_file
            for source_file in source_files
            if source_file.source.path.suffix == ".graphql"
        }

        for source_file in source_files:
            loaded = source_file.loaded
            if not loaded:
                continue

            loader, warning = self._get_loader(source_file.source.path)
            if not loader:
                if warning:
                    yield [warning]
                continue

            extra_sources: list[SourceLocation] | None = None
            destination_path = self._create_destination_path(source_file.source.path, loader.kind)

            if loader is GraphQLLoader:
                extra_sources = self._copy_graphql_to_build(source_file, destination_path, graphql_files)

            yield BuildDestinationFile(
                path=destination_path,
                loaded=loaded,
                loader=loader,
                source=source_file.source,
                extra_sources=extra_sources,
            )

    def _copy_graphql_to_build(
        self,
        source_file: BuildSourceFile,
        destination_path: Path,
        graphql_files: dict[Path, BuildSourceFile],
    ) -> list[SourceLocation]:
        extra_sources: list[SourceLocation] = []
        loaded_list: list[dict[str, Any]] = (
            source_file.loaded if isinstance(source_file.loaded, list) else [source_file.loaded]  # type: ignore[list-item]
        )

        for entry in loaded_list:
            if "dml" in entry:
                expected_filename = entry["dml"]
            else:
                expected_filename = f"{INDEX_PATTERN.sub('', source_file.source.path.stem.removesuffix(GraphQLLoader.kind).removesuffix('.'))}.graphql"
            expected_path = source_file.source.path.parent / Path(expected_filename)

            if expected_path in graphql_files:
                shutil.copy(graphql_files[expected_path].source.path, destination_path.with_suffix(".graphql"))
                extra_sources.append(graphql_files[expected_path].source)
            else:
                raise ToolkitFileNotFoundError(
                    f"Failed to find GraphQL file. Expected {expected_filename} adjacent to {source_file.source.path.as_posix()}"
                )
        return extra_sources

    def load_extra_field(self, extra: str) -> tuple[str, Any]:
        return "dml", extra
