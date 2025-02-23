import copy
from collections.abc import Callable, Iterable
from typing import Any

from cognite_toolkit._cdf_tk.builders import Builder
from cognite_toolkit._cdf_tk.data_classes import (
    BuildDestinationFile,
    BuildSourceFile,
    ModuleLocation,
)
from cognite_toolkit._cdf_tk.exceptions import ToolkitYAMLFormatError
from cognite_toolkit._cdf_tk.loaders import CogniteFileLoader, FileLoader, FileMetadataLoader
from cognite_toolkit._cdf_tk.tk_warnings import LowSeverityWarning, ToolkitWarning


class FileBuilder(Builder):
    _resource_folder = FileMetadataLoader.folder_name
    template_pattern = "$FILENAME"

    def build(
        self,
        source_files: list[BuildSourceFile],
        module: ModuleLocation,
        console: Callable[[str], None] | None = None,
        accept_invalid_files: bool = False,
    ) -> Iterable[BuildDestinationFile | list[ToolkitWarning]]:
        for source_file in source_files:
            loaded = source_file.loaded
            if loaded is None:
                continue

            loader, warning = self._get_loader(source_file.source.path)
            if loader is None:
                if warning is not None:
                    yield [warning]
                continue
            if loader in {FileMetadataLoader, CogniteFileLoader}:
                loaded = self._expand_file_metadata(loaded, module, console)
            destination_path = self._create_destination_path(source_file.source.path, loader.kind)

            yield BuildDestinationFile(
                path=destination_path,
                loaded=loaded,
                loader=loader,
                source=source_file.source,
                extra_sources=None,
            )

    @classmethod
    def _expand_file_metadata(
        cls,
        raw_list: list[dict[str, Any]] | dict[str, Any],
        module: ModuleLocation,
        console: Callable[[str], None] | None = None,
    ) -> list[dict[str, Any]] | dict[str, Any]:
        is_file_template = (
            isinstance(raw_list, list)
            and len(raw_list) == 1
            and cls.template_pattern in raw_list[0].get("externalId", "")
        )
        if not is_file_template:
            if (isinstance(raw_list, dict) and cls.template_pattern in raw_list.get("externalId", "")) or (
                isinstance(raw_list, list)
                and any(cls.template_pattern in entry.get("externalId", "") for entry in raw_list)
            ):
                raw_type = "dictionary" if isinstance(raw_list, dict) else "list with multiple entries"
                LowSeverityWarning(
                    f"Invalid file template {cls.template_pattern!r} usage detected in {module.relative_path.as_posix()!r}.\n"
                    f"The file template is expected in a list with a single entry, but got {raw_type}."
                ).print_warning()

            return raw_list
        if not (isinstance(raw_list, list) and raw_list and isinstance(raw_list[0], dict)):
            raise ToolkitYAMLFormatError(
                f"Expected a list with a single dictionary in the file metadata file {module.dir}, "
                f"but got {type(raw_list).__name__}"
            )
        template = raw_list[0]
        if console:
            console(
                f"Detected file template name {cls.template_pattern!r} in {module.relative_path.as_posix()!r}"
                f"Expanding file metadata..."
            )
        expanded_metadata: list[dict[str, Any]] = []
        for filepath in module.source_paths_by_resource_folder[FileLoader.folder_name]:
            if not FileLoader.is_supported_file(filepath):
                continue
            new_entry = copy.deepcopy(template)
            new_entry["externalId"] = new_entry["externalId"].replace(cls.template_pattern, filepath.name)
            new_entry["name"] = filepath.name
            expanded_metadata.append(new_entry)
        return expanded_metadata
