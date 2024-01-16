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

import itertools
import json
import re
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Literal, cast, final

import yaml
from cognite.client import CogniteClient
from cognite.client.data_classes import (
    DatapointsList,
    DataSet,
    DataSetList,
    DataSetWrite,
    DataSetWriteList,
    ExtractionPipeline,
    ExtractionPipelineConfig,
    ExtractionPipelineList,
    FileMetadata,
    FileMetadataList,
    FileMetadataUpdate,
    FileMetadataWrite,
    FileMetadataWriteList,
    OidcCredentials,
    TimeSeries,
    TimeSeriesList,
    TimeSeriesWrite,
    TimeSeriesWriteList,
    Transformation,
    TransformationList,
    TransformationSchedule,
    TransformationScheduleList,
    TransformationScheduleWrite,
    TransformationScheduleWriteList,
    TransformationWrite,
    TransformationWriteList,
    capabilities,
    filters,
)
from cognite.client.data_classes.capabilities import (
    Capability,
    DataModelInstancesAcl,
    DataModelsAcl,
    DataSetsAcl,
    ExtractionPipelinesAcl,
    FilesAcl,
    GroupsAcl,
    RawAcl,
    TimeSeriesAcl,
    TransformationsAcl,
)
from cognite.client.data_classes.data_modeling import (
    Container,
    ContainerApply,
    ContainerApplyList,
    ContainerList,
    ContainerProperty,
    DataModel,
    DataModelApply,
    DataModelApplyList,
    DataModelList,
    Edge,
    EdgeApply,
    EdgeApplyResultList,
    EdgeList,
    Node,
    NodeApply,
    NodeApplyResultList,
    NodeList,
    Space,
    SpaceApply,
    SpaceApplyList,
    SpaceList,
    View,
    ViewApply,
    ViewApplyList,
    ViewList,
)
from cognite.client.data_classes.data_modeling.ids import (
    ContainerId,
    DataModelId,
    EdgeId,
    NodeId,
    ViewId,
)
from cognite.client.data_classes.extractionpipelines import (
    ExtractionPipelineConfigList,
    ExtractionPipelineConfigWrite,
    ExtractionPipelineConfigWriteList,
    ExtractionPipelineWrite,
    ExtractionPipelineWriteList,
)
from cognite.client.data_classes.iam import Group, GroupList, GroupWrite, GroupWriteList
from cognite.client.exceptions import CogniteAPIError, CogniteDuplicatedError, CogniteNotFoundError
from cognite.client.utils.useful_types import SequenceNotStr
from rich import print

from cognite_toolkit.cdf_tk.utils import CDFToolConfig, load_yaml_inject_variables

from ._base_loaders import ResourceContainerLoader, ResourceLoader
from .data_classes import LoadableEdges, LoadableNodes, RawDatabaseTable, RawTableList

_MIN_TIMESTAMP_MS = -2208988800000  # 1900-01-01 00:00:00.000
_MAX_TIMESTAMP_MS = 4102444799999  # 2099-12-31 23:59:59.999


@final
class AuthLoader(ResourceLoader[str, GroupWrite, Group, GroupWriteList, GroupList]):
    support_drop = False
    api_name = "iam.groups"
    folder_name = "auth"
    resource_cls = Group
    resource_write_cls = GroupWrite
    list_cls = GroupList
    list_write_cls = GroupWriteList
    identifier_key = "name"
    resource_scopes = frozenset(
        {
            capabilities.IDScope,
            capabilities.SpaceIDScope,
            capabilities.DataSetScope,
            capabilities.TableScope,
            capabilities.AssetRootIDScope,
            capabilities.ExtractionPipelineScope,
            capabilities.IDScopeLowerCase,
        }
    )
    resource_scope_names = frozenset({scope._scope_name for scope in resource_scopes})  # type: ignore[attr-defined]

    def __init__(
        self,
        client: CogniteClient,
        target_scopes: Literal[
            "all",
            "all_scoped_only",
            "resource_scoped_only",
        ] = "all",
    ):
        super().__init__(client)
        self.target_scopes = target_scopes

    @property
    def display_name(self) -> str:
        return f"{self.api_name}({self.target_scopes.removesuffix('_only')})"

    @classmethod
    def create_loader(
        cls,
        ToolGlobals: CDFToolConfig,
        target_scopes: Literal[
            "all",
            "all_scoped_only",
            "resource_scoped_only",
        ] = "all",
    ) -> AuthLoader:
        client = ToolGlobals.verify_capabilities(capability=cls.get_required_capability(ToolGlobals))
        return AuthLoader(client, target_scopes)

    @classmethod
    def get_required_capability(cls, ToolGlobals: CDFToolConfig) -> Capability | list[Capability]:
        return GroupsAcl(
            [GroupsAcl.Action.Read, GroupsAcl.Action.List, GroupsAcl.Action.Create, GroupsAcl.Action.Delete],
            GroupsAcl.Scope.All(),
        )

    @classmethod
    def get_id(cls, item: GroupWrite | Group) -> str:
        return item.name

    def load_resource(
        self, filepath: Path, ToolGlobals: CDFToolConfig, skip_validation: bool
    ) -> GroupWrite | GroupWriteList | None:
        raw = load_yaml_inject_variables(filepath, ToolGlobals.environment_variables(), required_return_type="dict")
        is_resource_scoped = False
        for capability in raw.get("capabilities", []):
            for _, values in capability.items():
                scope = values.get("scope", {})
                is_resource_scoped = any(scope_name in scope for scope_name in self.resource_scope_names)
                if self.target_scopes == "all_scoped_only" and is_resource_scoped:
                    # If a group has a single capability with a resource scope, we skip it.
                    # None indicates skip
                    return None

                for scope_name, verify_method in [
                    ("datasetScope", ToolGlobals.verify_dataset),
                    ("idScope", ToolGlobals.verify_dataset),
                    ("extractionPipelineScope", ToolGlobals.verify_extraction_pipeline),
                ]:
                    if ids := scope.get(scope_name, {}).get("ids", []):
                        values["scope"][scope_name]["ids"] = [
                            verify_method(ext_id, skip_validation) if isinstance(ext_id, str) else ext_id
                            for ext_id in ids
                        ]

        if not is_resource_scoped and self.target_scopes == "resource_scoped_only":
            # If a group has no resource scoped capabilities, we skip it.
            return None

        return GroupWrite.load(raw)

    def create(self, items: Sequence[GroupWrite]) -> GroupList:
        if len(items) == 0:
            return GroupList([])
        # We MUST retrieve all the old groups BEFORE we add the new, if not the new will be deleted
        old_groups = self.client.iam.groups.list(all=True)
        old_group_by_names = {g.name: g for g in old_groups.as_write()}
        changed = []
        for item in items:
            if (old := old_group_by_names.get(item.name)) and old == item:
                # Ship unchanged groups
                continue
            changed.append(item)
        if len(changed) == 0:
            return GroupList([])
        created = self.client.iam.groups.create(changed)
        created_names = {g.name for g in created}
        to_delete = [g.id for g in old_groups if g.name in created_names and g.id]
        self.client.iam.groups.delete(to_delete)
        return created

    def update(self, items: Sequence[GroupWrite]) -> GroupList:
        return self.client.iam.groups.create(items)

    def retrieve(self, ids: SequenceNotStr[str]) -> GroupList:
        remote = self.client.iam.groups.list(all=True)
        found = [g for g in remote if g.name in ids]
        return GroupList(found)

    def delete(self, ids: SequenceNotStr[str]) -> int:
        id_list = list(ids)
        # Let's prevent that we delete groups we belong to
        try:
            groups = self.client.iam.groups.list()
        except Exception as e:
            print(
                f"[bold red]ERROR:[/] Failed to retrieve the current service principal's groups. Aborting group deletion.\n{e}"
            )
            return 0
        my_source_ids = set()
        for g in groups:
            if g.source_id not in my_source_ids:
                my_source_ids.add(g.source_id)
        groups = self.retrieve(ids)
        for g in groups:
            if g.source_id in my_source_ids:
                print(
                    f"  [bold yellow]WARNING:[/] Not deleting group {g.name} with sourceId {g.source_id} as it is used by the current service principal."
                )
                print("     If you want to delete this group, you must do it manually.")
                if g.name not in id_list:
                    print(f"    [bold red]ERROR[/] You seem to have duplicate groups of name {g.name}.")
                else:
                    id_list.remove(g.name)
        found = [g.id for g in groups if g.name in id_list and g.id]
        self.client.iam.groups.delete(found)
        return len(found)


