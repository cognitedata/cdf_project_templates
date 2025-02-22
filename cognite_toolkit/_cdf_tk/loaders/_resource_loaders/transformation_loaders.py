# Copyright 2023 Cognite AS
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# Copyright 2023 Cognite AS
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from __future__ import annotations

import warnings
from collections import defaultdict
from collections.abc import Hashable, Iterable, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any, cast, final

from cognite.client.data_classes import (
    OidcCredentials,
    Transformation,
    TransformationList,
    TransformationNotification,
    TransformationNotificationList,
    TransformationSchedule,
    TransformationScheduleList,
    TransformationScheduleWrite,
    TransformationScheduleWriteList,
    TransformationWrite,
    TransformationWriteList,
)
from cognite.client.data_classes.capabilities import (
    Capability,
    TransformationsAcl,
)
from cognite.client.data_classes.data_modeling.ids import (
    DataModelId,
    ViewId,
)
from cognite.client.data_classes.transformations.notifications import (
    TransformationNotificationWrite,
    TransformationNotificationWriteList,
)
from cognite.client.exceptions import CogniteAPIError, CogniteAuthError, CogniteDuplicatedError, CogniteNotFoundError
from cognite.client.utils.useful_types import SequenceNotStr
from rich import print

from cognite_toolkit._cdf_tk._parameters import ANY_INT, ParameterSpec, ParameterSpecSet
from cognite_toolkit._cdf_tk.client.data_classes.raw import RawDatabase, RawTable
from cognite_toolkit._cdf_tk.exceptions import (
    ResourceCreationError,
    ToolkitFileNotFoundError,
    ToolkitInvalidParameterNameError,
    ToolkitRequiredValueError,
    ToolkitTypeError,
    ToolkitYAMLFormatError,
)
from cognite_toolkit._cdf_tk.feature_flags import Flags
from cognite_toolkit._cdf_tk.loaders._base_loaders import ResourceLoader
from cognite_toolkit._cdf_tk.utils import (
    calculate_secure_hash,
    humanize_collection,
    in_dict,
    load_yaml_inject_variables,
    quote_int_value_by_key_in_yaml,
    safe_read,
)
from cognite_toolkit._cdf_tk.utils.cdf import try_find_error
from cognite_toolkit._cdf_tk.utils.diff_list import diff_list_hashable

from .auth_loaders import GroupAllScopedLoader
from .data_organization_loaders import DataSetsLoader
from .datamodel_loaders import DataModelLoader, SpaceLoader, ViewLoader
from .group_scoped_loader import GroupResourceScopedLoader
from .raw_loaders import RawDatabaseLoader, RawTableLoader


