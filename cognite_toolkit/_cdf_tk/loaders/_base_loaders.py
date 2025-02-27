from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Hashable, Iterable, Sequence, Set, Sized
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from cognite.client.data_classes._base import (
    T_CogniteResourceList,
    T_WritableCogniteResource,
    T_WriteClass,
    WriteableCogniteResourceList,
)
from cognite.client.data_classes.capabilities import Capability
from cognite.client.utils.useful_types import SequenceNotStr
from rich.console import Console

from cognite_toolkit._cdf_tk._parameters import ParameterSpecSet, read_parameter_from_init_type_hints
from cognite_toolkit._cdf_tk.client import ToolkitClient
from cognite_toolkit._cdf_tk.constants import EXCL_FILES, USE_SENTRY
from cognite_toolkit._cdf_tk.tk_warnings import ToolkitWarning
from cognite_toolkit._cdf_tk.utils import load_yaml_inject_variables, safe_read, to_directory_compatible

if TYPE_CHECKING:
    from cognite_toolkit._cdf_tk.data_classes import BuildEnvironment

T_ID = TypeVar("T_ID", bound=Hashable)
T_WritableCogniteResourceList = TypeVar("T_WritableCogniteResourceList", bound=WriteableCogniteResourceList)
_COMPILED_PATTERN: dict[str, re.Pattern] = {}


class Loader(ABC):
    """This is the base class for all loaders

    Args:
        client (ToolkitClient): The client to use for interacting with the CDF API.
        build_dir (Path): The path to the build directory

    Class attributes:
        filetypes: The filetypes that are supported by this loader. This should be set in all subclasses.
        folder_name: The name of the folder in the build directory where the files are located. This should be set in all subclasses.
        filename_pattern: A regex pattern that is used to filter the files that are supported by this loader. This is used
            when two loaders have the same folder name to differentiate between them. If not set, all files are supported.
        dependencies: A set of loaders that must be loaded before this loader.
        exclude_filetypes: A set of filetypes that should be excluded from the supported filetypes.
    """

    filetypes: frozenset[str]
    folder_name: str
    kind: str
    filename_pattern: str = ""
    dependencies: frozenset[type[ResourceLoader]] = frozenset()
    exclude_filetypes: frozenset[str] = frozenset()
    _doc_base_url: str = "https://api-docs.cognite.com/20230101/tag/"
    _doc_url: str = ""

    def __init__(self, client: ToolkitClient, build_dir: Path | None, console: Console | None = None) -> None:
        self.client = client
        self.resource_build_path: Path | None = None
        if build_dir is not None and build_dir.name == self.folder_name:
            raise ValueError(f"Build directory cannot be the same as the resource folder name: {self.folder_name}")
        elif build_dir is not None:
            self.resource_build_path = build_dir / self.folder_name
        self.console = console

    @classmethod
    def create_loader(
        cls: type[T_Loader],
        client: ToolkitClient,
        build_dir: Path | None = None,
        console: Console | None = None,
    ) -> T_Loader:
        return cls(client, build_dir, console)

    @property
    def display_name(self) -> str:
        return self.folder_name

    @classmethod
    def doc_url(cls) -> str:
        return cls._doc_base_url + cls._doc_url

    def find_files(self, dir_or_file: Path | None = None, include_formats: Set[str] | None = None) -> list[Path]:
        """Find all files that are supported by this loader in the given directory or file.

        Args:
            dir_or_file (Path): The directory or file to search in. If no path is given,
                the build directory is used.
            include_formats (set[str]): A set of file formats to include. If not set, all formats are included.

        Returns:
            list[Path]: A sorted list of all files that are supported by this loader.

        """
        dir_or_file = dir_or_file or self.resource_build_path
        if dir_or_file is None:
            raise ValueError("No 'dir_or_file' or 'build_path' is set.")
        if dir_or_file.is_file():
            if not self.is_supported_file(dir_or_file):
                raise ValueError("Invalid file type")
            return [dir_or_file]
        elif dir_or_file.is_dir():
            file_paths = [
                file
                for file in dir_or_file.glob("**/*")
                if self.is_supported_file(file) and (include_formats is None or file.suffix in include_formats)
            ]
            return sorted(file_paths)
        else:
            return []

    @classmethod
    def any_supported_files(cls, directory: Path) -> bool:
        return any(cls.is_supported_file(file) for file in directory.glob("**/*"))

    @classmethod
    def is_supported_file(cls, file: Path, force_pattern: bool = False) -> bool:
        """Check if hte file is supported by this loader.

        Args:
            file: The filepath to check.
            force_pattern: If True, the filename pattern is used to determine if the file is supported. If False, the
                file extension is used to determine if the file is supported (given that the
                RequireKind flag is enabled).

        Returns:
            bool: True if the file is supported, False otherwise.

        """
        if cls.filetypes and file.suffix[1:] not in cls.filetypes:
            return False
        if cls.exclude_filetypes and file.suffix[1:] in cls.exclude_filetypes:
            return False
        if force_pattern is False and not issubclass(cls, DataLoader):
            return file.stem.casefold().endswith(cls.kind.casefold())
        else:
            if cls.filename_pattern:
                if cls.filename_pattern not in _COMPILED_PATTERN:
                    _COMPILED_PATTERN[cls.filename_pattern] = re.compile(cls.filename_pattern, re.IGNORECASE)
                return _COMPILED_PATTERN[cls.filename_pattern].match(file.stem) is not None
        return True