@final
class DataSetsLoader(ResourceLoader[str, DataSetWrite, DataSet, DataSetWriteList, DataSetList]):
    support_drop = False
    api_name = "data_sets"
    folder_name = "data_sets"
    resource_cls = DataSet
    resource_write_cls = DataSetWrite
    list_cls = DataSetList
    list_write_cls = DataSetWriteList

    @classmethod
    def get_required_capability(cls, ToolGlobals: CDFToolConfig) -> Capability:
        return DataSetsAcl(
            [DataSetsAcl.Action.Read, DataSetsAcl.Action.Write],
            DataSetsAcl.Scope.All(),
        )

    @classmethod
    def get_id(cls, item: DataSet | DataSetWrite) -> str:
        if item.external_id is None:
            raise ValueError("DataSet must have external_id set.")
        return item.external_id

    def load_resource(self, filepath: Path, ToolGlobals: CDFToolConfig, skip_validation: bool) -> DataSetWriteList:
        resource = load_yaml_inject_variables(filepath, {})

        data_sets = [resource] if isinstance(resource, dict) else resource

        for data_set in data_sets:
            if data_set.get("metadata"):
                for key, value in data_set["metadata"].items():
                    data_set["metadata"][key] = json.dumps(value)
            if data_set.get("writeProtected") is None:
                # Todo: Setting missing default value, bug in SDK.
                data_set["writeProtected"] = False
            if data_set.get("metadata") is None:
                # Todo: Wrongly set to empty dict, bug in SDK.
                data_set["metadata"] = {}

        return DataSetWriteList.load(data_sets)

    def create(self, items: Sequence[DataSetWrite]) -> DataSetList:
        items = list(items)
        created = DataSetList([], cognite_client=self.client)
        # There is a bug in the data set API, so only one duplicated data set is returned at the time,
        # so we need to iterate.
        while len(items) > 0:
            try:
                created.extend(DataSetList(self.client.data_sets.create(items)))
                return created
            except CogniteDuplicatedError as e:
                if len(e.duplicated) < len(items):
                    for dup in e.duplicated:
                        ext_id = dup.get("externalId", None)
                        for item in items:
                            if item.external_id == ext_id:
                                items.remove(item)
                else:
                    items = []
        return created

    def retrieve(self, ids: SequenceNotStr[str]) -> DataSetList:
        return self.client.data_sets.retrieve_multiple(external_ids=cast(Sequence, ids), ignore_unknown_ids=True)

    def delete(self, ids: SequenceNotStr[str]) -> int:
        raise NotImplementedError("CDF does not support deleting data sets.")


@final
class RawDatabaseLoader(
    ResourceContainerLoader[RawDatabaseTable, RawDatabaseTable, RawDatabaseTable, RawTableList, RawTableList]
):
    item_name = "raw tables"
    api_name = "raw.databases"
    folder_name = "raw"
    resource_cls = RawDatabaseTable
    resource_write_cls = RawDatabaseTable
    list_cls = RawTableList
    list_write_cls = RawTableList
    identifier_key = "table_name"

    def __init__(self, client: CogniteClient):
        super().__init__(client)
        self._loaded_db_names: set[str] = set()

    @classmethod
    def get_required_capability(cls, ToolGlobals: CDFToolConfig) -> Capability:
        return RawAcl([RawAcl.Action.Read, RawAcl.Action.Write], RawAcl.Scope.All())

    @classmethod
    def get_id(cls, item: RawDatabaseTable) -> RawDatabaseTable:
        return item

    def load_resource(
        self, filepath: Path, ToolGlobals: CDFToolConfig, skip_validation: bool
    ) -> RawDatabaseTable | RawTableList | None:
        resource = super().load_resource(filepath, ToolGlobals, skip_validation)
        if resource is None:
            return None
        dbs = resource if isinstance(resource, RawTableList) else RawTableList([resource])
        # This loader is only used for the raw databases, so we need to remove the table names
        # such that the comparison will work correctly.
        db_names = set(dbs.as_db_names()) - self._loaded_db_names
        if not db_names:
            # All databases already loaded
            return None
        self._loaded_db_names.update(db_names)
        return RawTableList([RawDatabaseTable(db_name=db_name) for db_name in db_names])

    def create(self, items: RawTableList) -> RawTableList:
        database_list = self.client.raw.databases.create(items.as_db_names())
        return RawTableList([RawDatabaseTable(db_name=db.name) for db in database_list])

    def retrieve(self, ids: SequenceNotStr[RawDatabaseTable]) -> RawTableList:
        database_list = self.client.raw.databases.list(limit=-1)
        target_dbs = {db.db_name for db in ids}
        return RawTableList([RawDatabaseTable(db_name=db.name) for db in database_list if db.name in target_dbs])

    def update(self, items: Sequence[RawDatabaseTable]) -> RawTableList:
        raise NotImplementedError("Raw tables do not support update.")

    def delete(self, ids: SequenceNotStr[RawDatabaseTable]) -> int:
        db_names = [table.db_name for table in ids]
        try:
            self.client.raw.databases.delete(name=db_names)
        except CogniteAPIError as e:
            # Bug in API, missing is returned as failed
            if e.failed and (db_names := [name for name in db_names if name not in e.failed]):
                self.client.raw.databases.delete(name=db_names)
            else:
                raise e
        return len(db_names)

    def count(self, ids: SequenceNotStr[RawDatabaseTable]) -> int:
        nr_of_tables = 0
        for db_name, raw_tables in itertools.groupby(sorted(ids), key=lambda x: x.db_name):
            try:
                tables = self.client.raw.tables.list(db_name=db_name, limit=-1)
            except CogniteAPIError as e:
                if db_name in {item.get("name") for item in e.missing or []}:
                    continue
                raise e
            nr_of_tables += len(tables.data)
        return nr_of_tables

    def drop_data(self, ids: SequenceNotStr[RawDatabaseTable]) -> int:
        nr_of_tables = 0
        for db_name, raw_tables in itertools.groupby(sorted(ids), key=lambda x: x.db_name):
            try:
                existing = set(self.client.raw.tables.list(db_name=db_name, limit=-1).as_names())
            except CogniteAPIError as e:
                if db_name in {item.get("name") for item in e.missing or []}:
                    continue
                raise e
            tables = [table.table_name for table in raw_tables if table.table_name in existing]
            if tables:
                self.client.raw.tables.delete(db_name=db_name, name=tables)
                nr_of_tables += len(tables)
        return nr_of_tables


