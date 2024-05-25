from __future__ import annotations

import re
import traceback
from abc import ABC, abstractmethod
from collections.abc import Sequence, Sized
from functools import lru_cache
from pathlib import Path
from typing import Any, Generic, TypeVar, Union

from cognite.client import CogniteClient
from cognite.client.data_classes import WorkflowVersionId
from cognite.client.data_classes._base import (
    T_CogniteResourceList,
    T_WritableCogniteResource,
    T_WriteClass,
    WriteableCogniteResourceList,
)
from cognite.client.data_classes.capabilities import Capability
from cognite.client.data_classes.data_modeling import DataModelingId, VersionedDataModelingId
from cognite.client.data_classes.data_modeling.ids import InstanceId
from cognite.client.exceptions import CogniteAPIError, CogniteNotFoundError
from cognite.client.utils.useful_types import SequenceNotStr
from rich import print
from rich.panel import Panel

from cognite_toolkit._cdf_tk._parameters import ParameterSpecSet, read_parameter_from_init_type_hints
from cognite_toolkit._cdf_tk.tk_warnings import WarningList, YAMLFileWarning
from cognite_toolkit._cdf_tk.utils import CDFToolConfig, load_yaml_inject_variables

from .data_classes import (
    DatapointDeployResult,
    RawDatabaseTable,
    UploadDeployResult,
)

T_ID = TypeVar(
    "T_ID",
    bound=Union[str, int, DataModelingId, InstanceId, VersionedDataModelingId, RawDatabaseTable, WorkflowVersionId],
)
T_WritableCogniteResourceList = TypeVar("T_WritableCogniteResourceList", bound=WriteableCogniteResourceList)
_COMPILED_PATTERN: dict[str, re.Pattern] = {}