T_Loader = TypeVar("T_Loader", bound=Loader)


class ResourceLoader(
    Loader,
    ABC,
    Generic[T_ID, T_WriteClass, T_WritableCogniteResource, T_CogniteResourceList, T_WritableCogniteResourceList],
):
    """This is the base class for all resource loaders.

    A resource loader consists of the following
        - A CRUD (Create, Retrieve, Update, Delete) interface for interacting with the CDF API.
        - A read and write data class with list for the resource.
        - Must use the file-format YAML to store the local version of the resource.

    All resources supported by the cognite_toolkit should implement a loader.

    Class attributes:
        resource_write_cls: The write data class for the resource.
        resource_cls: The read data class for the resource.
        list_cls: The read list format for this resource.
        list_write_cls: The write list format for this resource.
        support_drop: Whether the resource supports the drop flag.
        filetypes: The filetypes that are supported by this loader. This should not be set in the subclass, it
            should always be yaml and yml.
        dependencies: A set of loaders that must be loaded before this loader.
    """

    # Must be set in the subclass
    resource_write_cls: type[T_WriteClass]
    resource_cls: type[T_WritableCogniteResource]
    list_cls: type[T_WritableCogniteResourceList]
    list_write_cls: type[T_CogniteResourceList]
    # Optional to set in the subclass
    support_drop = True
    support_update = True
    filetypes = frozenset({"yaml", "yml"})
    dependencies: frozenset[type[ResourceLoader]] = frozenset()
    # For example, TransformationNotification and Schedule has Transformation as the parent resource
    # This is used in the iterate method to ensure that nothing is returned if
    # the resource type does not have a parent resource.
    parent_resource: frozenset[type[ResourceLoader]] = frozenset()

    # The methods that must be implemented in the subclass
    @classmethod
    @abstractmethod
    def get_id(cls, item: T_WriteClass | T_WritableCogniteResource | dict) -> T_ID:
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def dump_id(cls, id: T_ID) -> dict[str, Any]:
        raise NotImplementedError()

    @classmethod
    @abstractmethod
    def get_required_capability(
        cls, items: Sequence[T_WriteClass] | None, read_only: bool
    ) -> Capability | list[Capability]:
        raise NotImplementedError(f"get_required_capability must be implemented for {cls.__name__}.")

    @abstractmethod
    def create(self, items: T_CogniteResourceList) -> Sized:
        raise NotImplementedError

    @abstractmethod
    def retrieve(self, ids: SequenceNotStr[T_ID]) -> T_WritableCogniteResourceList:
        raise NotImplementedError

    def update(self, items: T_CogniteResourceList) -> Sized:
        raise NotImplementedError(f"Update is not supported for {type(self).__name__}.")

    @abstractmethod
    def delete(self, ids: SequenceNotStr[T_ID]) -> int:
        raise NotImplementedError

    def iterate(
        self,
        data_set_external_id: str | None = None,
        space: str | None = None,
        parent_ids: list[Hashable] | None = None,
    ) -> Iterable[T_WritableCogniteResource]:
        if sum([1 for x in [data_set_external_id, space, parent_ids] if x is not None]) > 1:
            raise ValueError("At most one of data_set_external_id, space, or parent_ids must be set.")
        if parent_ids is not None and not self.parent_resource:
            return []
        if space is not None:
            from ._resource_loaders.datamodel_loaders import SpaceLoader

            if SpaceLoader not in self.dependencies:
                return []
        if data_set_external_id is not None:
            from ._resource_loaders.data_organization_loaders import DataSetsLoader

            if DataSetsLoader not in self.dependencies:
                return []
        return self._iterate(data_set_external_id, space, parent_ids)

    @abstractmethod
    def _iterate(
        self,
        data_set_external_id: str | None = None,
        space: str | None = None,
        parent_ids: list[Hashable] | None = None,
    ) -> Iterable[T_WritableCogniteResource]:
        raise NotImplementedError

    # The methods below have default implementations that can be overwritten in subclasses
    @classmethod
    @lru_cache(maxsize=1)
    def get_write_cls_parameter_spec(cls) -> ParameterSpecSet:
        return read_parameter_from_init_type_hints(cls.resource_write_cls).as_camel_case()

    @classmethod
    def get_dependent_items(cls, item: dict) -> Iterable[tuple[type[ResourceLoader], Hashable]]:
        """Returns all items that this item requires.

        For example, a TimeSeries requires a DataSet, so this method would return the
        DatasetLoader and identifier of that dataset.
        """
        return
        yield

    @classmethod
    def check_item(cls, item: dict, filepath: Path, element_no: int | None) -> list[ToolkitWarning]:
        """Check the item for any issues.

        This is intended to be overwritten in subclasses that require special checking of the item.

        Example, it is used in the WorkflowVersionLoader to check that all tasks dependsOn tasks that are in the same
        workflow.

        Args:
            item (dict): The item to check.
            filepath (Path): The path to the file where the item is located.
            element_no (int): The element number in the file. This is used to provide better error messages.
                None if the item is an object and not a list.

        Returns:
            list[ToolkitWarning]: A list of warnings.
        """
        return []

    @classmethod
    def get_internal_id(cls, item: T_WritableCogniteResource | dict) -> int:
        raise NotImplementedError(f"{cls.__name__} does not have an internal id.")

    @classmethod
    def _split_ids(cls, ids: T_ID | int | SequenceNotStr[T_ID | int] | None) -> tuple[list[int], list[str]]:
        # Used by subclasses to split the ids into external and internal ids
        if ids is None:
            return [], []
        if isinstance(ids, int):
            return [ids], []
        if isinstance(ids, str):
            return [], [ids]
        if isinstance(ids, Sequence):
            return [id for id in ids if isinstance(id, int)], [id for id in ids if isinstance(id, str)]
        raise ValueError(f"Invalid ids: {ids}")

    def safe_read(self, filepath: Path | str) -> str:
        """Reads the file and returns the content. This is intended to be overwritten in subclasses that require special
        handling of the files content. For example, Data Models need to quote the value on the version key to ensure
        it is parsed as a string."""
        return safe_read(filepath)

    def load_resource_file(
        self, filepath: Path, environment_variables: dict[str, str | None] | None = None
    ) -> list[dict[str, Any]]:
        """Loads the resource(s) from a file. Can be overwritten in subclasses.

        Examples, is the TransformationLoader that loads the query from a file. Another example, is the View and
        DataModel loaders that nees special handling of the yaml to ensure version key is parsed as a string.
        """
        raw_yaml = load_yaml_inject_variables(
            self.safe_read(filepath),
            environment_variables or {},
            original_filepath=filepath,
        )
        return raw_yaml if isinstance(raw_yaml, list) else [raw_yaml]

    def load_resource(self, resource: dict[str, Any], is_dry_run: bool = False) -> T_WriteClass:
        """Loads the resource from a dictionary. Can be overwritten in subclasses."""
        return self.resource_write_cls._load(resource)

    def load_minimum_resource(self, resource: dict[str, Any]) -> T_ID:
        """Loads the minimum resource from a dictionary. Can be overwritten in subclasses."""
        return self.get_id(self.load_resource(resource))

    def dump_resource(self, resource: T_WritableCogniteResource, local: dict[str, Any] | None = None) -> dict[str, Any]:
        """Dumps the resource to a dictionary that matches the write format.

        This is intended to be overwritten in subclasses that require special dumping logic, for example,
        replacing dataSetId with dataSetExternalId.

        Args:
            resource (T_WritableCogniteResource): The resource to dump (typically comes from CDF).
            local (dict[str, Any] | None): The local resource. When used in a dump/import command, there is no local
                resource.
        """
        return resource.as_write().dump()

    def split_resource(
        self, base_filepath: Path, resource: dict[str, Any]
    ) -> Iterable[tuple[Path, dict[str, Any] | str]]:
        """Splits a resource into multiple files.

        This is used in the dump command. For example, a transformation can be split into the YAML file and
        the SQL file for the query

        Args:
            base_filepath (Path): The base filepath to use when creating the new file.
            resource (dict[str,Any]): The resource to split.

        Returns:
            Iterable[[dict[str,Any], Path]]: An iterable of the new resources and the filepaths where they should be
                saved.
        """
        return [(base_filepath, resource)]

    def diff_list(
        self, local: list[Any], cdf: list[Any], json_path: tuple[str | int, ...]
    ) -> tuple[dict[int, int], list[int]]:
        """Diff two lists and return the indices that needs to be compared and the indices that have been added.
        The lists are subfields of the local and CDF resources.

        This is used by the pull command to determine changes to the local resources compared to the CDF resources. For
        example, a Sequence has a list of columns. This method is used to determine which columns to compare
        and which has been added.

        Args:
            local (list[Any]): The local list.
            cdf (list[Any]): The CDF list.
            json_path (tuple[str | int, ...]): The json path to the list in the resource. For example, 'columns'
                in the case of a sequence.

        Returns:
            tuple[dict[int, int], list[int]]: A dictionary with the indices that needs to be compared and a list of
                indices that have been added. The dictionary has local index as key and CDF index as value. The
                list of indices that have been added are cdf indices.
        """
        raise NotImplementedError(
            f"Missing implementation for {type(self).__name__} for {'.'.join(map(str, json_path))}."
        )

    # Helper methods
    @classmethod
    def get_ids(cls, items: Sequence[T_WriteClass | T_WritableCogniteResource | dict]) -> list[T_ID]:
        return [cls.get_id(item) for item in items]

    @classmethod
    def load_ids(cls, ids: SequenceNotStr[T_ID]) -> list[dict[str, Any]]:
        return [cls.dump_id(id) for id in ids]

    @classmethod
    def safe_get_write_cls_parameter_spec(cls) -> ParameterSpecSet | None:
        from sentry_sdk import capture_exception

        api_spec: ParameterSpecSet | None = None
        try:
            api_spec = cls.get_write_cls_parameter_spec()
        except Exception as e:
            # We don't want to crash the program if we can't get the parameter spec
            # as we can continue without doing this check. Note that getting the parameter spec
            # is also fragile as it relies on the type hints in the cognite-sdk which is out of our control.
            if USE_SENTRY:
                capture_exception(e)
            else:
                raise
        return api_spec

    @classmethod
    def as_str(cls, id: T_ID) -> str:
        if isinstance(id, str):
            return to_directory_compatible(id)
        raise NotImplementedError(
            f"Bug in CogniteToolkit 'as_str' is not implemented for {cls.__name__.removesuffix('Loader')}."
        )