@final
class RawTableLoader(
    ResourceContainerLoader[RawDatabaseTable, RawDatabaseTable, RawDatabaseTable, RawTableList, RawTableList]
):
    item_name = "raw cells"
    api_name = "raw.tables"
    folder_name = "raw"
    resource_cls = RawDatabaseTable
    resource_write_cls = RawDatabaseTable
    list_cls = RawTableList
    list_write_cls = RawTableList
    identifier_key = "table_name"

    @classmethod
    def get_required_capability(cls, ToolGlobals: CDFToolConfig) -> Capability:
        return RawAcl([RawAcl.Action.Read, RawAcl.Action.Write], RawAcl.Scope.All())

    @classmethod
    def get_id(cls, item: RawDatabaseTable) -> RawDatabaseTable:
        return item

    def create(self, items: RawTableList) -> RawTableList:
        created = RawTableList([])
        for db_name, raw_tables in itertools.groupby(sorted(items), key=lambda x: x.db_name):
            tables = [table.table_name for table in raw_tables]
            new_tables = self.client.raw.tables.create(db_name=db_name, name=tables)
            created.extend([RawDatabaseTable(db_name=db_name, table_name=table.name) for table in new_tables])
        return created

    def retrieve(self, ids: SequenceNotStr[RawDatabaseTable]) -> RawTableList:
        retrieved = RawTableList([])
        for db_name, raw_tables in itertools.groupby(sorted(ids), key=lambda x: x.db_name):
            expected_tables = {table.table_name for table in raw_tables}
            try:
                tables = self.client.raw.tables.list(db_name=db_name, limit=-1)
            except CogniteAPIError as e:
                if db_name in {item.get("name") for item in e.missing or []}:
                    continue
                raise e
            retrieved.extend(
                [
                    RawDatabaseTable(db_name=db_name, table_name=table.name)
                    for table in tables
                    if table.name in expected_tables
                ]
            )
        return retrieved

    def update(self, items: Sequence[RawDatabaseTable]) -> RawTableList:
        raise NotImplementedError("Raw tables do not support update.")

    def delete(self, ids: SequenceNotStr[RawDatabaseTable]) -> int:
        count = 0
        for db_name, raw_tables in itertools.groupby(sorted(ids, key=lambda x: x.db_name), key=lambda x: x.db_name):
            tables = [table.table_name for table in raw_tables if table.table_name]
            if tables:
                try:
                    self.client.raw.tables.delete(db_name=db_name, name=tables)
                except CogniteAPIError as e:
                    if re.match(r"^Database named (.*)+ not found$", e.message):
                        continue
                    elif tables := [
                        name for name in tables if name not in {item.get("name") for item in e.missing or []}
                    ]:
                        self.client.raw.tables.delete(db_name=db_name, name=tables)
                    else:
                        raise e
                count += len(tables)
        return count

    def count(self, ids: SequenceNotStr[RawDatabaseTable]) -> int:
        print("  [bold yellow]WARNING:[/] Raw rows do not support count (there is no aggregation method).")
        return 0

    def drop_data(self, ids: SequenceNotStr[RawDatabaseTable]) -> int:
        count = 0
        for db_name, raw_tables in itertools.groupby(sorted(ids, key=lambda x: x.db_name), key=lambda x: x.db_name):
            try:
                existing = set(self.client.raw.tables.list(db_name=db_name, limit=-1).as_names())
            except CogniteAPIError as e:
                if db_name in {item.get("name") for item in e.missing or []}:
                    continue
                raise e
            tables = [table.table_name for table in raw_tables if table.table_name in existing]
            if tables:
                self.client.raw.tables.delete(db_name=db_name, name=tables)
                count += len(tables)
        return count


@final
class TimeSeriesLoader(ResourceContainerLoader[str, TimeSeriesWrite, TimeSeries, TimeSeriesWriteList, TimeSeriesList]):
    item_name = "datapoints"
    api_name = "time_series"
    folder_name = "timeseries"
    resource_cls = TimeSeries
    resource_write_cls = TimeSeriesWrite
    list_cls = TimeSeriesList
    list_write_cls = TimeSeriesWriteList
    dependencies = frozenset({DataSetsLoader})

    @classmethod
    def get_required_capability(cls, ToolGlobals: CDFToolConfig) -> Capability:
        return TimeSeriesAcl(
            [TimeSeriesAcl.Action.Read, TimeSeriesAcl.Action.Write],
            TimeSeriesAcl.Scope.DataSet([ToolGlobals.data_set_id])
            if ToolGlobals.data_set_id
            else TimeSeriesAcl.Scope.All(),
        )

    @classmethod
    def get_id(cls, item: TimeSeries | TimeSeriesWrite) -> str:
        if item.external_id is None:
            raise ValueError("TimeSeries must have external_id set.")
        return item.external_id

    def load_resource(self, filepath: Path, ToolGlobals: CDFToolConfig, skip_validation: bool) -> TimeSeriesWriteList:
        resources = load_yaml_inject_variables(filepath, {})
        if not isinstance(resources, list):
            resources = [resources]
        for resource in resources:
            if resource.get("dataSetExternalId") is not None:
                ds_external_id = resource.pop("dataSetExternalId")
                resource["dataSetId"] = ToolGlobals.verify_dataset(ds_external_id, skip_validation)
            if resource.get("securityCategories") is None:
                # Bug in SDK, the read version sets security categories to an empty list.
                resource["securityCategories"] = []
        return TimeSeriesWriteList.load(resources)

    def retrieve(self, ids: SequenceNotStr[str]) -> TimeSeriesList:
        return self.client.time_series.retrieve_multiple(external_ids=cast(Sequence, ids), ignore_unknown_ids=True)

    def count(self, ids: SequenceNotStr[str]) -> int:
        datapoints = cast(
            DatapointsList,
            self.client.time_series.data.retrieve(
                external_id=cast(Sequence, ids),
                start=_MIN_TIMESTAMP_MS,
                end=_MAX_TIMESTAMP_MS + 1,
                aggregates="count",
                granularity="1000d",
            ),
        )
        return sum(sum(data.count or []) for data in datapoints)

    def drop_data(self, ids: SequenceNotStr[str]) -> int:
        existing = self.client.time_series.retrieve_multiple(
            external_ids=cast(Sequence, ids), ignore_unknown_ids=True
        ).as_external_ids()
        for external_id in existing:
            self.client.time_series.data.delete_range(
                external_id=external_id, start=_MIN_TIMESTAMP_MS, end=_MAX_TIMESTAMP_MS + 1
            )
        return len(ids)


