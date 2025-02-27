import difflib
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any, ClassVar, cast

from cognite_toolkit._cdf_tk.constants import INDEX_PATTERN
from cognite_toolkit._cdf_tk.data_classes import (
    BuildDestinationFile,
    BuildSourceFile,
    BuiltResourceList,
    ModuleLocation,
)
from cognite_toolkit._cdf_tk.exceptions import (
    AmbiguousResourceFileError,
)
from cognite_toolkit._cdf_tk.loaders import (
    LOADER_BY_FOLDER_NAME,
    GroupLoader,
    RawDatabaseLoader,
    RawTableLoader,
    ResourceLoader,
)
from cognite_toolkit._cdf_tk.tk_warnings import (
    ToolkitNotSupportedWarning,
    ToolkitWarning,
    WarningList,
)
from cognite_toolkit._cdf_tk.tk_warnings.fileread import (
    UnknownResourceTypeWarning,
)
from cognite_toolkit._cdf_tk.utils import (
    humanize_collection,
    safe_read,
)


class Builder(ABC):
    _resource_folder: ClassVar[str | None] = None

    def __init__(
        self,
        build_dir: Path | None,
        resource_folder: str | None = None,
    ):
        self._build_dir = build_dir
        self.resource_counter = 0
        if self._resource_folder is not None:
            self.resource_folder = self._resource_folder
        elif resource_folder is not None:
            self.resource_folder = resource_folder
        else:
            raise ValueError("Either _resource_folder or resource_folder must be set.")

    @property
    def build_dir(self) -> Path:
        if self._build_dir is None:
            raise ValueError("build_dir must be set for this operation.")
        return self._build_dir

    @abstractmethod
    def build(
        self,
        source_files: list[BuildSourceFile],
        module: ModuleLocation,
        console: Callable[[str], None] | None = None,
    ) -> Iterable[BuildDestinationFile | Sequence[ToolkitWarning]]:
        raise NotImplementedError()

    def load_extra_field(self, extra: str) -> tuple[str, Any]:
        """Overload in subclass to load extra fields from a file."""
        raise NotImplementedError(
            f"Extra field {extra!r} by {type(self).__name__} - {self.resource_folder} is not supported."
        )

    def validate_directory(
        self, built_resources: BuiltResourceList, module: ModuleLocation
    ) -> WarningList[ToolkitWarning]:
        """This can be overridden to add additional validation for the built resources."""
        return WarningList[ToolkitWarning]()

    # Helper methods
    def _create_destination_path(self, source_path: Path, kind: str) -> Path:
        """Creates the filepath in the build directory for the given source path.

        Note that this is a complex operation as the modules in the source are nested while the build directory is flat.
        This means that we lose information and risk having duplicate filenames. To avoid this, we prefix the filename
        with a number to ensure uniqueness.
        """
        filestem = source_path.stem
        # Get rid of the local index
        filestem = INDEX_PATTERN.sub("", filestem)

        # Increment to ensure we do not get duplicate filenames when we flatten the file
        # structure from the module to the build directory.
        self.resource_counter += 1

        filename = f"{self.resource_counter}.{filestem}"
        if not filename.casefold().endswith(kind.casefold()):
            filename = f"{filename}.{kind}"
        filename = f"{filename}{source_path.suffix}"
        destination_path = self.build_dir / self.resource_folder / filename
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        return destination_path

    def _get_loader(self, source_path: Path) -> tuple[None, ToolkitWarning] | tuple[type[ResourceLoader], None]:
        return get_loader(source_path, self.resource_folder)


def get_loader(
    source_path: Path,
    resource_folder: str,
    force_pattern: bool = False,
) -> tuple[None, ToolkitWarning] | tuple[type[ResourceLoader], None]:
    folder_loaders = LOADER_BY_FOLDER_NAME.get(resource_folder, [])
    if not folder_loaders:
        return None, ToolkitNotSupportedWarning(
            f"resource of type {resource_folder!r} in {source_path.name}.",
            details=f"Available resources are: {', '.join(LOADER_BY_FOLDER_NAME.keys())}",
        )

    loaders = [
        loader for loader in folder_loaders if loader.is_supported_file(source_path, force_pattern=force_pattern)
    ]
    if len(loaders) == 0:
        suggestion: str | None = None
        if "." in source_path.stem:
            core, kind = source_path.stem.rsplit(".", 1)
            match = difflib.get_close_matches(kind, [loader.kind for loader in folder_loaders])
            if match:
                suggested_name = f"{core}.{match[0]}{source_path.suffix}"
                suggestion = f"Did you mean to call the file {suggested_name!r}?"
        else:
            kinds = [loader.kind for loader in folder_loaders]
            if len(kinds) == 1:
                suggestion = f"Did you mean to call the file '{source_path.stem}.{kinds[0]}{source_path.suffix}'?"
            else:
                suggestion = (
                    f"All files in the {resource_folder!r} folder must have a file extension that matches "
                    f"the resource type. Supported types are: {humanize_collection(kinds)}."
                )
        return None, UnknownResourceTypeWarning(source_path, suggestion)
    elif len(loaders) > 1 and all(loader.folder_name == "raw" for loader in loaders):
        # Raw files can be ambiguous, so we need to check the content.
        # If there is a tableName field, it is a table, otherwise it is a database.
        if any(
            line.strip().startswith("tableName:") or line.strip().startswith("- tableName:")
            for line in safe_read(source_path).splitlines()
        ):
            return RawTableLoader, None
        else:
            return RawDatabaseLoader, None
    elif len(loaders) > 1 and all(issubclass(loader, GroupLoader) for loader in loaders):
        # There are two group loaders, one for resource scoped and one for all scoped.
        return GroupLoader, None
    elif len(loaders) > 1:
        names = humanize_collection(
            [f"'{source_path.stem}.{loader.kind}{source_path.suffix}'" for loader in loaders], bind_word="or"
        )
        raise AmbiguousResourceFileError(
            f"Ambiguous resource file {source_path.name} in {resource_folder} folder. "
            f"Unclear whether it is {humanize_collection([loader.kind for loader in loaders], bind_word='or')}."
            f"\nPlease name the file {names}."
        )

    return cast(type[ResourceLoader], loaders[0]), None


class DefaultBuilder(Builder):
    """This is used to build resources that do not have a specific builder."""

    def build(
        self,
        source_files: list[BuildSourceFile],
        module: ModuleLocation,
        console: Callable[[str], None] | None = None,
    ) -> Iterable[BuildDestinationFile | list[ToolkitWarning]]:
        for source_file in source_files:
            if source_file.loaded is None:
                # Not a YAML file
                continue
            loader, warning = self._get_loader(source_file.source.path)
            if loader is None:
                if warning is not None:
                    yield [warning]
                continue

            destination_path = self._create_destination_path(source_file.source.path, loader.kind)
            destination = BuildDestinationFile(
                path=destination_path,
                loaded=source_file.loaded,
                loader=loader,
                source=source_file.source,
                extra_sources=None,
            )
            yield destination