class Loader(ABC):
    """This is the base class for all loaders

    Args:
        client (CogniteClient): The client to use for interacting with the CDF API.

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
    filename_pattern: str = ""
    dependencies: frozenset[type[ResourceLoader]] = frozenset()
    exclude_filetypes: frozenset[str] = frozenset()
    _doc_base_url: str = "https://api-docs.cognite.com/20230101/tag/"
    _doc_url: str = ""

    def __init__(self, client: CogniteClient, build_path: Path | None = None):
        self.client = client
        self.build_path = build_path
        self.extra_configs: dict[str, Any] = {}

    @classmethod
    def create_loader(cls: type[T_Loader], ToolGlobals: CDFToolConfig) -> T_Loader:
        return cls(ToolGlobals.client)

    @property
    def display_name(self) -> str:
        return self.folder_name

    @classmethod
    def doc_url(cls) -> str:
        return cls._doc_base_url + cls._doc_url

    @classmethod
    def find_files(cls, dir_or_file: Path) -> list[Path]:
        """Find all files that are supported by this loader in the given directory or file.

        Args:
            dir_or_file (Path): The directory or file to search in.

        Returns:
            list[Path]: A sorted list of all files that are supported by this loader.

        """
        if dir_or_file.is_file():
            if not cls.is_supported_file(dir_or_file):
                raise ValueError("Invalid file type")
            return [dir_or_file]
        elif dir_or_file.is_dir():
            file_paths = [file for file in dir_or_file.glob("**/*") if cls.is_supported_file(file)]
            return sorted(file_paths)
        else:
            return []

    @classmethod
    def is_supported_file(cls, file: Path) -> bool:
        if cls.filetypes and file.suffix[1:] not in cls.filetypes:
            return False
        if cls.exclude_filetypes and file.suffix[1:] in cls.exclude_filetypes:
            return False
        if cls.filename_pattern:
            if cls.filename_pattern not in _COMPILED_PATTERN:
                _COMPILED_PATTERN[cls.filename_pattern] = re.compile(cls.filename_pattern)
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
        _display_name: The name of the resource that is used when printing messages. If this is not set, the
            api_name is used.
    """

    # Must be set in the subclass
    resource_write_cls: type[T_WriteClass]
    resource_cls: type[T_WritableCogniteResource]
    list_cls: type[T_WritableCogniteResourceList]
    list_write_cls: type[T_CogniteResourceList]
    # Optional to set in the subclass
    support_drop = True
    filetypes = frozenset({"yaml", "yml"})
    dependencies: frozenset[type[ResourceLoader]] = frozenset()
    _display_name: str = ""

    @property
    def display_name(self) -> str:
        return self._display_name or super().display_name

    @classmethod
    @abstractmethod
    def get_id(cls, item: T_WriteClass | T_WritableCogniteResource | dict) -> T_ID:
        raise NotImplementedError

    @classmethod
    def check_identifier_semantics(
        cls, identifier: T_ID, filepath: Path, verbose: bool
    ) -> WarningList[YAMLFileWarning]:
        """This should be overwritten in subclasses to check the semantics of the identifier."""
        return WarningList[YAMLFileWarning]()

    @classmethod
    @abstractmethod
    def get_required_capability(cls, items: T_CogniteResourceList) -> Capability | list[Capability]:
        raise NotImplementedError(f"get_required_capability must be implemented for {cls.__name__}.")

    @classmethod
    def get_ids(cls, items: Sequence[T_WriteClass | T_WritableCogniteResource]) -> list[T_ID]:
        return [cls.get_id(item) for item in items]

    # Default implementations that can be overridden
    @classmethod
    def create_empty_of(cls, items: T_CogniteResourceList) -> T_CogniteResourceList:
        return cls.list_write_cls([])

    def load_resource(
        self, filepath: Path, ToolGlobals: CDFToolConfig, skip_validation: bool
    ) -> T_WriteClass | T_CogniteResourceList | None:
        raw_yaml = load_yaml_inject_variables(filepath, ToolGlobals.environment_variables())
        if isinstance(raw_yaml, list):
            return self.list_write_cls.load(raw_yaml)
        else:
            return self.list_write_cls([self.resource_write_cls.load(raw_yaml)])

    def dump_resource(
        self, resource: T_WriteClass, source_file: Path, local_resource: T_WriteClass
    ) -> tuple[dict[str, Any], dict[Path, str]]:
        """Dumps the resource to a dictionary that matches the write format.

        In addition, it can return a dictionary with extra files and their content. This is, for example, used by
        Transformations to dump the 'query' key to an .sql file.

        Args:
            resource (T_WritableCogniteResource): The resource to dump (typically comes from CDF).
            source_file (Path): The source file that the resource was loaded from.
            local_resource (T_WritableCogniteResource): The local resource.

        Returns:
            tuple[dict[str, Any], dict[Path, str]]: The dumped resource and a dictionary with extra files and their
             content.
        """
        return resource.dump(), {}

    @abstractmethod
    def create(self, items: T_CogniteResourceList) -> Sized:
        raise NotImplementedError

    @abstractmethod
    def retrieve(self, ids: SequenceNotStr[T_ID]) -> T_WritableCogniteResourceList:
        raise NotImplementedError

    @abstractmethod
    def update(self, items: T_CogniteResourceList) -> Sized:
        raise NotImplementedError

    @abstractmethod
    def delete(self, ids: SequenceNotStr[T_ID]) -> int:
        raise NotImplementedError

    @classmethod
    @lru_cache(maxsize=1)
    def get_write_cls_parameter_spec(cls) -> ParameterSpecSet:
        return read_parameter_from_init_type_hints(cls.resource_write_cls).as_camel_case()

    def to_create_changed_unchanged_triple(
        self, resources: T_CogniteResourceList
    ) -> tuple[T_CogniteResourceList, T_CogniteResourceList, T_CogniteResourceList]:
        """Returns a triple of lists of resources that should be created, updated, and are unchanged."""
        resource_ids = self.get_ids(resources)
        to_create, to_update, unchanged = (
            self.create_empty_of(resources),
            self.create_empty_of(resources),
            self.create_empty_of(resources),
        )
        try:
            cdf_resources = self.retrieve(resource_ids)
        except Exception as e:
            print(
                f"  [bold yellow]WARNING:[/] Failed to retrieve {len(resource_ids)} of {self.display_name}. Proceeding assuming not data in CDF. Error {e}."
            )
            print(Panel(traceback.format_exc()))
            cdf_resource_by_id = {}
        else:
            cdf_resource_by_id = {self.get_id(resource): resource for resource in cdf_resources}

        for item in resources:
            cdf_resource = cdf_resource_by_id.get(self.get_id(item))
            # The custom compare is needed when the regular == does not work. For example, TransformationWrite
            # have OIDC credentials that will not be returned by the retrieve method, and thus need special handling.
            if cdf_resource and (item == cdf_resource.as_write() or self._is_equal_custom(item, cdf_resource)):
                unchanged.append(item)
            elif cdf_resource:
                to_update.append(item)
            else:
                to_create.append(item)
        return to_create, to_update, unchanged

    def _is_equal_custom(self, local: T_WriteClass, cdf_resource: T_WritableCogniteResource) -> bool:
        """This method is used to compare the local and cdf resource when the default comparison fails.

        This is needed for resources that have fields that are not returned by the retrieve method, like,
        for example, the OIDC credentials in Transformations.
        """
        return False

    def _update_resources(self, resources: T_CogniteResourceList, verbose: bool) -> int | None:
        try:
            updated = self.update(resources)
        except Exception as e:
            print(f"  [bold yellow]Error:[/] Failed to update {self.display_name}. Error {e}.")
            if verbose:
                print(Panel(traceback.format_exc()))
            return None
        else:
            return len(updated)

    @staticmethod
    def _print_ids_or_length(resource_ids: SequenceNotStr[T_ID], limit: int = 10) -> str:
        if len(resource_ids) == 1:
            return f"{resource_ids[0]!r}"
        elif len(resource_ids) <= limit:
            return f"{resource_ids}"
        else:
            return f"{len(resource_ids)} items"