@final
class TransformationLoader(
    ResourceLoader[str, TransformationWrite, Transformation, TransformationWriteList, TransformationList]
):
    api_name = "transformations"
    folder_name = "transformations"
    filename_pattern = (
        r"^(?:(?!\.schedule).)*$"  # Matches all yaml files except file names who's stem contain *.schedule.
    )
    resource_cls = Transformation
    resource_write_cls = TransformationWrite
    list_cls = TransformationList
    list_write_cls = TransformationWriteList
    dependencies = frozenset({DataSetsLoader, RawDatabaseLoader})

    @classmethod
    def get_required_capability(cls, ToolGlobals: CDFToolConfig) -> Capability:
        scope: capabilities.AllScope | capabilities.DataSetScope = (
            TransformationsAcl.Scope.DataSet([ToolGlobals.data_set_id])
            if ToolGlobals.data_set_id
            else TransformationsAcl.Scope.All()
        )
        return TransformationsAcl(
            [TransformationsAcl.Action.Read, TransformationsAcl.Action.Write],
            scope,
        )

    @classmethod
    def get_id(cls, item: Transformation | TransformationWrite) -> str:
        if item.external_id is None:
            raise ValueError("Transformation must have external_id set.")
        return item.external_id

    def _is_equal_custom(self, local: TransformationWrite, cdf_resource: Transformation) -> bool:
        local_dumped = local.dump()
        local_dumped.pop("destinationOidcCredentials", None)
        local_dumped.pop("sourceOidcCredentials", None)

        return local_dumped == cdf_resource.as_write().dump()

    def load_resource(self, filepath: Path, ToolGlobals: CDFToolConfig, skip_validation: bool) -> TransformationWrite:
        raw = load_yaml_inject_variables(filepath, ToolGlobals.environment_variables(), required_return_type="dict")
        # The `authentication` key is custom for this template:

        source_oidc_credentials = raw.get("authentication", {}).get("read") or raw.get("authentication") or None
        destination_oidc_credentials = raw.get("authentication", {}).get("write") or raw.get("authentication") or None
        if raw.get("dataSetExternalId") is not None:
            ds_external_id = raw.pop("dataSetExternalId")
            raw["dataSetId"] = ToolGlobals.verify_dataset(ds_external_id, skip_validation)
        if raw.get("conflictMode") is None:
            # Todo; Bug SDK missing default value
            raw["conflictMode"] = "upsert"

        transformation = TransformationWrite.load(raw)
        transformation.source_oidc_credentials = source_oidc_credentials and OidcCredentials.load(
            source_oidc_credentials
        )
        transformation.destination_oidc_credentials = destination_oidc_credentials and OidcCredentials.load(
            destination_oidc_credentials
        )
        # Find the non-integer prefixed filename
        file_name = filepath.stem.split(".", 2)[1]
        sql_file = filepath.parent / f"{file_name}.sql"
        if not sql_file.exists():
            sql_file = filepath.parent / f"{transformation.external_id}.sql"
            if not sql_file.exists():
                raise FileNotFoundError(
                    f"Could not find sql file belonging to transformation {filepath.name}. Please run build again."
                )
        transformation.query = sql_file.read_text()

        return transformation


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
    api_name = "transformations.schedules"
    folder_name = "transformations"
    filename_pattern = r"^.*\.schedule$"  # Matches all yaml files who's stem contain *.schedule.
    resource_cls = TransformationSchedule
    resource_write_cls = TransformationScheduleWrite
    list_cls = TransformationScheduleList
    list_write_cls = TransformationScheduleWriteList
    dependencies = frozenset({TransformationLoader})

    @classmethod
    def get_required_capability(cls, ToolGlobals: CDFToolConfig) -> Capability:
        scope: capabilities.AllScope | capabilities.DataSetScope = (
            TransformationsAcl.Scope.DataSet([ToolGlobals.data_set_id])
            if ToolGlobals.data_set_id
            else TransformationsAcl.Scope.All()
        )
        return TransformationsAcl(
            [TransformationsAcl.Action.Read, TransformationsAcl.Action.Write],
            scope,
        )

    @classmethod
    def get_id(cls, item: TransformationSchedule | TransformationScheduleWrite) -> str:
        if item.external_id is None:
            raise ValueError("TransformationSchedule must have external_id set.")
        return item.external_id

    def load_resource(
        self, filepath: Path, ToolGlobals: CDFToolConfig, skip_validation: bool
    ) -> TransformationScheduleWrite:
        raw = load_yaml_inject_variables(filepath, ToolGlobals.environment_variables(), required_return_type="dict")
        return TransformationScheduleWrite.load(raw)

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

    def delete(self, ids: SequenceNotStr[str]) -> int:
        try:
            self.client.transformations.schedules.delete(external_id=cast(Sequence, ids), ignore_unknown_ids=False)
            return len(ids)
        except CogniteNotFoundError as e:
            return len(ids) - len(e.not_found)


