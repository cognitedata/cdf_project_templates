import time
from collections import defaultdict
from collections.abc import Hashable, Iterable, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any, cast, final

from cognite.client.data_classes import (
    ClientCredentials,
    Function,
    FunctionList,
    FunctionSchedule,
    FunctionSchedulesList,
    FunctionScheduleWrite,
    FunctionScheduleWriteList,
    FunctionWrite,
    FunctionWriteList,
)
from cognite.client.data_classes.capabilities import (
    Capability,
    FilesAcl,
    FunctionsAcl,
    SessionsAcl,
)
from cognite.client.data_classes.functions import HANDLER_FILE_NAME
from cognite.client.exceptions import CogniteAuthError
from cognite.client.utils.useful_types import SequenceNotStr
from rich import print
from rich.console import Console

from cognite_toolkit._cdf_tk._parameters import ParameterSpec, ParameterSpecSet
from cognite_toolkit._cdf_tk.client import ToolkitClient
from cognite_toolkit._cdf_tk.client.data_classes.functions import FunctionScheduleID
from cognite_toolkit._cdf_tk.exceptions import (
    ResourceCreationError,
    ToolkitRequiredValueError,
)
from cognite_toolkit._cdf_tk.feature_flags import Flags
from cognite_toolkit._cdf_tk.loaders._base_loaders import ResourceLoader
from cognite_toolkit._cdf_tk.tk_warnings import HighSeverityWarning, LowSeverityWarning
from cognite_toolkit._cdf_tk.utils import (
    calculate_directory_hash,
    calculate_secure_hash,
    calculate_str_or_file_hash,
)
from cognite_toolkit._cdf_tk.utils.cdf import read_auth, try_find_error

from .auth_loaders import GroupAllScopedLoader
from .data_organization_loaders import DataSetsLoader
from .group_scoped_loader import GroupResourceScopedLoader