class ResourceContainerLoader(
    ResourceLoader[T_ID, T_WriteClass, T_WritableCogniteResource, T_CogniteResourceList, T_WritableCogniteResourceList],
    ABC,
):
    """This is the base class for all loaders resource containers.

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

    def _drop_data(self, loaded_resources: T_CogniteResourceList, dry_run: bool, verbose: bool) -> int:
        nr_of_dropped = 0
        resource_ids = self.get_ids(loaded_resources)
        if dry_run:
            resource_drop_count = self.count(resource_ids)
            nr_of_dropped += resource_drop_count
            if verbose:
                self._verbose_print_drop(resource_drop_count, resource_ids, dry_run)
            return nr_of_dropped

        try:
            resource_drop_count = self.drop_data(resource_ids)
            nr_of_dropped += resource_drop_count
        except CogniteAPIError as e:
            if e.code == 404 and verbose:
                print(f"  [bold]INFO:[/] {len(resource_ids)} {self.display_name} do(es) not exist.")
        except CogniteNotFoundError:
            return nr_of_dropped
        except Exception as e:
            print(
                f"  [bold yellow]WARNING:[/] Failed to drop {self.item_name} from {len(resource_ids)} {self.display_name}. Error {e}."
            )
            if verbose:
                print(Panel(traceback.format_exc()))
        else:  # Delete succeeded
            if verbose:
                self._verbose_print_drop(resource_drop_count, resource_ids, dry_run)
        return nr_of_dropped

    def _verbose_print_drop(self, drop_count: int, resource_ids: SequenceNotStr[T_ID], dry_run: bool) -> None:
        prefix = "Would have dropped" if dry_run else "Dropped"
        if drop_count > 0:
            print(
                f"  {prefix} {drop_count:,} {self.item_name} from {self.display_name}: "
                f"{self._print_ids_or_length(resource_ids)}."
            )
        elif drop_count == 0:
            verb = "is" if len(resource_ids) == 1 else "are"
            print(
                f"  The {self.display_name}: {self._print_ids_or_length(resource_ids)} {verb} empty, "
                f"thus no {self.item_name} will be {'touched' if dry_run else 'dropped'}."
            )
        else:
            # Count is not supported
            print(
                f" {prefix} all {self.item_name} from {self.display_name}: "
                f"{self._print_ids_or_length(resource_ids)}."
            )


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
    def upload(self, datafile: Path, ToolGlobals: CDFToolConfig, dry_run: bool) -> tuple[str, int]:
        raise NotImplementedError

    def deploy_resources(
        self,
        path: Path,
        ToolGlobals: CDFToolConfig,
        dry_run: bool = False,
        has_done_drop: bool = False,
        has_dropped_data: bool = False,
        verbose: bool = False,
    ) -> UploadDeployResult | None:
        filepaths = self.find_files(path)

        prefix = "Would upload" if dry_run else "Uploading"
        print(f"[bold]{prefix} {len(filepaths)} data {self.display_name} files to CDF...[/]")
        datapoints = 0
        for filepath in filepaths:
            try:
                message, file_datapoints = self.upload(filepath, ToolGlobals, dry_run)
            except Exception as e:
                print(f"  [bold red]Error:[/] Failed to upload {filepath.name}. Error: {e!r}.")
                print(Panel(traceback.format_exc()))
                ToolGlobals.failed = True
                return None
            if verbose:
                print(message)
            datapoints += file_datapoints
        if datapoints != 0:
            return DatapointDeployResult(
                self.display_name, points=datapoints, uploaded=len(filepaths), item_name=self.item_name
            )
        else:
            return UploadDeployResult(self.display_name, uploaded=len(filepaths), item_name=self.item_name)