@final
class ExtractionPipelineLoader(
    ResourceLoader[
        str, ExtractionPipelineWrite, ExtractionPipeline, ExtractionPipelineWriteList, ExtractionPipelineList
    ]
):
    api_name = "extraction_pipelines"
    folder_name = "extraction_pipelines"
    filename_pattern = r"^(?:(?!\.config).)*$"  # Matches all yaml files except file names who's stem contain *.config.
    resource_cls = ExtractionPipeline
    resource_write_cls = ExtractionPipelineWrite
    list_cls = ExtractionPipelineList
    list_write_cls = ExtractionPipelineWriteList
    dependencies = frozenset({DataSetsLoader, RawDatabaseLoader})

    @classmethod
    def get_required_capability(cls, ToolGlobals: CDFToolConfig) -> Capability:
        return ExtractionPipelinesAcl(
            [ExtractionPipelinesAcl.Action.Read, ExtractionPipelinesAcl.Action.Write],
            ExtractionPipelinesAcl.Scope.All(),
        )

    @classmethod
    def get_id(cls, item: ExtractionPipeline | ExtractionPipelineWrite) -> str:
        if item.external_id is None:
            raise ValueError("ExtractionPipeline must have external_id set.")
        return item.external_id

    def load_resource(
        self, filepath: Path, ToolGlobals: CDFToolConfig, skip_validation: bool
    ) -> ExtractionPipelineWrite:
        resource = load_yaml_inject_variables(filepath, {}, required_return_type="dict")

        if resource.get("dataSetExternalId") is not None:
            ds_external_id = resource.pop("dataSetExternalId")
            resource["dataSetId"] = ToolGlobals.verify_dataset(ds_external_id, skip_validation)
        if resource.get("createdBy") is None:
            # Todo; Bug SDK missing default value (this will be set on the server-side if missing)
            resource["createdBy"] = "unknown"

        return ExtractionPipelineWrite.load(resource)

    def create(self, items: Sequence[ExtractionPipelineWrite]) -> ExtractionPipelineList:
        items = list(items)
        try:
            return self.client.extraction_pipelines.create(items)
        except CogniteDuplicatedError as e:
            if len(e.duplicated) < len(items):
                for dup in e.duplicated:
                    ext_id = dup.get("externalId", None)
                    for item in items:
                        if item.external_id == ext_id:
                            items.remove(item)

                return self.client.extraction_pipelines.create(items)
        return ExtractionPipelineList([])

    def delete(self, ids: SequenceNotStr[str]) -> int:
        id_list = list(ids)
        try:
            self.client.extraction_pipelines.delete(external_id=id_list)
        except CogniteNotFoundError as e:
            not_existing = {external_id for dup in e.not_found if (external_id := dup.get("externalId", None))}
            if id_list := [id_ for id_ in id_list if id_ not in not_existing]:
                self.client.extraction_pipelines.delete(external_id=id_list)
        return len(id_list)


@final
class ExtractionPipelineConfigLoader(
    ResourceLoader[
        str,
        ExtractionPipelineConfigWrite,
        ExtractionPipelineConfig,
        ExtractionPipelineConfigWriteList,
        ExtractionPipelineConfigList,
    ]
):
    api_name = "extraction_pipelines.config"
    folder_name = "extraction_pipelines"
    filename_pattern = r"^.*\.config$"
    resource_cls = ExtractionPipelineConfig
    resource_write_cls = ExtractionPipelineConfigWrite
    list_cls = ExtractionPipelineConfigList
    list_write_cls = ExtractionPipelineConfigWriteList
    dependencies = frozenset({ExtractionPipelineLoader})

    @classmethod
    def get_required_capability(cls, ToolGlobals: CDFToolConfig) -> Capability:
        return ExtractionPipelinesAcl(
            [ExtractionPipelinesAcl.Action.Read, ExtractionPipelinesAcl.Action.Write],
            ExtractionPipelinesAcl.Scope.All(),
        )

    @classmethod
    def get_id(cls, item: ExtractionPipelineConfig | ExtractionPipelineConfigWrite) -> str:
        if item.external_id is None:
            raise ValueError("ExtractionPipelineConfig must have external_id set.")
        return item.external_id

    def load_resource(
        self, filepath: Path, ToolGlobals: CDFToolConfig, skip_validation: bool
    ) -> ExtractionPipelineConfigWrite:
        resource = load_yaml_inject_variables(filepath, {}, required_return_type="dict")
        try:
            resource["config"] = yaml.dump(resource.get("config", ""), indent=4)
        except Exception:
            print(
                "[yellow]WARNING:[/] configuration could not be parsed as valid YAML, which is the recommended format.\n"
            )
            resource["config"] = resource.get("config", "")
        return ExtractionPipelineConfigWrite.load(resource)

    def create(self, items: Sequence[ExtractionPipelineConfigWrite]) -> ExtractionPipelineConfigList:
        return ExtractionPipelineConfigList([self.client.extraction_pipelines.config.create(items[0])])

    def delete(self, ids: SequenceNotStr[str]) -> int:
        count = 0
        for id_ in ids:
            result = self.client.extraction_pipelines.config.list(external_id=id_)
            count += len(result)
        return count