@final
class FunctionLoader(ResourceLoader[str, FunctionWrite, Function, FunctionWriteList, FunctionList]):
    support_drop = True
    folder_name = "functions"
    filename_pattern = (
        r"^(?:(?!schedule).)*$"  # Matches all yaml files except file names who's stem contain *.schedule.
    )
    resource_cls = Function
    resource_write_cls = FunctionWrite
    list_cls = FunctionList
    list_write_cls = FunctionWriteList
    kind = "Function"
    dependencies = frozenset({DataSetsLoader, GroupAllScopedLoader})
    _doc_url = "Functions/operation/postFunctions"
    metadata_value_limit = 512
    support_update = False

    class _MetadataKey:
        function_hash = "cognite-toolkit-hash"
        secret_hash = "cdf-toolkit-secret-hash"

    def __init__(self, client: ToolkitClient, build_path: Path | None, console: Console | None):
        super().__init__(client, build_path, console)
        self.data_set_id_by_external_id: dict[str, int] = {}
        self.function_dir_by_external_id: dict[str, Path] = {}

    @property
    def display_name(self) -> str:
        return "functions"

    @classmethod
    def get_required_capability(
        cls, items: Sequence[FunctionWrite] | None, read_only: bool
    ) -> list[Capability] | list[Capability]:
        if not items and items is not None:
            return []

        function_actions = (
            [FunctionsAcl.Action.Read] if read_only else [FunctionsAcl.Action.Read, FunctionsAcl.Action.Write]
        )
        file_actions = [FilesAcl.Action.Read] if read_only else [FilesAcl.Action.Read, FilesAcl.Action.Write]

        return [
            FunctionsAcl(function_actions, FunctionsAcl.Scope.All()),
            FilesAcl(file_actions, FilesAcl.Scope.All()),  # Needed for uploading function artifacts
        ]

    @classmethod
    def get_id(cls, item: Function | FunctionWrite | dict) -> str:
        if isinstance(item, dict):
            return item["externalId"]
        if item.external_id is None:
            raise ToolkitRequiredValueError("Function must have external_id set.")
        return item.external_id

    @classmethod
    def dump_id(cls, id: str) -> dict[str, Any]:
        return {"externalId": id}

    @classmethod
    def get_dependent_items(cls, item: dict) -> Iterable[tuple[type[ResourceLoader], Hashable]]:
        if "dataSetExternalId" in item:
            yield DataSetsLoader, item["dataSetExternalId"]

    def load_resource_file(
        self, filepath: Path, environment_variables: dict[str, str | None] | None = None
    ) -> list[dict[str, Any]]:
        if filepath.parent.name != self.folder_name:
            # Functions configs needs to be in the root function folder.
            # This is to allow arbitrary YAML files inside the function code folder.
            return []
        if self.resource_build_path is None:
            raise ValueError("build_path must be set to compare functions as function code must be compared.")

        raw_list = super().load_resource_file(filepath, environment_variables)
        for item in raw_list:
            item_id = self.get_id(item)
            function_rootdir = Path(self.resource_build_path / item_id)
            self.function_dir_by_external_id[item_id] = function_rootdir
            if "metadata" not in item:
                item["metadata"] = {}
            value = self._create_hash_values(function_rootdir)
            item["metadata"][self._MetadataKey.function_hash] = value
            if "secrets" in item:
                item["metadata"][self._MetadataKey.secret_hash] = calculate_secure_hash(item["secrets"])

        return raw_list

    @classmethod
    def _create_hash_values(cls, function_rootdir: Path) -> str:
        root_hash = calculate_directory_hash(function_rootdir, ignore_files={".pyc"}, shorten=True)
        hash_value = f"/={root_hash}"
        to_search = [function_rootdir]
        while to_search:
            search_dir = to_search.pop()
            for file in sorted(search_dir.glob("*"), key=lambda x: x.relative_to(function_rootdir).as_posix()):
                if file.is_dir():
                    to_search.append(file)
                    continue
                elif file.is_file() and file.suffix == ".pyc":
                    continue
                file_hash = calculate_str_or_file_hash(file, shorten=True)
                new_entry = f"{file.relative_to(function_rootdir).as_posix()}={file_hash}"
                if len(hash_value) + len(new_entry) > (cls.metadata_value_limit - 1):
                    break
                hash_value += f";{new_entry}"
        return hash_value

    def load_resource(self, resource: dict[str, Any], is_dry_run: bool = False) -> FunctionWrite:
        item_id = self.get_id(resource)
        if ds_external_id := resource.pop("dataSetExternalId", None):
            self.data_set_id_by_external_id[item_id] = self.client.lookup.data_sets.id(ds_external_id, is_dry_run)
        if "fileId" not in resource:
            # The fileID is required for the function to be created, but in the `.create` method
            # we first create that file and then set the fileID.
            resource["fileId"] = "<will_be_generated>"
        return FunctionWrite._load(resource)

    def dump_resource(self, resource: Function, local: dict[str, Any] | None = None) -> dict[str, Any]:
        if resource.status == "Failed":
            dumped = self.dump_id(resource.external_id or resource.name)
            dumped["status"] = "Failed"
            return dumped
        dumped = resource.as_write().dump()
        local = local or {}
        for key in ["cpu", "memory", "runtime"]:
            if key not in local:
                # Server set default values
                dumped.pop(key, None)
            elif isinstance(local.get(key), float) and local[key] < dumped[key]:
                # On Azure and AWS, the server sets the CPU and Memory to the default values if the user
                # pass in lower values. We set this to match the local to avoid triggering a redeploy.
                # Note the user will get a warning about this when the function is created.
                if self.client.config.cloud_provider in ("azure", "aws"):
                    dumped[key] = local[key]
                elif self.client.config.cloud_provider == "gcp" and key == "cpu" and local[key] < 1.0:
                    # GCP does not allow CPU to be set to below 1.0
                    dumped[key] = local[key]
                elif self.client.config.cloud_provider == "gcp" and key == "memory" and local[key] < 1.5:
                    # GCP does not allow Memory to be set to below 1.5
                    dumped[key] = local[key]

        for key in ["indexUrl", "extraIndexUrls"]:
            # Only in write (request) format of the function
            if key in local:
                dumped[key] = local[key]
        if "secrets" in dumped and "secrets" not in local:
            # Secrets are masked in the response.
            dumped.pop("secrets")
        elif "secrets" in dumped and "secrets" in local:
            # Note this will be misleading as the secrets might not be the same as the ones in the API.
            # It will be caught by the hash comparison, but can cause confusion for the user if they
            # compare the dumped file with the API.
            dumped["secrets"] = local["secrets"]

        if file_id := dumped.pop("fileId", None):
            # The fileId is not part of the write object.
            function_zip_file = self.client.files.retrieve(id=file_id)
            if function_zip_file and (data_set_id := function_zip_file.data_set_id):
                dumped["dataSetExternalId"] = self.client.lookup.data_sets.external_id(data_set_id)

        if dumped.get("functionPath") == HANDLER_FILE_NAME and "functionPath" not in local:
            # Remove the default value of the functionPath
            dumped.pop("functionPath", None)

        return dumped

    def _is_activated(self, action: str) -> bool:
        status = self.client.functions.status()
        if status.status == "activated":
            return True
        if status.status == "requested":
            print(
                HighSeverityWarning(
                    f"Function service activation is in progress, cannot {action} functions."
                ).get_message()
            )
            return False
        else:
            print(
                HighSeverityWarning(
                    "Function service has not been activated, activating now, this may take up to 2 hours..."
                ).get_message()
            )
            self.client.functions.activate()
        return False

    def create(self, items: FunctionWriteList) -> FunctionList:
        created = FunctionList([], cognite_client=self.client)
        if not self._is_activated("create"):
            return created
        if self.resource_build_path is None:
            raise ValueError("build_path must be set to compare functions as function code must be compared.")
        for item in items:
            external_id = item.external_id or item.name
            function_rootdir = self.function_dir_by_external_id[external_id]
            file_id = self.client.functions._zip_and_upload_folder(
                name=item.name,
                folder=str(function_rootdir),
                external_id=external_id,
                data_set_id=self.data_set_id_by_external_id.get(external_id),
            )
            # Wait until the files is available
            t0 = time.perf_counter()
            sleep_time = 1.0  # seconds
            for i in range(6):
                file = self.client.files.retrieve(external_id=external_id)
                if file and file.uploaded:
                    break
                time.sleep(sleep_time)
                sleep_time *= 2
            else:
                elapsed_time = time.perf_counter() - t0
                raise ResourceCreationError(
                    f"Failed to create function {external_id}. CDF API timed out after {elapsed_time:.0f} "
                    "seconds while waiting for the function code to be uploaded. Wait and try again.\nIf the"
                    " problem persists, please contact Cognite support."
                )
            item.file_id = file_id
            created_item = self.client.functions.create(item)
            self._warn_if_cpu_or_memory_changed(created_item, item)
            created.append(created_item)
        return created

    @staticmethod
    def _warn_if_cpu_or_memory_changed(created_item: Function, item: FunctionWrite) -> None:
        is_cpu_increased = (
            isinstance(item.cpu, float) and isinstance(created_item.cpu, float) and item.cpu < created_item.cpu
        )
        is_mem_increased = (
            isinstance(item.memory, float)
            and isinstance(created_item.memory, float)
            and item.memory < created_item.memory
        )
        if is_cpu_increased and is_mem_increased:
            prefix = "CPU and Memory"
            suffix = f"CPU {item.cpu} -> {created_item.cpu}, Memory {item.memory} -> {created_item.memory}"
        elif is_cpu_increased:
            prefix = "CPU"
            suffix = f"{item.cpu} -> {created_item.cpu}"
        elif is_mem_increased:
            prefix = "Memory"
            suffix = f"{item.memory} -> {created_item.memory}"
        else:
            return
        # The server sets the CPU and Memory to the default values, if the user pass in a lower value.
        # This happens on Azure and AWS. Warning the user about this.
        LowSeverityWarning(
            f"Function {prefix} is not configurable. Function {item.external_id!r} set {suffix}"
        ).print_warning()

    def retrieve(self, ids: SequenceNotStr[str]) -> FunctionList:
        if not self._is_activated("retrieve"):
            return FunctionList([])
        return self.client.functions.retrieve_multiple(external_ids=ids, ignore_unknown_ids=True)

    def delete(self, ids: SequenceNotStr[str]) -> int:
        functions = self.retrieve(ids)

        self.client.functions.delete(external_id=ids)
        file_ids = {func.file_id for func in functions if func.file_id}
        self.client.files.delete(id=list(file_ids), ignore_unknown_ids=True)
        return len(ids)

    def _iterate(
        self,
        data_set_external_id: str | None = None,
        space: str | None = None,
        parent_ids: list[Hashable] | None = None,
    ) -> Iterable[Function]:
        return iter(self.client.functions)

    @classmethod
    @lru_cache(maxsize=1)
    def get_write_cls_parameter_spec(cls) -> ParameterSpecSet:
        spec = super().get_write_cls_parameter_spec()
        # Added by toolkit
        spec.add(ParameterSpec(("dataSetExternalId",), frozenset({"str"}), is_required=False, _is_nullable=False))
        # Replaced by the toolkit
        spec.discard(ParameterSpec(("fileId",), frozenset({"int"}), is_required=True, _is_nullable=False))
        return spec