class ResourceContainerLoader(
    ResourceLoader[T_ID, T_WriteClass, T_WritableCogniteResource, T_CogniteResourceList, T_WritableCogniteResourceList],
    ABC,
):
    """This is the base class for all loaders' resource containers.

    A resource container is a resource that contains data. For example, Timeseries contains datapoints, and another
    example is spaces and containers in data modeling that contains instances.

    In addition to the methods that are required for a resource loader, a resource container loader must implement
    the following methods:
        - count: Counts the number of items in the resource container.
        - drop_data: Deletes the data in the resource container.

    class attributes:
        item_name: The name of the item that is stored in the resource container. This should be set in the subclass.
            It is used to display messages when running operations.
    """

    item_name: str

    @abstractmethod
    def count(self, ids: SequenceNotStr[T_ID]) -> int:
        raise NotImplementedError

    @abstractmethod
    def drop_data(self, ids: SequenceNotStr[T_ID]) -> int:
        raise NotImplementedError


class DataLoader(Loader, ABC):
    """This is the base class for all data loaders.

    A data loader is a loader that uploads data to CDF. It will typically depend on a
    resource container that stores the data. For example, the datapoints loader depends
    on the timeseries loader.

    It has only one required method:
        - upload: Uploads the data to CDF.

    class attributes:
        item_name: The name of the item that is stored in the resource container. This should be set in the subclass.
            It is used to display messages when running operations.

    """

    item_name: str

    @abstractmethod
    def upload(self, state: BuildEnvironment, dry_run: bool) -> Iterable[tuple[str, int]]:
        raise NotImplementedError

    def _find_data_files(self, directory: Path) -> list[Path]:
        return [
            path
            for path in directory.rglob("*")
            if path.is_file() and path.name not in EXCL_FILES and self.is_supported_file(path)
        ]