@final
class FileMetadataLoader(
    ResourceContainerLoader[str, FileMetadataWrite, FileMetadata, FileMetadataWriteList, FileMetadataList]
):
    item_name = "files"
    api_name = "files"
    folder_name = "files"
    resource_cls = FileMetadata
    resource_write_cls = FileMetadataWrite
    list_cls = FileMetadataList
    list_write_cls = FileMetadataWriteList
    dependencies = frozenset({DataSetsLoader})

    @property
    def display_name(self) -> str:
        return "file_metadata"

    @classmethod
    def get_required_capability(cls, ToolGlobals: CDFToolConfig) -> Capability:
        scope: capabilities.AllScope | capabilities.DataSetScope
        if ToolGlobals.data_set_id is None:
            scope = FilesAcl.Scope.All()
        else:
            scope = FilesAcl.Scope.DataSet([ToolGlobals.data_set_id])

        return FilesAcl([FilesAcl.Action.Read, FilesAcl.Action.Write], scope)

    @classmethod
    def get_id(cls, item: FileMetadata | FileMetadataWrite) -> str:
        if item.external_id is None:
            raise ValueError("FileMetadata must have external_id set.")
        return item.external_id

    def load_resource(
        self, filepath: Path, ToolGlobals: CDFToolConfig, skip_validation: bool
    ) -> FileMetadataWrite | FileMetadataWriteList:
        try:
            resource = load_yaml_inject_variables(
                filepath, ToolGlobals.environment_variables(), required_return_type="dict"
            )
            if resource.get("dataSetExternalId") is not None:
                ds_external_id = resource.pop("dataSetExternalId")
                resource["dataSetId"] = ToolGlobals.verify_dataset(ds_external_id, skip_validation)
            files_metadata = FileMetadataWriteList([FileMetadataWrite.load(resource)])
        except Exception:
            files_metadata = FileMetadataWriteList.load(
                load_yaml_inject_variables(filepath, ToolGlobals.environment_variables(), required_return_type="list")
            )

        # If we have a file with exact one file config, check to see if this is a pattern to expand
        if len(files_metadata) == 1 and ("$FILENAME" in (files_metadata[0].external_id or "")):
            # It is, so replace this file with all files in this folder using the same data
            print(
                f"  [bold yellow]Info:[/] File pattern detected in {filepath.name}, expanding to all files in folder."
            )
            file_data = files_metadata.data[0]
            ext_id_pattern = file_data.external_id
            files_metadata = FileMetadataWriteList([], cognite_client=self.client)
            for file in filepath.parent.glob("*"):
                if file.suffix in [".yaml", ".yml"]:
                    continue
                files_metadata.append(
                    FileMetadataWrite(
                        name=file.name,
                        external_id=re.sub(r"\$FILENAME", file.name, ext_id_pattern),
                        data_set_id=file_data.data_set_id,
                        source=file_data.source,
                        metadata=file_data.metadata,
                        directory=file_data.directory,
                        asset_ids=file_data.asset_ids,
                        labels=file_data.labels,
                        geo_location=file_data.geo_location,
                        security_categories=file_data.security_categories,
                    )
                )
        for meta in files_metadata:
            if meta.name is None:
                raise ValueError(f"File {meta.external_id} has no name.")
            if not Path(filepath.parent / meta.name).exists():
                raise FileNotFoundError(f"Could not find file {meta.name} referenced in filepath {filepath.name}")
            if isinstance(meta.data_set_id, str):
                # Replace external_id with internal id
                meta.data_set_id = ToolGlobals.verify_dataset(meta.data_set_id, skip_validation)
        return files_metadata

    def create(self, items: FileMetadataWriteList) -> FileMetadataList:
        created = FileMetadataList([])
        for meta in items:
            try:
                created.append(self.client.files.create(meta))
            except CogniteAPIError as e:
                if e.code == 409:
                    print(f"  [bold yellow]WARNING:[/] File {meta.external_id} already exists, skipping upload.")
        return created

    def delete(self, ids: SequenceNotStr[str]) -> int:
        self.client.files.delete(external_id=cast(Sequence, ids))
        return len(ids)

    def count(self, ids: SequenceNotStr[str]) -> int:
        return sum(1 for meta in self.client.files.retrieve_multiple(external_ids=list(ids)) if meta.uploaded)

    def drop_data(self, ids: SequenceNotStr[str]) -> int:
        existing = self.client.files.retrieve_multiple(external_ids=list(ids), ignore_unknown_ids=True)
        updates = [FileMetadataUpdate(external_id=meta.external_id).source.set(None) for meta in existing]
        updated = self.client.files.update(updates)
        return sum(1 for meta in updated if not meta.uploaded)


@final
class SpaceLoader(ResourceContainerLoader[str, SpaceApply, Space, SpaceApplyList, SpaceList]):
    item_name = "nodes and edges"
    api_name = "data_modeling.spaces"
    folder_name = "data_models"
    filename_pattern = r"^.*\.?(space)$"
    resource_cls = Space
    resource_write_cls = SpaceApply
    list_write_cls = SpaceApplyList
    list_cls = SpaceList
    _display_name = "spaces"

    @classmethod
    def get_required_capability(cls, ToolGlobals: CDFToolConfig) -> list[Capability]:
        return [
            DataModelsAcl(
                [DataModelsAcl.Action.Read, DataModelsAcl.Action.Write],
                DataModelsAcl.Scope.All(),
            ),
            # Needed to delete instances
            DataModelInstancesAcl(
                [DataModelInstancesAcl.Action.Read, DataModelInstancesAcl.Action.Write],
                DataModelInstancesAcl.Scope.All(),
            ),
        ]

    @classmethod
    def get_id(cls, item: SpaceApply | Space) -> str:
        return item.space

    def create(self, items: Sequence[SpaceApply]) -> SpaceList:
        return self.client.data_modeling.spaces.apply(items)

    def update(self, items: Sequence[SpaceApply]) -> SpaceList:
        return self.client.data_modeling.spaces.apply(items)

    def delete(self, ids: SequenceNotStr[str]) -> int:
        deleted = self.client.data_modeling.spaces.delete(ids)
        return len(deleted)

    def count(self, ids: SequenceNotStr[str]) -> int:
        # Bug in spec of aggregate requiring view_id to be passed in, so we cannot use it.
        # When this bug is fixed, it will be much faster to use aggregate.
        existing = self.client.data_modeling.spaces.retrieve(ids)

        return sum(len(batch) for batch in self._iterate_over_nodes(existing)) + sum(
            len(batch) for batch in self._iterate_over_edges(existing)
        )

    def drop_data(self, ids: SequenceNotStr[str]) -> int:
        existing = self.client.data_modeling.spaces.retrieve(ids)
        if not existing:
            return 0
        print(f"[bold]Deleting existing data in spaces {ids}...[/]")
        nr_of_deleted = 0
        for edge_ids in self._iterate_over_edges(existing):
            self.client.data_modeling.instances.delete(edges=edge_ids)
            nr_of_deleted += len(edge_ids)
        for node_ids in self._iterate_over_nodes(existing):
            self.client.data_modeling.instances.delete(nodes=node_ids)
            nr_of_deleted += len(node_ids)
        return nr_of_deleted

    def _iterate_over_nodes(self, spaces: SpaceList) -> Iterable[list[NodeId]]:
        is_space: filters.Filter
        if len(spaces) == 0:
            return
        elif len(spaces) == 1:
            is_space = filters.Equals(["node", "space"], spaces[0].as_id())
        else:
            is_space = filters.In(["node", "space"], spaces.as_ids())
        for instances in self.client.data_modeling.instances(
            chunk_size=1000, instance_type="node", filter=is_space, limit=-1
        ):
            yield instances.as_ids()

    def _iterate_over_edges(self, spaces: SpaceList) -> Iterable[list[EdgeId]]:
        is_space: filters.Filter
        if len(spaces) == 0:
            return
        elif len(spaces) == 1:
            is_space = filters.Equals(["edge", "space"], spaces[0].as_id())
        else:
            is_space = filters.In(["edge", "space"], spaces.as_ids())
        for instances in self.client.data_modeling.instances(
            chunk_size=1000, instance_type="edge", limit=-1, filter=is_space
        ):
            yield instances.as_ids()


