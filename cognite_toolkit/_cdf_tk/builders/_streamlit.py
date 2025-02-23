import shutil
from collections.abc import Callable, Iterable, Sequence

from cognite_toolkit._cdf_tk.builders import Builder
from cognite_toolkit._cdf_tk.data_classes import (
    BuildDestinationFile,
    BuildSourceFile,
    ModuleLocation,
)
from cognite_toolkit._cdf_tk.exceptions import ToolkitFileExistsError, ToolkitNotADirectoryError, ToolkitValueError
from cognite_toolkit._cdf_tk.loaders import StreamlitLoader
from cognite_toolkit._cdf_tk.tk_warnings import (
    FileReadWarning,
    HighSeverityWarning,
    ToolkitWarning,
    WarningList,
)


class StreamlitBuilder(Builder):
    _resource_folder = StreamlitLoader.folder_name

    def build(
        self,
        source_files: list[BuildSourceFile],
        module: ModuleLocation,
        console: Callable[[str], None] | None = None,
        accept_invalid_files: bool = False,
    ) -> Iterable[BuildDestinationFile | Sequence[ToolkitWarning]]:
        for source_file in source_files:
            if source_file.loaded is None:
                continue
            if source_file.source.path.parent.parent != module.dir:
                # Streamlit YAML files must be in the resource folder top level
                continue

            loader, warning = self._get_loader(source_file.source.path)
            if loader is None:
                if warning is not None:
                    yield [warning]
                continue

            warnings = WarningList[FileReadWarning]()
            if loader is StreamlitLoader:
                warnings = self.copy_app_directory_to_build(source_file)

            destination_path = self._create_destination_path(source_file.source.path, loader.kind)

            yield BuildDestinationFile(
                path=destination_path,
                loaded=source_file.loaded,
                loader=loader,
                source=source_file.source,
                extra_sources=None,
                warnings=warnings,
            )

    def copy_app_directory_to_build(self, source_file: BuildSourceFile) -> WarningList[FileReadWarning]:
        raw_content = source_file.loaded
        if raw_content is None:
            # This should already be checked before calling this method.
            raise ToolkitValueError("Streamlit source file should be a YAML file.")
        raw_apps = raw_content if isinstance(raw_content, list) else [raw_content]
        warnings = WarningList[FileReadWarning]()
        for raw_app in raw_apps:
            external_id = raw_app.get("externalId")
            if not external_id:
                warnings.append(
                    HighSeverityWarning(
                        f"StreamlitApp in {source_file.source.path.as_posix()!r} has no externalId defined. "
                        f"This is used to match the Streamlit App to directory."
                    )
                )
                continue
            app_directory = source_file.source.path.with_name(external_id)

            if not app_directory.is_dir():
                raise ToolkitNotADirectoryError(
                    f"StreamlitApp directory not found in {app_directory}(based on externalId {external_id} defined in {source_file.source.path.as_posix()!r}.)"
                )

            destination = self.build_dir / self.resource_folder / external_id
            if destination.exists():
                raise ToolkitFileExistsError(
                    f"StreamlitApp {external_id!r} is duplicated. If this is unexpected, ensure you have a clean build directory."
                )
            shutil.copytree(app_directory, destination, ignore=shutil.ignore_patterns("__pycache__"))

        return warnings