@final
class TransformationLoader(
    ResourceLoader[str, TransformationWrite, Transformation, TransformationWriteList, TransformationList]
):
    folder_name = "transformations"
    filename_pattern = (
        # Matches all yaml files except file names whose stem contain *.schedule. or .Notification
        r"^(?!.*schedule.*|.*\.notification$).*$"
    )
    resource_cls = Transformation
    resource_write_cls = TransformationWrite
    list_cls = TransformationList
    list_write_cls = TransformationWriteList
    kind = "Transformation"
    dependencies = frozenset(
        {
            DataSetsLoader,
            RawDatabaseLoader,
            GroupAllScopedLoader,
            SpaceLoader,
            ViewLoader,
            DataModelLoader,
            RawTableLoader,
            RawDatabaseLoader,
            GroupResourceScopedLoader,
        }
    )
    _doc_url = "Transformations/operation/createTransformations"
    _hash_key = "-- cdf-auth"

    @property
    def display_name(self) -> str:
        return "transformations"

    @classmethod
    def get_required_capability(
        cls, items: Sequence[TransformationWrite] | None, read_only: bool
    ) -> Capability | list[Capability]:
        if not items and items is not None:
            return []

        actions = (
            [TransformationsAcl.Action.Read]
            if read_only
            else [TransformationsAcl.Action.Read, TransformationsAcl.Action.Write]
        )
        scope: TransformationsAcl.Scope.All | TransformationsAcl.Scope.DataSet = TransformationsAcl.Scope.All()  # type: ignore[valid-type]
        if items is not None:
            if data_set_ids := {item.data_set_id for item in items if item.data_set_id}:
                scope = TransformationsAcl.Scope.DataSet(list(data_set_ids))

        return TransformationsAcl(
            actions,
            scope,  # type: ignore[arg-type]
        )

    @classmethod
    def get_id(cls, item: Transformation | TransformationWrite | dict) -> str:
        if isinstance(item, dict):
            return item["externalId"]
        if item.external_id is None:
            raise ToolkitRequiredValueError("Transformation must have external_id set.")
        return item.external_id

    @classmethod
    def get_internal_id(cls, item: Transformation | dict) -> int:
        if isinstance(item, dict):
            return item["id"]
        if item.id is None:
            raise ToolkitRequiredValueError("Transformation must have id set.")
        return item.id

    @classmethod
    def dump_id(cls, id: str) -> dict[str, Any]:
        return {"externalId": id}

    @classmethod
    def get_dependent_items(cls, item: dict) -> Iterable[tuple[type[ResourceLoader], Hashable]]:
        if "dataSetExternalId" in item:
            yield DataSetsLoader, item["dataSetExternalId"]
        if destination := item.get("destination", {}):
            if not isinstance(destination, dict):
                return
            if destination.get("type") == "raw" and in_dict(("database", "table"), destination):
                yield RawDatabaseLoader, RawDatabase(destination["database"])
                yield RawTableLoader, RawTable(destination["database"], destination["table"])
            elif destination.get("type") in ("nodes", "edges") and (view := destination.get("view", {})):
                if space := destination.get("instanceSpace"):
                    yield SpaceLoader, space
                if in_dict(("space", "externalId", "version"), view):
                    view["version"] = str(view["version"])
                    yield ViewLoader, ViewId.load(view)
            elif destination.get("type") == "instances":
                if space := destination.get("instanceSpace"):
                    yield SpaceLoader, space
                if data_model := destination.get("dataModel"):
                    if in_dict(("space", "externalId", "version"), data_model):
                        data_model["version"] = str(data_model["version"])
                        yield DataModelLoader, DataModelId.load(data_model)

    def safe_read(self, filepath: Path | str) -> str:
        # If the destination is a DataModel or a View we need to ensure that the version is a string
        return quote_int_value_by_key_in_yaml(safe_read(filepath), key="version")

    def load_resource_file(
        self, filepath: Path, environment_variables: dict[str, str | None] | None = None
    ) -> list[dict[str, Any]]:
        resources = load_yaml_inject_variables(
            self.safe_read(filepath),
            environment_variables or {},
            original_filepath=filepath,
        )

        raw_list = resources if isinstance(resources, list) else [resources]
        for item in raw_list:
            query_file: Path | None = None
            if "queryFile" in item:
                if filepath is None:
                    raise ValueError("filepath must be set if queryFile is set")
                query_file = filepath.parent / Path(item.pop("queryFile"))

            external_id = self.get_id(item)
            if query_file is None and "query" not in item:
                if filepath is None:
                    raise ValueError("filepath must be set if query is not set")
                raise ToolkitYAMLFormatError(
                    f"query property or is missing. It can be inline or a separate file named {filepath.stem}.sql or {external_id}.sql",
                    filepath,
                )
            elif query_file and not query_file.exists():
                # We checked above that filepath is not None
                raise ToolkitFileNotFoundError(f"Query file {query_file.as_posix()} not found", filepath)  # type: ignore[union-attr]
            elif query_file and "query" in item:
                raise ToolkitYAMLFormatError(
                    f"query property is ambiguously defined in both the yaml file and a separate file named {query_file}\n"
                    f"Please remove one of the definitions, either the query property in {filepath} or the file {query_file}",
                    filepath,
                )
            elif query_file:
                item["query"] = safe_read(query_file)

            if Flags.CREDENTIALS_HASH.is_enabled():
                auth_dict: dict[str, Any] = {}
                for key in [
                    "authentication",
                    "sourceOidcCredentials",
                    "destinationOidcCredentials",
                    "sourceNonce",
                    "destinationNonce",
                ]:
                    if key in item:
                        auth_dict[key] = item[key]
                if auth_dict:
                    auth_hash = calculate_secure_hash(auth_dict, shorten=True)
                    if "query" in item:
                        item["query"] = f"{self._hash_key}: {auth_hash}\n{item['query']}"
        return raw_list

    def load_resource(self, resource: dict[str, Any], is_dry_run: bool = False) -> TransformationWrite:
        invalid_parameters: dict[str, str] = {}
        if "action" in resource and "conflictMode" not in resource:
            invalid_parameters["action"] = "conflictMode"
        if "shared" in resource and "isPublic" not in resource:
            invalid_parameters["shared"] = "isPublic"
        if invalid_parameters:
            raise ToolkitInvalidParameterNameError(
                "Parameters invalid. These are specific for the "
                "'transformation-cli' and not supported by cognite-toolkit",
                resource.get("externalId", "<Missing>"),
                invalid_parameters,
            )

        if ds_external_id := resource.pop("dataSetExternalId", None):
            resource["dataSetId"] = self.client.lookup.data_sets.id(ds_external_id, is_dry_run)
        if "conflictMode" not in resource:
            # Todo; Bug SDK missing default value
            resource["conflictMode"] = "upsert"

        source_oidc_credentials = (
            resource.get("authentication", {}).get("read") or resource.get("authentication") or None
        )
        destination_oidc_credentials = (
            resource.get("authentication", {}).get("write") or resource.get("authentication") or None
        )
        transformation = TransformationWrite._load(resource)
        try:
            transformation.source_oidc_credentials = source_oidc_credentials and OidcCredentials.load(
                source_oidc_credentials
            )

            transformation.destination_oidc_credentials = destination_oidc_credentials and OidcCredentials.load(
                destination_oidc_credentials
            )
        except KeyError as e:
            item_id = self.get_id(resource)
            raise ToolkitTypeError(
                f"Ill-formed Transformation {item_id}: Authentication property is missing required fields"
            ) from e
        return transformation

    def dump_resource(self, resource: Transformation, local: dict[str, Any] | None = None) -> dict[str, Any]:
        dumped = resource.as_write().dump()
        local = local or {}
        if data_set_id := dumped.pop("dataSetId", None):
            dumped["dataSetExternalId"] = self.client.lookup.data_sets.external_id(data_set_id)
        if "isPublic" in dumped and "isPublic" not in local:
            # Default set from server side.
            dumped.pop("isPublic")
        if "authentication" in local:
            # The hash added to the beginning of the query detects the change in the authentication
            dumped["authentication"] = local["authentication"]
        return dumped

    def split_resource(
        self, base_filepath: Path, resource: dict[str, Any]
    ) -> Iterable[tuple[Path, dict[str, Any] | str]]:
        if query := resource.pop("query", None):
            yield base_filepath.with_suffix(".sql"), cast(str, query)

        yield base_filepath, resource

    def diff_list(
        self, local: list[Any], cdf: list[Any], json_path: tuple[str | int, ...]
    ) -> tuple[dict[int, int], list[int]]:
        if json_path[-1] == "scopes":
            return diff_list_hashable(local, cdf)
        return super().diff_list(local, cdf, json_path)

    def create(self, items: Sequence[TransformationWrite]) -> TransformationList:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            # Ignoring warnings from SDK about session unauthorized. Motivation is CDF is not fast enough to
            # handle first a group that authorizes the session and then the transformation.
            try:
                return self.client.transformations.create(items)
            except CogniteAuthError as e:
                if error := self._create_auth_creation_error(items):
                    raise error from e
                raise e

    def retrieve(self, ids: SequenceNotStr[str | int]) -> TransformationList:
        internal_ids, external_ids = self._split_ids(ids)
        return self.client.transformations.retrieve_multiple(
            ids=internal_ids, external_ids=external_ids, ignore_unknown_ids=True
        )

    def update(self, items: Sequence[TransformationWrite]) -> TransformationList:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            # Ignoring warnings from SDK about session unauthorized. Motivation is CDF is not fast enough to
            # handle first a group that authorizes the session and then the transformation.
            try:
                return self.client.transformations.update(items, mode="replace")
            except CogniteAuthError as e:
                if error := self._create_auth_creation_error(items):
                    raise error from e
                raise e

    @staticmethod
    def _create_auth_creation_error(items: Sequence[TransformationWrite]) -> ResourceCreationError | None:
        hints_by_id: dict[str, list[str]] = defaultdict(list)
        for item in items:
            if not item.external_id:
                continue
            hint_source = try_find_error(item.source_oidc_credentials)
            if hint_source:
                hints_by_id[item.external_id].append(hint_source)
            if hint_dest := try_find_error(item.destination_oidc_credentials):
                if hint_dest != hint_source:
                    hints_by_id[item.external_id].append(hint_dest)
        if hints_by_id:
            body = "\n".join(f"  {id_} - {humanize_collection(hints)}" for id_, hints in hints_by_id.items())
            return ResourceCreationError(
                f"Failed to create Transformation(s) du to likely invalid credentials:\n{body}",
            )
        return None

    def delete(self, ids: SequenceNotStr[str | int]) -> int:
        existing = self.retrieve(ids).as_ids()
        if existing:
            self.client.transformations.delete(id=existing, ignore_unknown_ids=True)
        return len(existing)

    def _iterate(
        self,
        data_set_external_id: str | None = None,
        space: str | None = None,
        parent_ids: list[Hashable] | None = None,
    ) -> Iterable[Transformation]:
        return iter(
            self.client.transformations(data_set_external_ids=[data_set_external_id] if data_set_external_id else None)
        )

    @classmethod
    @lru_cache(maxsize=1)
    def get_write_cls_parameter_spec(cls) -> ParameterSpecSet:
        spec = super().get_write_cls_parameter_spec()
        spec.update(
            ParameterSpecSet(
                {
                    # Added by toolkit
                    ParameterSpec(("dataSetExternalId",), frozenset({"str"}), is_required=False, _is_nullable=False),
                    ParameterSpec(("authentication",), frozenset({"dict"}), is_required=False, _is_nullable=False),
                    ParameterSpec(
                        ("authentication", "clientId"), frozenset({"str"}), is_required=True, _is_nullable=False
                    ),
                    ParameterSpec(
                        ("authentication", "clientSecret"), frozenset({"str"}), is_required=True, _is_nullable=False
                    ),
                    ParameterSpec(
                        ("authentication", "scopes"), frozenset({"str"}), is_required=False, _is_nullable=False
                    ),
                    ParameterSpec(
                        ("authentication", "scopes", ANY_INT), frozenset({"str"}), is_required=False, _is_nullable=False
                    ),
                    ParameterSpec(
                        ("authentication", "tokenUri"), frozenset({"str"}), is_required=True, _is_nullable=False
                    ),
                    ParameterSpec(
                        ("authentication", "cdfProjectName"), frozenset({"str"}), is_required=True, _is_nullable=False
                    ),
                    ParameterSpec(
                        ("authentication", "audience"), frozenset({"str"}), is_required=False, _is_nullable=False
                    ),
                    ParameterSpec(("queryFile",), frozenset({"str"}), is_required=False, _is_nullable=False),
                }
            )
        )
        return spec