class ContainerLoader(
    ResourceContainerLoader[ContainerId, ContainerApply, Container, ContainerApplyList, ContainerList]
):
    item_name = "nodes and edges"
    api_name = "data_modeling.containers"
    folder_name = "data_models"
    filename_pattern = r"^.*\.?(container)$"
    resource_cls = Container
    resource_write_cls = ContainerApply
    list_cls = ContainerList
    list_write_cls = ContainerApplyList
    dependencies = frozenset({SpaceLoader})

    _display_name = "containers"

    @classmethod
    def get_required_capability(cls, ToolGlobals: CDFToolConfig) -> Capability:
        # Todo Scoped to spaces
        return DataModelsAcl(
            [DataModelsAcl.Action.Read, DataModelsAcl.Action.Write],
            DataModelsAcl.Scope.All(),
        )

    @classmethod
    def get_id(cls, item: ContainerApply | Container) -> ContainerId:
        return item.as_id()

    def load_resource(
        self, filepath: Path, ToolGlobals: CDFToolConfig, skip_validation: bool
    ) -> ContainerApply | ContainerApplyList | None:
        loaded = super().load_resource(filepath, ToolGlobals, skip_validation)
        if loaded is None:
            return None
        items = loaded if isinstance(loaded, ContainerApplyList) else [loaded]
        if not skip_validation:
            ToolGlobals.verify_spaces(list({item.space for item in items}))
        for item in items:
            # Todo Bug in SDK, not setting defaults on load
            for prop_name in item.properties.keys():
                prop_dumped = item.properties[prop_name].dump()
                if prop_dumped.get("nullable") is None:
                    prop_dumped["nullable"] = False
                if prop_dumped.get("autoIncrement") is None:
                    prop_dumped["autoIncrement"] = False
                item.properties[prop_name] = ContainerProperty.load(prop_dumped)
        return loaded

    def create(self, items: Sequence[ContainerApply]) -> ContainerList:
        return self.client.data_modeling.containers.apply(items)

    def update(self, items: Sequence[ContainerApply]) -> ContainerList:
        return self.create(items)

    def delete(self, ids: SequenceNotStr[ContainerId]) -> int:
        deleted = self.client.data_modeling.containers.delete(cast(Sequence, ids))
        return len(deleted)

    def count(self, ids: SequenceNotStr[ContainerId]) -> int:
        # Bug in spec of aggregate requiring view_id to be passed in, so we cannot use it.
        # When this bug is fixed, it will be much faster to use aggregate.
        existing_containers = self.client.data_modeling.containers.retrieve(cast(Sequence, ids))
        return sum(len(batch) for batch in self._iterate_over_nodes(existing_containers)) + sum(
            len(batch) for batch in self._iterate_over_edges(existing_containers)
        )

    def drop_data(self, ids: SequenceNotStr[ContainerId]) -> int:
        nr_of_deleted = 0
        existing_containers = self.client.data_modeling.containers.retrieve(cast(Sequence, ids))
        for node_ids in self._iterate_over_nodes(existing_containers):
            self.client.data_modeling.instances.delete(nodes=node_ids)
            nr_of_deleted += len(node_ids)
        for edge_ids in self._iterate_over_edges(existing_containers):
            self.client.data_modeling.instances.delete(edges=edge_ids)
            nr_of_deleted += len(edge_ids)
        return nr_of_deleted

    def _iterate_over_nodes(self, containers: ContainerList) -> Iterable[list[NodeId]]:
        container_ids = [container.as_id() for container in containers if container.used_for in ["node", "all"]]
        if not container_ids:
            return
        is_container = filters.HasData(containers=container_ids)
        for instances in self.client.data_modeling.instances(
            chunk_size=1000, instance_type="node", filter=is_container, limit=-1
        ):
            yield instances.as_ids()

    def _iterate_over_edges(self, containers: ContainerList) -> Iterable[list[EdgeId]]:
        container_ids = [container.as_id() for container in containers if container.used_for in ["edge", "all"]]
        if not container_ids:
            return
        is_container = filters.HasData(containers=container_ids)
        for instances in self.client.data_modeling.instances(
            chunk_size=1000, instance_type="edge", limit=-1, filter=is_container
        ):
            yield instances.as_ids()


class ViewLoader(ResourceLoader[ViewId, ViewApply, View, ViewApplyList, ViewList]):
    api_name = "data_modeling.views"
    folder_name = "data_models"
    filename_pattern = r"^.*\.?(view)$"
    resource_cls = View
    resource_write_cls = ViewApply
    list_cls = ViewList
    list_write_cls = ViewApplyList
    dependencies = frozenset({SpaceLoader, ContainerLoader})

    _display_name = "views"

    @classmethod
    def get_required_capability(cls, ToolGlobals: CDFToolConfig) -> Capability:
        # Todo Scoped to spaces
        return DataModelsAcl(
            [DataModelsAcl.Action.Read, DataModelsAcl.Action.Write],
            DataModelsAcl.Scope.All(),
        )

    @classmethod
    def get_id(cls, item: ViewApply | View) -> ViewId:
        return item.as_id()

    def load_resource(
        self, filepath: Path, ToolGlobals: CDFToolConfig, skip_validation: bool
    ) -> ViewApply | ViewApplyList | None:
        loaded = super().load_resource(filepath, ToolGlobals, skip_validation)
        if not skip_validation:
            items = loaded if isinstance(loaded, ViewApplyList) else [loaded]
            ToolGlobals.verify_spaces(list({item.space for item in items}))
        return loaded

    def create(self, items: Sequence[ViewApply]) -> ViewList:
        return self.client.data_modeling.views.apply(items)

    def update(self, items: Sequence[ViewApply]) -> ViewList:
        return self.create(items)


@final
class DataModelLoader(ResourceLoader[DataModelId, DataModelApply, DataModel, DataModelApplyList, DataModelList]):
    api_name = "data_modeling.data_models"
    folder_name = "data_models"
    filename_pattern = r"^.*\.?(datamodel)$"
    resource_cls = DataModel
    resource_write_cls = DataModelApply
    list_cls = DataModelList
    list_write_cls = DataModelApplyList
    dependencies = frozenset({SpaceLoader, ViewLoader})
    _display_name = "data models"

    @classmethod
    def get_required_capability(cls, ToolGlobals: CDFToolConfig) -> Capability:
        # Todo Scoped to spaces
        return DataModelsAcl(
            [DataModelsAcl.Action.Read, DataModelsAcl.Action.Write],
            DataModelsAcl.Scope.All(),
        )

    @classmethod
    def get_id(cls, item: DataModelApply | DataModel) -> DataModelId:
        return item.as_id()

    def load_resource(
        self, filepath: Path, ToolGlobals: CDFToolConfig, skip_validation: bool
    ) -> DataModelApply | DataModelApplyList | None:
        loaded = super().load_resource(filepath, ToolGlobals, skip_validation)
        if not skip_validation:
            items = loaded if isinstance(loaded, DataModelApplyList) else [loaded]
            ToolGlobals.verify_spaces(list({item.space for item in items}))
        return loaded

    def create(self, items: DataModelApplyList) -> DataModelList:
        return self.client.data_modeling.data_models.apply(items)

    def update(self, items: DataModelApplyList) -> DataModelList:
        return self.create(items)