@final
class FunctionScheduleLoader(
    ResourceLoader[
        FunctionScheduleID, FunctionScheduleWrite, FunctionSchedule, FunctionScheduleWriteList, FunctionSchedulesList
    ]
):
    folder_name = "functions"
    filename_pattern = r"^.*schedule.*$"  # Matches all yaml files who's stem contain *.schedule
    resource_cls = FunctionSchedule
    resource_write_cls = FunctionScheduleWrite
    list_cls = FunctionSchedulesList
    list_write_cls = FunctionScheduleWriteList
    kind = "Schedule"
    dependencies = frozenset({FunctionLoader, GroupResourceScopedLoader, GroupAllScopedLoader})
    _doc_url = "Function-schedules/operation/postFunctionSchedules"
    parent_resource = frozenset({FunctionLoader})
    support_update = False

    _hash_key = "cdf-auth"
    _description_character_limit = 500

    def __init__(self, client: ToolkitClient, build_path: Path | None, console: Console | None):
        super().__init__(client, build_path, console)
        self.authentication_by_id: dict[FunctionScheduleID, ClientCredentials] = {}

    @property
    def display_name(self) -> str:
        return "function schedules"

    @classmethod
    def get_required_capability(
        cls, items: Sequence[FunctionScheduleWrite] | None, read_only: bool
    ) -> list[Capability]:
        if not items and items is not None:
            return []

        function_actions = (
            [FunctionsAcl.Action.Read] if read_only else [FunctionsAcl.Action.Read, FunctionsAcl.Action.Write]
        )
        session_actions = (
            [SessionsAcl.Action.List]
            if read_only
            else [SessionsAcl.Action.List, SessionsAcl.Action.Create, SessionsAcl.Action.Delete]
        )

        return [
            FunctionsAcl(function_actions, FunctionsAcl.Scope.All()),
            SessionsAcl(session_actions, SessionsAcl.Scope.All()),
        ]

    @classmethod
    def dump_id(cls, id: FunctionScheduleID) -> dict[str, Any]:
        return id.dump(camel_case=True)

    @classmethod
    def get_id(cls, item: FunctionScheduleWrite | FunctionSchedule | dict) -> FunctionScheduleID:
        if isinstance(item, dict):
            if missing := tuple(k for k in {"functionExternalId", "name"} if k not in item):
                # We need to raise a KeyError with all missing keys to get the correct error message.
                raise KeyError(*missing)
            return FunctionScheduleID(item["functionExternalId"], item["name"])

        if item.function_external_id is None or item.name is None:
            raise ToolkitRequiredValueError("FunctionSchedule must have functionExternalId and Name set.")
        return FunctionScheduleID(item.function_external_id, item.name)

    @classmethod
    def get_dependent_items(cls, item: dict) -> Iterable[tuple[type[ResourceLoader], Hashable]]:
        if "functionExternalId" in item:
            yield FunctionLoader, item["functionExternalId"]

    def load_resource_file(
        self, filepath: Path, environment_variables: dict[str, str | None] | None = None
    ) -> list[dict[str, Any]]:
        resources = super().load_resource_file(filepath, environment_variables)
        # We need to the auth hash calculation here, as the output of the load_resource_file
        # is used to compare with the CDF resource.
        for resource in resources:
            identifier = self.get_id(resource)
            credentials = read_auth(identifier, resource, self.client, "function schedule", self.console)
            self.authentication_by_id[identifier] = credentials
            if Flags.CREDENTIALS_HASH.is_enabled():
                auth_hash = calculate_secure_hash(credentials.dump(camel_case=True), shorten=True)
                extra_str = f" {self._hash_key}: {auth_hash}"
                if "description" not in resource:
                    resource["description"] = extra_str[1:]
                elif len(resource["description"]) + len(extra_str) < self._description_character_limit:
                    resource["description"] += f"{extra_str}"
                else:
                    LowSeverityWarning(
                        f"Description is too long for schedule {identifier!r}. Truncating..."
                    ).print_warning(console=self.console)
                    truncation = self._description_character_limit - len(extra_str) - 3
                    resource["description"] = f"{resource['description'][:truncation]}...{extra_str}"
        return resources

    def load_resource(self, resource: dict[str, Any], is_dry_run: bool = False) -> FunctionScheduleWrite:
        if "functionId" in resource:
            identifier = self.get_id(resource)
            LowSeverityWarning(f"FunctionId will be ignored in the schedule {identifier!r}").print_warning(
                console=self.console
            )
            resource.pop("functionId", None)

        return FunctionScheduleWrite._load(resource)

    def dump_resource(self, resource: FunctionSchedule, local: dict[str, Any] | None = None) -> dict[str, Any]:
        dumped = resource.as_write().dump()
        local = local or {}
        if "functionId" in dumped and "functionId" not in local:
            dumped.pop("functionId")
        if "authentication" in local:
            # The authentication is not returned in the response, so we need to add it back.
            dumped["authentication"] = local["authentication"]
        return dumped

    def _resolve_functions_ext_id(self, items: FunctionScheduleWriteList) -> FunctionScheduleWriteList:
        functions = FunctionLoader(self.client, None, None).retrieve(
            list(set([item.function_external_id for item in items]))
        )
        for item in items:
            for func in functions:
                if func.external_id == item.function_external_id:
                    item.function_id = func.id  # type: ignore[assignment]
        return items

    def retrieve(self, ids: SequenceNotStr[FunctionScheduleID]) -> FunctionSchedulesList:
        names_by_function: dict[str, set[str]] = defaultdict(set)
        for id_ in ids:
            names_by_function[id_.function_external_id].add(id_.name)
        functions = FunctionLoader(self.client, None, None).retrieve(list(names_by_function))
        schedules = FunctionSchedulesList([])
        for func in functions:
            func_external_id = cast(str, func.external_id)
            function_schedules = self.client.functions.schedules.list(function_id=func.id, limit=-1)
            for schedule in function_schedules:
                schedule.function_external_id = func_external_id
            schedules.extend(
                [schedule for schedule in function_schedules if schedule.name in names_by_function[func_external_id]]
            )
        return schedules

    def create(self, items: FunctionScheduleWriteList) -> FunctionSchedulesList:
        created_list = FunctionSchedulesList([], cognite_client=self.client)
        for item in items:
            id_ = self.get_id(item)
            if id_ not in self.authentication_by_id:
                raise ToolkitRequiredValueError(f"Authentication is missing for schedule {id_!r}")
            client_credentials = self.authentication_by_id[id_]
            try:
                created = self.client.functions.schedules.create(item, client_credentials=client_credentials)
            except CogniteAuthError as e:
                if hint := try_find_error(client_credentials):
                    raise ResourceCreationError(f"Failed to create Function Schedule {id_}: {hint}") from e
                raise e

            # The PySDK mutates the input object, such that function_id is set and function_external_id is None.
            # If we call .get_id on the returned object, it will raise an error we require the function_external_id
            # to be set.
            created.function_external_id = id_.function_external_id
            created_list.append(created)
        return created_list

    def delete(self, ids: SequenceNotStr[FunctionScheduleID]) -> int:
        schedules = self.retrieve(ids)
        count = 0
        for schedule in schedules:
            if schedule.id:
                self.client.functions.schedules.delete(id=schedule.id)
                count += 1
        return count

    def _iterate(
        self,
        data_set_external_id: str | None = None,
        space: str | None = None,
        parent_ids: list[Hashable] | None = None,
    ) -> Iterable[FunctionSchedule]:
        if parent_ids is None:
            yield from self.client.functions.schedules
        else:
            for parent_id in parent_ids:
                if not isinstance(parent_id, str):
                    continue
                yield from self.client.functions.schedules(function_external_id=parent_id)

    @classmethod
    @lru_cache(maxsize=1)
    def get_write_cls_parameter_spec(cls) -> ParameterSpecSet:
        spec = super().get_write_cls_parameter_spec()
        # Added by toolkit
        spec.add(ParameterSpec(("authentication",), frozenset({"dict"}), is_required=False, _is_nullable=False))
        spec.add(
            ParameterSpec(("authentication", "clientId"), frozenset({"str"}), is_required=False, _is_nullable=False)
        )
        spec.add(
            ParameterSpec(("authentication", "clientSecret"), frozenset({"str"}), is_required=False, _is_nullable=False)
        )
        return spec