@final
class TransformationScheduleLoader(
    ResourceLoader[
        str,
        TransformationScheduleWrite,
        TransformationSchedule,
        TransformationScheduleWriteList,
        TransformationScheduleList,
    ]
):
    folder_name = "transformations"
    # Matches all yaml files whose stem contains *schedule or *TransformationSchedule.
    filename_pattern = r"^.*schedule$"
    resource_cls = TransformationSchedule
    resource_write_cls = TransformationScheduleWrite
    list_cls = TransformationScheduleList
    list_write_cls = TransformationScheduleWriteList
    kind = "Schedule"
    dependencies = frozenset({TransformationLoader})
    _doc_url = "Transformation-Schedules/operation/createTransformationSchedules"
    parent_resource = frozenset({TransformationLoader})

    @property
    def display_name(self) -> str:
        return "transformation schedules"

    @classmethod
    def get_required_capability(
        cls, items: Sequence[TransformationScheduleWrite] | None, read_only: bool
    ) -> list[Capability]:
        # Access for transformations schedules is checked by the transformation that is deployed
        # first, so we don't need to check for any capabilities here.
        return []

    @classmethod
    def get_id(cls, item: TransformationSchedule | TransformationScheduleWrite | dict) -> str:
        if isinstance(item, dict):
            return item["externalId"]
        if item.external_id is None:
            raise ToolkitRequiredValueError("TransformationSchedule must have external_id set.")
        return item.external_id

    @classmethod
    def dump_id(cls, id: str) -> dict[str, Any]:
        return {"externalId": id}

    @classmethod
    def get_dependent_items(cls, item: dict) -> Iterable[tuple[type[ResourceLoader], Hashable]]:
        if "externalId" in item:
            yield TransformationLoader, item["externalId"]

    def create(self, items: Sequence[TransformationScheduleWrite]) -> TransformationScheduleList:
        try:
            return self.client.transformations.schedules.create(list(items))
        except CogniteDuplicatedError as e:
            existing = {external_id for dup in e.duplicated if (external_id := dup.get("externalId", None))}
            print(
                f"  [bold yellow]WARNING:[/] {len(e.duplicated)} transformation schedules already exist(s): {existing}"
            )
            new_items = [item for item in items if item.external_id not in existing]
            return self.client.transformations.schedules.create(new_items)

    def retrieve(self, ids: SequenceNotStr[str]) -> TransformationScheduleList:
        return self.client.transformations.schedules.retrieve_multiple(external_ids=ids, ignore_unknown_ids=True)

    def update(self, items: TransformationScheduleWriteList) -> TransformationScheduleList:
        return self.client.transformations.schedules.update(items, mode="replace")

    def delete(self, ids: str | SequenceNotStr[str] | None) -> int:
        try:
            self.client.transformations.schedules.delete(
                external_id=cast(SequenceNotStr[str], ids), ignore_unknown_ids=False
            )
            return len(cast(SequenceNotStr[str], ids))
        except CogniteNotFoundError as e:
            return len(cast(SequenceNotStr[str], ids)) - len(e.not_found)

    def _iterate(
        self,
        data_set_external_id: str | None = None,
        space: str | None = None,
        parent_ids: list[Hashable] | None = None,
    ) -> Iterable[TransformationSchedule]:
        if parent_ids is None:
            yield from iter(self.client.transformations.schedules)
        else:
            for transformation_id in parent_ids:
                if isinstance(transformation_id, str):
                    res = self.client.transformations.schedules.retrieve(external_id=transformation_id)
                    if res:
                        yield res
                elif isinstance(transformation_id, int):
                    res = self.client.transformations.schedules.retrieve(id=transformation_id)
                    if res:
                        yield res