@final
class NodeLoader(ResourceContainerLoader[NodeId, NodeApply, Node, LoadableNodes, NodeList]):
    item_name = "nodes"
    api_name = "data_modeling.instances"
    folder_name = "data_models"
    filename_pattern = r"^.*\.?(node)$"
    resource_cls = Node
    resource_write_cls = NodeApply
    list_cls = NodeList
    list_write_cls = LoadableNodes
    dependencies = frozenset({SpaceLoader, ViewLoader, ContainerLoader})
    _display_name = "nodes"

    @classmethod
    def get_required_capability(cls, ToolGlobals: CDFToolConfig) -> Capability:
        # Todo Scoped to spaces
        return DataModelInstancesAcl(
            [DataModelInstancesAcl.Action.Read, DataModelInstancesAcl.Action.Write],
            DataModelInstancesAcl.Scope.All(),
        )

    @classmethod
    def get_id(cls, item: NodeApply | Node) -> NodeId:
        return item.as_id()

    @classmethod
    def create_empty_of(cls, items: LoadableNodes) -> LoadableNodes:
        return cls.list_write_cls.create_empty_from(items)

    def _is_equal_custom(self, local: NodeApply, cdf_resource: Node) -> bool:
        """Comparison for nodes to include properties in the comparison

        Note this is an expensive operation as we to an extra retrieve to fetch the properties.
        Thus, the cdf-tk should not be used to upload nodes that are data only nodes used for configuration.
        """
        # Note reading from a container is not supported.
        sources = [
            source_prop_pair.source
            for source_prop_pair in local.sources or []
            if isinstance(source_prop_pair.source, ViewId)
        ]
        cdf_resource_with_properties = self.client.data_modeling.instances.retrieve(
            nodes=cdf_resource.as_id(), sources=sources
        ).nodes[0]
        cdf_resource_dumped = cdf_resource_with_properties.as_write().dump()
        local_dumped = local.dump()
        if "existingVersion" not in local_dumped:
            # Existing version is typically not set when creating nodes, but we get it back
            # when we retrieve the node from the server.
            local_dumped["existingVersion"] = cdf_resource_dumped.get("existingVersion", None)

        return local_dumped == cdf_resource_dumped

    def load_resource(self, filepath: Path, ToolGlobals: CDFToolConfig, skip_validation: bool) -> LoadableNodes:
        raw = load_yaml_inject_variables(filepath, ToolGlobals.environment_variables())
        if isinstance(raw, dict):
            loaded = LoadableNodes._load(raw, cognite_client=self.client)
        else:
            raise ValueError(f"Unexpected node yaml file format {filepath.name}")
        if not skip_validation:
            ToolGlobals.verify_spaces(list({item.space for item in loaded}))
        return loaded

    def create(self, items: LoadableNodes) -> NodeApplyResultList:
        if not isinstance(items, LoadableNodes):
            raise ValueError("Unexpected node format file format")
        item = items
        result = self.client.data_modeling.instances.apply(
            nodes=item.nodes,
            auto_create_direct_relations=item.auto_create_direct_relations,
            skip_on_version_conflict=item.skip_on_version_conflict,
            replace=item.replace,
        )
        return result.nodes

    def retrieve(self, ids: SequenceNotStr[NodeId]) -> NodeList:
        return self.client.data_modeling.instances.retrieve(nodes=cast(Sequence, ids)).nodes

    def update(self, items: LoadableNodes) -> NodeApplyResultList:
        return self.create(items)

    def delete(self, ids: SequenceNotStr[NodeId]) -> int:
        deleted = self.client.data_modeling.instances.delete(nodes=cast(Sequence, ids))
        return len(deleted.nodes)

    def count(self, ids: SequenceNotStr[NodeId]) -> int:
        return len(ids)

    def drop_data(self, ids: SequenceNotStr[NodeId]) -> int:
        # Nodes will be deleted in .delete call.
        return 0


@final
class EdgeLoader(ResourceContainerLoader[EdgeId, EdgeApply, Edge, LoadableEdges, EdgeList]):
    item_name = "edges"
    api_name = "data_modeling.instances"
    folder_name = "data_models"
    filename_pattern = r"^.*\.?(edge)$"
    resource_cls = Edge
    resource_write_cls = EdgeApply
    list_cls = EdgeList
    list_write_cls = LoadableEdges
    _display_name = "edges"

    # Note edges do not need nodes to be created first, as they are created as part of the edge creation.
    # However, for deletion (reversed order) we need to delete edges before nodes.
    dependencies = frozenset({SpaceLoader, ViewLoader, NodeLoader})

    @classmethod
    def get_required_capability(cls, ToolGlobals: CDFToolConfig) -> Capability:
        # Todo Scoped to spaces
        return DataModelInstancesAcl(
            [DataModelInstancesAcl.Action.Read, DataModelInstancesAcl.Action.Write],
            DataModelInstancesAcl.Scope.All(),
        )

    @classmethod
    def get_id(cls, item: EdgeApply | Edge) -> EdgeId:
        return item.as_id()

    @classmethod
    def create_empty_of(cls, items: LoadableEdges) -> LoadableEdges:
        return cls.list_write_cls.create_empty_from(items)

    def load_resource(self, filepath: Path, ToolGlobals: CDFToolConfig, skip_validation: bool) -> LoadableEdges:
        raw = load_yaml_inject_variables(filepath, ToolGlobals.environment_variables())
        if isinstance(raw, dict):
            loaded = LoadableEdges._load(raw, cognite_client=self.client)
        else:
            raise ValueError(f"Unexpected edge yaml file format {filepath.name}")
        if not skip_validation:
            ToolGlobals.verify_spaces(list({item.space for item in loaded}))
        return loaded

    def create(self, items: LoadableEdges) -> EdgeApplyResultList:
        if not isinstance(items, LoadableEdges):
            raise ValueError("Unexpected edge format file format")
        item = items
        result = self.client.data_modeling.instances.apply(
            edges=item.edges,
            auto_create_start_nodes=item.auto_create_start_nodes,
            auto_create_end_nodes=item.auto_create_end_nodes,
            skip_on_version_conflict=item.skip_on_version_conflict,
            replace=item.replace,
        )
        return result.edges

    def retrieve(self, ids: SequenceNotStr[EdgeId]) -> EdgeList:
        return self.client.data_modeling.instances.retrieve(edges=cast(Sequence, ids)).edges

    def update(self, items: LoadableEdges) -> EdgeApplyResultList:
        return self.create(items)

    def delete(self, ids: SequenceNotStr[EdgeId]) -> int:
        deleted = self.client.data_modeling.instances.delete(edges=cast(Sequence, ids))
        return len(deleted.edges)

    def count(self, ids: SequenceNotStr[EdgeId]) -> int:
        return len(ids)

    def drop_data(self, ids: SequenceNotStr[EdgeId]) -> int:
        # Edges will be deleted in .delete call.
        return 0