@final
class TransformationNotificationLoader(
    ResourceLoader[
        str,
        TransformationNotificationWrite,
        TransformationNotification,
        TransformationNotificationWriteList,
        TransformationNotificationList,
    ]
):
    folder_name = "transformations"
    # Matches all yaml files whose stem ends with *Notification.
    filename_pattern = r"^.*Notification$"
    resource_cls = TransformationNotification
    resource_write_cls = TransformationNotificationWrite
    list_cls = TransformationNotificationList
    list_write_cls = TransformationNotificationWriteList
    kind = "Notification"
    dependencies = frozenset({TransformationLoader})
    _doc_url = "Transformation-Notifications/operation/createTransformationNotifications"
    _split_character = "@@@"
    parent_resource = frozenset({TransformationLoader})

    @property
    def display_name(self) -> str:
        return "transformation notifications"

    @classmethod
    def get_id(cls, item: TransformationNotification | TransformationNotificationWrite | dict) -> str:
        if isinstance(item, dict):
            if missing := tuple(k for k in {"transformationExternalId", "destination"} if k not in item):
                # We need to raise a KeyError with all missing keys to get the correct error message.
                raise KeyError(*missing)
            return f"{item['transformationExternalId']}{cls._split_character}{item['destination']}"

        return f"{item.transformation_external_id}{cls._split_character}{item.destination}"

    @classmethod
    def dump_id(cls, id: str) -> dict[str, Any]:
        transformation_id, destination = id.split(cls._split_character, maxsplit=1)
        return {
            "transformationExternalId": transformation_id,
            "destination": destination,
        }

    @classmethod
    def get_required_capability(
        cls, items: Sequence[TransformationNotificationWrite] | None, read_only: bool
    ) -> Capability | list[Capability]:
        # Access for transformation notification is checked by the transformation that is deployed
        # first, so we don't need to check for any capabilities here.
        return []

    def dump_resource(
        self, resource: TransformationNotification, local: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        dumped = resource.as_write().dump()
        if local and "transformationExternalId" in local:
            dumped.pop("transformationId")
            dumped["transformationExternalId"] = local["transformationExternalId"]
        return dumped

    def create(self, items: TransformationNotificationWriteList) -> TransformationNotificationList:
        return self.client.transformations.notifications.create(items)  # type: ignore[return-value]

    def retrieve(self, ids: SequenceNotStr[str]) -> TransformationNotificationList:
        retrieved = TransformationNotificationList([])
        for id_ in ids:
            try:
                transformation_external_id, destination = id_.rsplit(self._split_character, maxsplit=1)
            except ValueError:
                # This should never happen, and is a bug in the toolkit if it occurs. Creating a nice error message
                # here so that if it does happen, it will be easier to debug.
                raise ValueError(
                    f"Invalid externalId: {id_}. Must be in the format 'transformationExternalId{self._split_character}destination'"
                )
            try:
                result = self.client.transformations.notifications.list(
                    transformation_external_id=transformation_external_id, destination=destination, limit=-1
                )
                # list() does not return the transformation_external_id on items
                for notification in result:
                    notification.transformation_external_id = transformation_external_id

            except CogniteAPIError:
                # The notification endpoint gives a 500 if the notification does not exist.
                # The issue has been reported to the service team.
                continue

            retrieved.extend(result)

        return retrieved

    def update(self, items: TransformationNotificationWriteList) -> TransformationNotificationList:
        # Note that since a notification is identified by the combination of transformationExternalId and destination,
        # which is the entire object, an update should never happen. However, implementing just in case.
        item_by_id = {self.get_id(item): item for item in items}
        existing = self.retrieve(list(item_by_id.keys()))
        exiting_by_id = {self.get_id(item): item for item in existing}
        create: list[TransformationNotificationWrite] = []
        unchanged: list[str] = []
        delete: list[int] = []
        for id_, local_item in item_by_id.items():
            existing_item = exiting_by_id.get(id_)
            local_dict = local_item.dump()
            if existing_item and local_item == self.dump_resource(existing_item, local_dict):
                unchanged.append(self.get_id(existing_item))
            else:
                create.append(local_item)
            if existing_item:
                delete.append(cast(int, existing_item.id))
        if delete:
            self.client.transformations.notifications.delete(delete)
        updated_by_id: dict[str, TransformationNotification] = {}
        if create:
            # Bug in SDK
            created = self.client.transformations.notifications.create(create)
            updated_by_id.update({self.get_id(item): item for item in created})
        if unchanged:
            updated_by_id.update({id_: exiting_by_id[id_] for id_ in unchanged})
        return TransformationNotificationList([updated_by_id[id_] for id_ in item_by_id.keys()])

    def delete(self, ids: SequenceNotStr[str]) -> int:
        # Note that it is theoretically possible that more items will be deleted than
        # input ids. This is because TransformationNotifications are identified by an internal id,
        # while the toolkit uses the transformationExternalId + destination as the id. Thus, there could
        # be multiple notifications for the same transformationExternalId + destination.
        if existing := self.retrieve(ids):
            self.client.transformations.notifications.delete([item.id for item in existing])  # type: ignore[misc]
        return len(existing)

    def _iterate(
        self,
        data_set_external_id: str | None = None,
        space: str | None = None,
        parent_ids: list[Hashable] | None = None,
    ) -> Iterable[TransformationNotification]:
        if parent_ids is None:
            yield from iter(self.client.transformations.notifications)
        else:
            for transformation_id in parent_ids:
                if isinstance(transformation_id, str):
                    yield from self.client.transformations.notifications(transformation_external_id=transformation_id)
                elif isinstance(transformation_id, int):
                    yield from self.client.transformations.notifications(transformation_id=transformation_id)

    @classmethod
    def get_dependent_items(cls, item: dict) -> Iterable[tuple[type[ResourceLoader], Hashable]]:
        """Returns all items that this item requires.

        For example, a TimeSeries requires a DataSet, so this method would return the
        DatasetLoader and identifier of that dataset.
        """
        if "transformationExternalId" in item:
            yield TransformationLoader, item["transformationExternalId"]
