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

import re
import sys
from collections import defaultdict
from collections.abc import Hashable, Iterable, Sequence
from functools import lru_cache
from graphlib import CycleError, TopologicalSorter
from pathlib import Path
from time import sleep
from typing import Any, cast, final

import yaml
from cognite.client.data_classes import (
    filters,
)
from cognite.client.data_classes.capabilities import (
    Capability,
    DataModelInstancesAcl,
    DataModelsAcl,
)
from cognite.client.data_classes.data_modeling import (
    Container,
    ContainerApply,
    ContainerApplyList,
    ContainerList,
    DataModel,
    DataModelApply,
    DataModelApplyList,
    DataModelList,
    Edge,
    EdgeApply,
    EdgeApplyList,
    EdgeApplyResultList,
    EdgeList,
    Node,
    NodeApply,
    NodeApplyList,
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
from cognite.client.data_classes.data_modeling.graphql import DMLApplyResult
from cognite.client.data_classes.data_modeling.ids import (
    ContainerId,
    DataModelId,
    EdgeId,
    NodeId,
    ViewId,
)
from cognite.client.exceptions import CogniteAPIError
from cognite.client.utils.useful_types import SequenceNotStr
from rich import print

from cognite_toolkit._cdf_tk._parameters import ANY_INT, ANY_STR, ANYTHING, ParameterSpec, ParameterSpecSet
from cognite_toolkit._cdf_tk.client import ToolkitClient
from cognite_toolkit._cdf_tk.client.data_classes.graphql_data_models import (
    GraphQLDataModel,
    GraphQLDataModelList,
    GraphQLDataModelWrite,
    GraphQLDataModelWriteList,
)
from cognite_toolkit._cdf_tk.constants import HAS_DATA_FILTER_LIMIT
from cognite_toolkit._cdf_tk.exceptions import GraphQLParseError, ToolkitCycleError, ToolkitFileNotFoundError
from cognite_toolkit._cdf_tk.loaders._base_loaders import (
    ResourceContainerLoader,
    ResourceLoader,
)
from cognite_toolkit._cdf_tk.tk_warnings import LowSeverityWarning
from cognite_toolkit._cdf_tk.utils import (
    GraphQLParser,
    calculate_str_or_file_hash,
    in_dict,
    load_yaml_inject_variables,
    quote_int_value_by_key_in_yaml,
    retrieve_view_ancestors,
    safe_read,
)

from .auth_loaders import GroupAllScopedLoader


@final
class SpaceLoader(ResourceContainerLoader[str, SpaceApply, Space, SpaceApplyList, SpaceList]):
    item_name = "nodes and edges"
    folder_name = "data_models"
    filename_pattern = r"^.*space$"
    resource_cls = Space
    resource_write_cls = SpaceApply
    list_write_cls = SpaceApplyList
    list_cls = SpaceList
    kind = "Space"
    dependencies = frozenset({GroupAllScopedLoader})
    _doc_url = "Spaces/operation/ApplySpaces"

    @property
    def display_name(self) -> str:
        return "spaces"

    @classmethod
    def get_required_capability(
        cls, items: Sequence[SpaceApply] | None, read_only: bool
    ) -> list[Capability] | list[Capability]:
        if not items and items is not None:
            return []

        actions = [DataModelsAcl.Action.Read] if read_only else [DataModelsAcl.Action.Read, DataModelsAcl.Action.Write]

        return [DataModelsAcl(actions, DataModelsAcl.Scope.All())]

    @classmethod
    def get_id(cls, item: SpaceApply | Space | dict) -> str:
        if isinstance(item, dict):
            return item["space"]
        return item.space

    @classmethod
    def dump_id(cls, id: str) -> dict[str, Any]:
        return {"space": id}

    def create(self, items: Sequence[SpaceApply]) -> SpaceList:
        return self.client.data_modeling.spaces.apply(items)

    def retrieve(self, ids: SequenceNotStr[str]) -> SpaceList:
        return self.client.data_modeling.spaces.retrieve(ids)

    def update(self, items: Sequence[SpaceApply]) -> SpaceList:
        return self.client.data_modeling.spaces.apply(items)

    def delete(self, ids: SequenceNotStr[str]) -> int:
        existing = self.client.data_modeling.spaces.retrieve(ids)
        is_global = {space.space for space in existing if space.is_global}
        if is_global:
            print(
                f"  [bold yellow]WARNING:[/] Spaces {list(is_global)} are global and cannot be deleted, skipping delete, for these."
            )
        to_delete = [space for space in ids if space not in is_global]
        deleted = self.client.data_modeling.spaces.delete(to_delete)
        return len(deleted)

    def _iterate(
        self,
        data_set_external_id: str | None = None,
        space: str | None = None,
        parent_ids: list[Hashable] | None = None,
    ) -> Iterable[Space]:
        if space:
            return self.client.data_modeling.spaces.retrieve([space])
        else:
            return iter(self.client.data_modeling.spaces)

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
    folder_name = "data_models"
    filename_pattern = r"^.*container$"
    resource_cls = Container
    resource_write_cls = ContainerApply
    list_cls = ContainerList
    list_write_cls = ContainerApplyList
    kind = "Container"
    dependencies = frozenset({SpaceLoader})
    _doc_url = "Containers/operation/ApplyContainers"

    @property
    def display_name(self) -> str:
        return "containers"

    @classmethod
    def get_required_capability(
        cls, items: Sequence[ContainerApply] | None, read_only: bool
    ) -> Capability | list[Capability]:
        if not items and items is not None:
            return []

        actions = [DataModelsAcl.Action.Read] if read_only else [DataModelsAcl.Action.Read, DataModelsAcl.Action.Write]

        scope = (
            DataModelsAcl.Scope.SpaceID(list({item.space for item in items}))
            if items is not None
            else DataModelsAcl.Scope.All()
        )

        return DataModelsAcl(actions, scope)  # type: ignore[arg-type]

    @classmethod
    def get_id(cls, item: ContainerApply | Container | dict) -> ContainerId:
        if isinstance(item, dict):
            if missing := tuple(k for k in {"space", "externalId"} if k not in item):
                # We need to raise a KeyError with all missing keys to get the correct error message.
                raise KeyError(*missing)
            return ContainerId(space=item["space"], external_id=item["externalId"])
        return item.as_id()

    @classmethod
    def dump_id(cls, id: ContainerId) -> dict[str, Any]:
        return id.dump(include_type=False)

    @classmethod
    def get_dependent_items(cls, item: dict) -> Iterable[tuple[type[ResourceLoader], Hashable]]:
        if "space" in item:
            yield SpaceLoader, item["space"]
        # Note that we are very careful in the code below to not raise an exception if the
        # item is not properly formed. If that is the case, an appropriate warning will be given elsewhere.
        for prop in item.get("properties", {}).values():
            if not isinstance(prop, dict):
                continue
            prop_type = prop.get("type", {})
            if isinstance(prop_type, dict) and prop_type.get("type") == "direct":
                if isinstance(prop_type.get("container"), dict):
                    container = prop_type["container"]
                    if "space" in container and "externalId" in container and container.get("type") == "container":
                        yield (
                            ContainerLoader,
                            ContainerId(space=container["space"], external_id=container["externalId"]),
                        )

    def load_resource(self, resource: dict[str, Any], is_dry_run: bool = False) -> ContainerApply:
        for prop in resource.get("properties", {}).values():
            type_ = prop.get("type", {})
            if "list" not in type_:
                # In the Python-SDK, list property of a container.properties.<property>.type.list is required.
                # This is not the case in the API, so we need to set it here. (This is due to the PropertyType class
                # is used as read and write in the SDK, and the read class has it required while the write class does not)
                type_["list"] = False
            # Todo Bug in SDK, not setting defaults on load
            if "nullable" not in prop:
                prop["nullable"] = False
            if "autoIncrement" not in prop:
                prop["autoIncrement"] = False

        return ContainerApply._load(resource)

    def dump_resource(self, resource: Container, local: dict[str, Any]) -> dict[str, Any]:
        dumped = resource.as_write().dump()
        for key in ["constraints", "indexes"]:
            if not dumped.get(key) and key not in local:
                # Set to empty dict by server.
                dumped.pop(key, None)
        return dumped

    def create(self, items: Sequence[ContainerApply]) -> ContainerList:
        return self.client.data_modeling.containers.apply(items)

    def retrieve(self, ids: SequenceNotStr[ContainerId]) -> ContainerList:
        return self.client.data_modeling.containers.retrieve(cast(Sequence, ids))

    def update(self, items: Sequence[ContainerApply]) -> ContainerList:
        return self.create(items)

    def delete(self, ids: SequenceNotStr[ContainerId]) -> int:
        deleted = self.client.data_modeling.containers.delete(cast(Sequence, ids))
        return len(deleted)

    def _iterate(
        self,
        data_set_external_id: str | None = None,
        space: str | None = None,
        parent_ids: list[Hashable] | None = None,
    ) -> Iterable[Container]:
        return iter(self.client.data_modeling.containers(space=space))

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
        for container_id_chunk in self._chunker(container_ids, HAS_DATA_FILTER_LIMIT):
            is_container = filters.HasData(containers=container_id_chunk)
            for instances in self.client.data_modeling.instances(
                chunk_size=1000, instance_type="node", filter=is_container, limit=-1
            ):
                yield instances.as_ids()

    def _iterate_over_edges(self, containers: ContainerList) -> Iterable[list[EdgeId]]:
        container_ids = [container.as_id() for container in containers if container.used_for in ["edge", "all"]]
        if not container_ids:
            return

        for container_id_chunk in self._chunker(container_ids, HAS_DATA_FILTER_LIMIT):
            is_container = filters.HasData(containers=container_id_chunk)
            for instances in self.client.data_modeling.instances(
                chunk_size=1000, instance_type="edge", limit=-1, filter=is_container
            ):
                yield instances.as_ids()

    @staticmethod
    def _chunker(seq: Sequence, size: int) -> Iterable[Sequence]:
        return (seq[pos : pos + size] for pos in range(0, len(seq), size))

    @classmethod
    @lru_cache(maxsize=1)
    def get_write_cls_parameter_spec(cls) -> ParameterSpecSet:
        output = super().get_write_cls_parameter_spec()
        # In the SDK this is called isList, while in the API it is called list.
        output.discard(
            ParameterSpec(
                ("properties", ANY_STR, "type", "isList"), frozenset({"bool"}), is_required=True, _is_nullable=False
            )
        )
        output.add(
            ParameterSpec(
                ("properties", ANY_STR, "type", "list"), frozenset({"bool"}), is_required=True, _is_nullable=False
            )
        )
        # The parameters below are used by the SDK to load the correct class, and ase thus not part of the init
        # that the spec is created from, so we need to add them manually.
        output.update(
            ParameterSpecSet(
                {
                    ParameterSpec(
                        ("properties", ANY_STR, "type", "type"),
                        frozenset({"str"}),
                        is_required=True,
                        _is_nullable=False,
                    ),
                    ParameterSpec(
                        # direct relations with constraint
                        ("properties", ANY_STR, "type", "container", "type"),
                        frozenset({"str"}),
                        is_required=True,
                        _is_nullable=False,
                    ),
                    ParameterSpec(
                        ("constraints", ANY_STR, "constraintType"),
                        frozenset({"str"}),
                        is_required=True,
                        _is_nullable=False,
                    ),
                    ParameterSpec(
                        ("constraints", ANY_STR, "require", "type"),
                        frozenset({"str"}),
                        is_required=True,
                        _is_nullable=False,
                    ),
                    ParameterSpec(
                        ("indexes", ANY_STR, "indexType"), frozenset({"str"}), is_required=True, _is_nullable=False
                    ),
                }
            )
        )
        return output


class ViewLoader(ResourceLoader[ViewId, ViewApply, View, ViewApplyList, ViewList]):
    folder_name = "data_models"
    filename_pattern = r"^.*view$"
    resource_cls = View
    resource_write_cls = ViewApply
    list_cls = ViewList
    list_write_cls = ViewApplyList
    kind = "View"
    dependencies = frozenset({SpaceLoader, ContainerLoader})
    _doc_url = "Views/operation/ApplyViews"

    def __init__(self, client: ToolkitClient, build_dir: Path) -> None:
        super().__init__(client, build_dir)
        # Caching to avoid multiple lookups on the same interfaces.
        self._interfaces_by_id: dict[ViewId, View] = {}

    @property
    def display_name(self) -> str:
        return "views"

    @classmethod
    def get_required_capability(
        cls, items: Sequence[ViewApply] | None, read_only: bool
    ) -> Capability | list[Capability]:
        if not items and items is not None:
            return []

        actions = [DataModelsAcl.Action.Read] if read_only else [DataModelsAcl.Action.Read, DataModelsAcl.Action.Write]

        scope = (
            DataModelsAcl.Scope.SpaceID(list({item.space for item in items}))
            if items is not None
            else DataModelsAcl.Scope.All()
        )

        return DataModelsAcl(actions, scope)  # type: ignore[arg-type]

    @classmethod
    def get_id(cls, item: ViewApply | View | dict) -> ViewId:
        if isinstance(item, dict):
            if missing := tuple(k for k in {"space", "externalId", "version"} if k not in item):
                # We need to raise a KeyError with all missing keys to get the correct error message.
                raise KeyError(*missing)
            return ViewId(space=item["space"], external_id=item["externalId"], version=str(item["version"]))

        return ViewId(item.space, item.external_id, str(item.version))

    @classmethod
    def dump_id(cls, id: ViewId) -> dict[str, Any]:
        return id.dump(include_type=False)

    @classmethod
    def get_dependent_items(cls, item: dict) -> Iterable[tuple[type[ResourceLoader], Hashable]]:
        if "space" in item:
            yield SpaceLoader, item["space"]
        if isinstance(implements := item.get("implements", []), list):
            for parent in implements:
                if not isinstance(parent, dict):
                    continue
                if parent.get("type") == "view" and in_dict(["space", "externalId", "version"], parent):
                    yield (
                        ViewLoader,
                        ViewId(parent["space"], parent["externalId"], str(v) if (v := parent.get("version")) else None),
                    )
        for prop in item.get("properties", {}).values():
            if (container := prop.get("container", {})) and container.get("type") == "container":
                if in_dict(("space", "externalId"), container):
                    yield ContainerLoader, ContainerId(container["space"], container["externalId"])
            for key, dct_ in [("source", prop), ("edgeSource", prop), ("source", prop.get("through", {}))]:
                if source := dct_.get(key, {}):
                    if source.get("type") == "view" and in_dict(("space", "externalId", "version"), source):
                        yield (
                            ViewLoader,
                            ViewId(
                                source["space"], source["externalId"], str(v) if (v := source.get("version")) else None
                            ),
                        )
                    elif source.get("type") == "container" and in_dict(("space", "externalId"), source):
                        yield ContainerLoader, ContainerId(source["space"], source["externalId"])

    def dump_as_write(self, cdf_resource: View) -> dict[str, Any]:
        """Views are special in that they include all parent properties. This
        methods looks up all parent views and removes the properties that are
        not overridden to get the true write view."""
        cdf_dumped = cdf_resource.as_write().dump()
        if not cdf_resource.implements:
            return cdf_dumped
        if cdf_resource.properties:
            # All read version of views have all the properties of their parent views.
            # We need to remove these properties to compare with the local view.
            # Unless the local view has overridden the properties.
            parents = retrieve_view_ancestors(self.client, cdf_resource.implements or [], self._interfaces_by_id)
            cdf_properties = cdf_dumped.get("properties", {})
            for parent in parents:
                for prop_name, parent_prop in (parent.as_write().properties or {}).items():
                    is_overidden = prop_name in cdf_properties and cdf_properties[prop_name] != parent_prop.dump()
                    if is_overidden:
                        continue
                    cdf_properties.pop(prop_name, None)
        return cdf_dumped

    def load_resource_file(
        self, filepath: Path, environment_variables: dict[str, str | None] | None = None
    ) -> list[dict[str, Any]]:
        # The version is a string, but the user often writes it as an int.
        # YAML will then parse it as an int, for example, `3_0_2` will be parsed as `302`.
        # This is technically a user mistake, as you should quote the version in the YAML file.
        # However, we do not want to put this burden on the user (knowing the intricate workings of YAML),
        # so we fix it here.
        raw_str = quote_int_value_by_key_in_yaml(safe_read(filepath), key="version")
        raw_yaml = load_yaml_inject_variables(
            raw_str, environment_variables or {} if self.do_environment_variable_injection else {}
        )
        return raw_yaml if isinstance(raw_yaml, list) else [raw_yaml]

    def dump_resource(self, resource: View, local: dict[str, Any]) -> dict[str, Any]:
        dumped = self.dump_as_write(resource)
        if not dumped.get("properties") and not local.get("properties"):
            # All properties were removed, so we remove the properties key.
            dumped.pop("properties", None)
        if not dumped.get("implements") and not local.get("implements"):
            dumped.pop("implements", None)
        return dumped

    def create(self, items: Sequence[ViewApply]) -> ViewList:
        return self.client.data_modeling.views.apply(items)

    def retrieve(self, ids: SequenceNotStr[ViewId]) -> ViewList:
        return self.client.data_modeling.views.retrieve(cast(Sequence, ids))

    def update(self, items: Sequence[ViewApply]) -> ViewList:
        return self.create(items)

    def delete(self, ids: SequenceNotStr[ViewId]) -> int:
        to_delete = list(ids)
        nr_of_deleted = 0
        attempt_count = 5
        for attempt_no in range(attempt_count):
            deleted = self.client.data_modeling.views.delete(to_delete)
            nr_of_deleted += len(deleted)
            existing = self.client.data_modeling.views.retrieve(to_delete).as_ids()
            if not existing:
                return nr_of_deleted
            sleep(2)
            to_delete = existing
        else:
            print(f"  [bold yellow]WARNING:[/] Could not delete views {to_delete} after {attempt_count} attempts.")
        return nr_of_deleted

    def _iterate(
        self,
        data_set_external_id: str | None = None,
        space: str | None = None,
        parent_ids: list[Hashable] | None = None,
    ) -> Iterable[View]:
        return iter(self.client.data_modeling.views(space=space))

    @classmethod
    @lru_cache(maxsize=1)
    def get_write_cls_parameter_spec(cls) -> ParameterSpecSet:
        spec = super().get_write_cls_parameter_spec()
        # The Filter class in the SDK class View implementation is deviating from the API.
        # So we need to modify the spec to match the API.
        parameter_path = ("filter",)
        length = len(parameter_path)
        for item in spec:
            if len(item.path) >= length + 1 and item.path[:length] == parameter_path[:length]:
                # Add extra ANY_STR layer
                # The spec class is immutable, so we use this trick to modify it.
                is_has_data_filter = item.path[1] in ["containers", "views"]
                if is_has_data_filter:
                    # Special handling of the HasData filter that deviates in SDK implementation from API Spec.
                    object.__setattr__(item, "path", item.path[:length] + (ANY_STR,) + item.path[length + 1 :])
                else:
                    object.__setattr__(item, "path", item.path[:length] + (ANY_STR,) + item.path[length:])

        spec.add(ParameterSpec(("filter", ANY_STR), frozenset({"dict"}), is_required=False, _is_nullable=False))
        # The following types are used by the SDK to load the correct class. They are not part of the init,
        # so we need to add it manually.
        spec.update(
            ParameterSpecSet(
                {
                    ParameterSpec(
                        ("implements", ANY_INT, "type"), frozenset({"str"}), is_required=True, _is_nullable=False
                    ),
                    ParameterSpec(
                        ("properties", ANY_STR, "connectionType"),
                        frozenset({"str"}),
                        is_required=True,
                        _is_nullable=False,
                    ),
                    ParameterSpec(
                        ("properties", ANY_STR, "source", "type"),
                        frozenset({"str"}),
                        is_required=True,
                        _is_nullable=False,
                    ),
                    ParameterSpec(
                        ("properties", ANY_STR, "container", "type"),
                        frozenset({"str"}),
                        is_required=True,
                        _is_nullable=False,
                    ),
                    ParameterSpec(
                        ("properties", ANY_STR, "edgeSource", "type"),
                        frozenset({"str"}),
                        is_required=True,
                        _is_nullable=False,
                    ),
                    ParameterSpec(
                        ("properties", ANY_STR, "through", "source", "type"),
                        frozenset({"str"}),
                        is_required=True,
                        _is_nullable=False,
                    ),
                    ParameterSpec(
                        # In the SDK, this is called "property"
                        ("properties", ANY_STR, "through", "identifier"),
                        frozenset({"str"}),
                        is_required=True,
                        _is_nullable=False,
                    ),
                    # Filters are complex, so we do not attempt to give any more specific spec.
                    ParameterSpec(
                        ("filter", ANYTHING),
                        frozenset({"str"}),
                        is_required=True,
                        _is_nullable=False,
                    ),
                }
            )
        )
        spec.discard(
            ParameterSpec(
                # The API spec calls this "identifier", while the SDK calls it "property".
                ("properties", ANY_STR, "through", "property"),
                frozenset({"str"}),
                is_required=True,
                _is_nullable=False,
            )
        )
        return spec


@final
class DataModelLoader(ResourceLoader[DataModelId, DataModelApply, DataModel, DataModelApplyList, DataModelList]):
    folder_name = "data_models"
    filename_pattern = r"^.*datamodel$"
    resource_cls = DataModel
    resource_write_cls = DataModelApply
    list_cls = DataModelList
    list_write_cls = DataModelApplyList
    kind = "DataModel"
    dependencies = frozenset({SpaceLoader, ViewLoader})
    _doc_url = "Data-models/operation/createDataModels"

    @property
    def display_name(self) -> str:
        return "data models"

    @classmethod
    def get_required_capability(
        cls, items: Sequence[DataModelApply] | None, read_only: bool
    ) -> Capability | list[Capability]:
        if not items and items is not None:
            return []

        actions = [DataModelsAcl.Action.Read] if read_only else [DataModelsAcl.Action.Read, DataModelsAcl.Action.Write]

        scope = (
            DataModelsAcl.Scope.SpaceID(list({item.space for item in items}))
            if items is not None
            else DataModelsAcl.Scope.All()
        )

        return DataModelsAcl(actions, scope)  # type: ignore[arg-type]

    @classmethod
    def get_id(cls, item: DataModelApply | DataModel | dict) -> DataModelId:
        if isinstance(item, dict):
            if missing := tuple(k for k in {"space", "externalId", "version"} if k not in item):
                # We need to raise a KeyError with all missing keys to get the correct error message.
                raise KeyError(*missing)
            return DataModelId(space=item["space"], external_id=item["externalId"], version=str(item["version"]))
        return DataModelId(item.space, item.external_id, str(item.version))

    @classmethod
    def dump_id(cls, id: DataModelId) -> dict[str, Any]:
        return id.dump(include_type=False)

    @classmethod
    def get_dependent_items(cls, item: dict) -> Iterable[tuple[type[ResourceLoader], Hashable]]:
        if "space" in item:
            yield SpaceLoader, item["space"]
        for view in item.get("views", []):
            if in_dict(("space", "externalId"), view):
                yield (
                    ViewLoader,
                    ViewId(view["space"], view["externalId"], str(v) if (v := view.get("version")) else None),
                )

    def load_resource_file(
        self, filepath: Path, environment_variables: dict[str, str | None] | None = None
    ) -> list[dict[str, Any]]:
        # The version is a string, but the user often writes it as an int.
        # YAML will then parse it as an int, for example, `3_0_2` will be parsed as `302`.
        # This is technically a user mistake, as you should quote the version in the YAML file.
        # However, we do not want to put this burden on the user (knowing the intricate workings of YAML),
        # so we fix it here.
        raw_str = quote_int_value_by_key_in_yaml(safe_read(filepath), key="version")
        raw_yaml = load_yaml_inject_variables(
            raw_str, environment_variables or {} if self.do_environment_variable_injection else {}
        )
        return raw_yaml if isinstance(raw_yaml, list) else [raw_yaml]

    def dump_resource(self, resource: DataModel, local: dict[str, Any]) -> dict[str, Any]:
        dumped = resource.as_write().dump()
        if "views" not in dumped:
            return dumped
        # Sorting in the same order as the local file.
        view_order_by_id = {ViewId.load(v): no for no, v in enumerate(local.get("views", []))}
        end_of_list = len(view_order_by_id)
        dumped["views"] = sorted(dumped["views"], key=lambda v: view_order_by_id.get(ViewId.load(v), end_of_list))
        return dumped

    def create(self, items: DataModelApplyList) -> DataModelList:
        return self.client.data_modeling.data_models.apply(items)

    def retrieve(self, ids: SequenceNotStr[DataModelId]) -> DataModelList:
        return self.client.data_modeling.data_models.retrieve(cast(Sequence, ids))

    def update(self, items: DataModelApplyList) -> DataModelList:
        updated = self.create(items)
        # There is a bug in the API not raising an exception if view is removed from a data model.
        # So we check here that the update was fixed.
        updated_by_id = {item.as_id(): item for item in updated}
        for local in items:
            item_id = local.as_id()
            if item_id in updated_by_id:
                views_updated = {v.as_id() if isinstance(v, View) else v for v in updated_by_id[item_id].views or []}
                views_local = set(v.as_id() if isinstance(v, ViewApply) else v for v in local.views or [])
                missing = views_local - views_updated
                extra = views_updated - views_local
                if missing or extra:
                    raise CogniteAPIError(
                        f"The API did not update the data model, {item_id} correctly. You might have "
                        f"to increase the version number of the data model for it to update.\nMissing views in CDF: {missing}\n"
                        f"Extra views in the CDF: {extra}",
                        code=500,
                    )
            else:
                raise CogniteAPIError(
                    f"The data model {item_id} was not updated. Please check the data model manually.",
                    code=500,
                )

        return updated

    def delete(self, ids: SequenceNotStr[DataModelId]) -> int:
        return len(self.client.data_modeling.data_models.delete(cast(Sequence, ids)))

    def _iterate(
        self,
        data_set_external_id: str | None = None,
        space: str | None = None,
        parent_ids: list[Hashable] | None = None,
    ) -> Iterable[DataModel]:
        return iter(self.client.data_modeling.data_models(space=space, include_global=False))

    @classmethod
    @lru_cache(maxsize=1)
    def get_write_cls_parameter_spec(cls) -> ParameterSpecSet:
        spec = super().get_write_cls_parameter_spec()
        # ViewIds have the type set in the API Spec, but this is hidden in the SDK classes,
        # so we need to add it manually.
        spec.add(ParameterSpec(("views", ANY_INT, "type"), frozenset({"str"}), is_required=True, _is_nullable=False))
        return spec


@final
class NodeLoader(ResourceContainerLoader[NodeId, NodeApply, Node, NodeApplyList, NodeList]):
    item_name = "nodes"
    folder_name = "data_models"
    filename_pattern = r"^.*node$"
    resource_cls = Node
    resource_write_cls = NodeApply
    list_cls = NodeList
    list_write_cls = NodeApplyList
    kind = "Node"
    dependencies = frozenset({SpaceLoader, ViewLoader, ContainerLoader})
    _doc_url = "Instances/operation/applyNodeAndEdges"

    @property
    def display_name(self) -> str:
        return "nodes"

    @classmethod
    def get_required_capability(
        cls, items: Sequence[NodeApply] | None, read_only: bool
    ) -> Capability | list[Capability]:
        if not items and items is not None:
            return []

        actions = (
            [DataModelInstancesAcl.Action.Read]
            if read_only
            else [DataModelInstancesAcl.Action.Read, DataModelInstancesAcl.Action.Write]
        )

        return DataModelInstancesAcl(
            actions,
            DataModelInstancesAcl.Scope.SpaceID(list({item.space for item in items}))
            if items is not None
            else DataModelInstancesAcl.Scope.All(),
        )

    @classmethod
    def get_id(cls, item: NodeApply | Node | dict) -> NodeId:
        if isinstance(item, dict):
            if missing := tuple(k for k in {"space", "externalId"} if k not in item):
                # We need to raise a KeyError with all missing keys to get the correct error message.
                raise KeyError(*missing)
            return NodeId(space=item["space"], external_id=item["externalId"])
        return item.as_id()

    @classmethod
    def dump_id(cls, id: NodeId) -> dict[str, Any]:
        return id.dump()

    @classmethod
    def get_dependent_items(cls, item: dict) -> Iterable[tuple[type[ResourceLoader], Hashable]]:
        if "space" in item:
            yield SpaceLoader, item["space"]
        for source in item.get("sources", []):
            if (identifier := source.get("source")) and isinstance(identifier, dict):
                if identifier.get("type") == "view" and in_dict(("space", "externalId", "version"), identifier):
                    yield (
                        ViewLoader,
                        ViewId(
                            identifier["space"],
                            identifier["externalId"],
                            str(v) if (v := identifier.get("version")) else None,
                        ),
                    )
                elif identifier.get("type") == "container" and in_dict(("space", "externalId"), identifier):
                    yield ContainerLoader, ContainerId(identifier["space"], identifier["externalId"])

    def dump_resource(self, resource: Node, local: dict[str, Any]) -> dict[str, Any]:
        # CDF resource does not have properties set, so we need to do a lookup
        sources = [ViewId.load(source["source"]) for source in local.get("sources", []) if "source" in source]
        try:
            cdf_resource_with_properties = self.client.data_modeling.instances.retrieve(
                nodes=resource.as_id(), sources=sources
            ).nodes[0]
        except CogniteAPIError:
            # View does not exist
            dumped = resource.as_write().dump()
        else:
            dumped = cdf_resource_with_properties.as_write().dump()

        if "existingVersion" not in local:
            # Existing version is typically not set when creating nodes, but we get it back
            # when we retrieve the node from the server.
            dumped.pop("existingVersion", None)

        if "instanceType" in dumped and "instanceType" not in local:
            # Toolkit uses file suffix to determine instanceType, so we need to remove it from the CDF resource
            # to match the local resource.
            dumped.pop("instanceType")

        return dumped

    def dump_resource_legacy(
        self, resource: NodeApply, source_file: Path, local_resource: NodeApply
    ) -> tuple[dict[str, Any], dict[Path, str]]:
        resource_node = resource
        local_node = local_resource
        # Retrieve node again to get properties.
        view_ids = {source.source for source in local_node.sources or [] if isinstance(source.source, ViewId)}
        nodes = self.client.data_modeling.instances.retrieve(nodes=local_node.as_id(), sources=list(view_ids)).nodes
        if not nodes:
            print(
                f"  [bold yellow]WARNING:[/] Node {local_resource.as_id()} does not exist. Failed to fetch properties."
            )
            return resource_node.dump(), {}
        node = nodes[0]
        node_dumped = node.as_write().dump()
        node_dumped.pop("existingVersion", None)

        # Node files have configuration in the first 3 lines, we need to include this in the dumped file.
        dumped = yaml.safe_load("\n".join(safe_read(source_file).splitlines()[:3]))

        dumped["nodes"] = [node_dumped]

        return dumped, {}

    def create(self, items: NodeApplyList) -> NodeApplyResultList:
        result = self.client.data_modeling.instances.apply(
            nodes=items, auto_create_direct_relations=True, replace=False
        )
        return result.nodes

    def retrieve(self, ids: SequenceNotStr[NodeId]) -> NodeList:
        return self.client.data_modeling.instances.retrieve(nodes=cast(Sequence, ids)).nodes

    def update(self, items: NodeApplyList) -> NodeApplyResultList:
        result = self.client.data_modeling.instances.apply(
            nodes=items, auto_create_direct_relations=False, replace=True
        )
        return result.nodes

    def delete(self, ids: SequenceNotStr[NodeId]) -> int:
        try:
            deleted = self.client.data_modeling.instances.delete(nodes=cast(Sequence, ids))
        except CogniteAPIError as e:
            if "not exist" in e.message and "space" in e.message.lower():
                return 0
            raise e
        return len(deleted.nodes)

    def _iterate(
        self,
        data_set_external_id: str | None = None,
        space: str | None = None,
        parent_ids: list[Hashable] | None = None,
    ) -> Iterable[Node]:
        return iter(self.client.data_modeling.instances(space=space))

    def count(self, ids: SequenceNotStr[NodeId]) -> int:
        return len(ids)

    def drop_data(self, ids: SequenceNotStr[NodeId]) -> int:
        # Nodes will be deleted in .delete call.
        return 0

    @classmethod
    @lru_cache(maxsize=1)
    def get_write_cls_parameter_spec(cls) -> ParameterSpecSet:
        node_spec = super().get_write_cls_parameter_spec()
        # This is a deviation between the SDK and the API
        node_spec.add(ParameterSpec(("instanceType",), frozenset({"str"}), is_required=False, _is_nullable=False))
        node_spec.add(
            ParameterSpec(
                ("sources", ANY_INT, "source", "type"),
                frozenset({"str"}),
                is_required=True,
                _is_nullable=False,
            )
        )
        return ParameterSpecSet(node_spec, spec_name=cls.__name__)


class GraphQLLoader(
    ResourceContainerLoader[
        DataModelId, GraphQLDataModelWrite, GraphQLDataModel, GraphQLDataModelWriteList, GraphQLDataModelList
    ]
):
    folder_name = "data_models"
    filename_pattern = r"^.*GraphQLSchema"
    resource_cls = GraphQLDataModel
    resource_write_cls = GraphQLDataModelWrite
    list_cls = GraphQLDataModelList
    list_write_cls = GraphQLDataModelWriteList
    kind = "GraphQLSchema"
    dependencies = frozenset({SpaceLoader, ContainerLoader})
    item_name = "views"
    _doc_url = "Data-models/operation/createDataModels"
    _hash_name = "CDFToolkitHash:"

    def __init__(self, client: ToolkitClient, build_dir: Path) -> None:
        super().__init__(client, build_dir)
        self._graphql_filepath_cache: dict[DataModelId, Path] = {}
        self._datamodels_by_view_id: dict[ViewId, set[DataModelId]] = defaultdict(set)
        self._dependencies_by_datamodel_id: dict[DataModelId, set[ViewId | DataModelId]] = {}

    @property
    def display_name(self) -> str:
        return "graph QL schemas"

    @classmethod
    def get_id(cls, item: GraphQLDataModelWrite | GraphQLDataModel | dict) -> DataModelId:
        if isinstance(item, dict):
            if missing := tuple(k for k in {"space", "externalId", "version"} if k not in item):
                # We need to raise a KeyError with all missing keys to get the correct error message.
                raise KeyError(*missing)
            return DataModelId(space=item["space"], external_id=item["externalId"], version=str(item["version"]))
        return DataModelId(item.space, item.external_id, str(item.version))

    @classmethod
    def dump_id(cls, id: DataModelId) -> dict[str, Any]:
        return id.dump(include_type=False)

    @classmethod
    def get_required_capability(
        cls, items: Sequence[GraphQLDataModelWrite] | None, read_only: bool
    ) -> Capability | list[Capability]:
        if not items and items is not None:
            return []
        actions = [DataModelsAcl.Action.Read] if read_only else [DataModelsAcl.Action.Read, DataModelsAcl.Action.Write]
        return DataModelsAcl(
            actions,
            DataModelsAcl.Scope.SpaceID(list({item.space for item in items}))
            if items is not None
            else DataModelsAcl.Scope.All(),
        )

    @classmethod
    def get_dependent_items(cls, item: dict) -> Iterable[tuple[type[ResourceLoader], Hashable]]:
        if "space" in item:
            yield SpaceLoader, item["space"]

    def load_resource_file(
        self, filepath: Path, environment_variables: dict[str, str | None] | None = None
    ) -> list[dict[str, Any]]:
        # The version is a string, but the user often writes it as an int.
        # YAML will then parse it as an int, for example, `3_0_2` will be parsed as `302`.
        # This is technically a user mistake, as you should quote the version in the YAML file.
        # However, we do not want to put this burden on the user (knowing the intricate workings of YAML),
        # so we fix it here.
        raw_str = quote_int_value_by_key_in_yaml(safe_read(filepath), key="version")
        raw_yaml = load_yaml_inject_variables(
            raw_str, environment_variables or {} if self.do_environment_variable_injection else {}
        )
        raw_list = raw_yaml if isinstance(raw_yaml, list) else [raw_yaml]

        for item in raw_list:
            model_id = self.get_id(item)
            # Find the GraphQL files adjacent to the DML files
            graphql_file = filepath.with_suffix(".graphql")
            if not graphql_file.is_file():
                raise ToolkitFileNotFoundError(
                    f"Failed to find GraphQL file. Expected {graphql_file.name} adjacent to {filepath.as_posix()}"
                )

            self._graphql_filepath_cache[model_id] = graphql_file
            graphql_content = safe_read(graphql_file)

            parser = GraphQLParser(graphql_content, model_id)
            try:
                for view in parser.get_views():
                    self._datamodels_by_view_id[view].add(model_id)
                self._dependencies_by_datamodel_id[model_id] = parser.get_dependencies()
            except Exception as e:
                # We catch a broad exception here to give a more user-friendly error message.
                raise GraphQLParseError(f"Failed to parse GraphQL file {graphql_file.as_posix()}: {e}") from e

            # Add hash to description
            description = item.get("description", "")
            hash_ = calculate_str_or_file_hash(graphql_content)[:8]
            suffix = f"{self._hash_name}{hash_}"
            if len(description) + len(suffix) > 1024:
                LowSeverityWarning(f"Description is above limit for {model_id}. Truncating...").print_warning()
                description = description[: 1024 - len(suffix) + 1 - 3] + "..."
            description += f" {suffix}"
            item["description"] = description
            item["graphqlFile"] = hash_
        return raw_list

    def dump_resource(self, resource: GraphQLDataModel, local: dict[str, Any]) -> dict[str, Any]:
        dumped = resource.as_write().dump()
        if "dml" in local:
            # Reference to the GraphQL file will cause the comparison to always be False
            dumped["dml"] = local["dml"]

        description = resource.description or ""
        if match := re.match(rf"(.|\n)*( {self._hash_name}([a-f0-9]{{8}}))$", description):
            dumped["graphqlFile"] = match.group(3)
        return dumped

    def create(self, items: GraphQLDataModelWriteList) -> list[DMLApplyResult]:
        creation_order = self._topological_sort(items)

        created_list: list[DMLApplyResult] = []
        for item in creation_order:
            item_id = item.as_id()
            graphql_file_content = self._get_graphql_content(item_id)
            if "--verbose" in sys.argv:
                print(f"Deploying GraphQL schema {item_id}")

            created = self.client.dml.apply_dml(
                item.as_id(),
                dml=graphql_file_content,
                name=item.name,
                description=item.description,
                previous_version=item.previous_version,
                preserve_dml=item.preserve_dml,
            )
            created_list.append(created)
        return created_list

    def _get_graphql_content(self, data_model_id: DataModelId) -> str:
        filepath = self._graphql_filepath_cache.get(data_model_id)
        if filepath is None:
            raise ToolkitFileNotFoundError(f"Could not find the GraphQL file for {data_model_id}")
        return safe_read(filepath)

    def retrieve(self, ids: SequenceNotStr[DataModelId]) -> GraphQLDataModelList:
        result = self.client.data_modeling.data_models.retrieve(list(ids), inline_views=False)
        return GraphQLDataModelList([GraphQLDataModel._load(d.dump()) for d in result])

    def update(self, items: GraphQLDataModelWriteList) -> list[DMLApplyResult]:
        return self.create(items)

    def delete(self, ids: SequenceNotStr[DataModelId]) -> int:
        retrieved = self.retrieve(ids)
        views = {view for dml in retrieved for view in dml.views or []}
        deleted = len(self.client.data_modeling.data_models.delete(list(ids)))
        deleted += len(self.client.data_modeling.views.delete(list(views)))
        return deleted

    def _iterate(
        self,
        data_set_external_id: str | None = None,
        space: str | None = None,
        parent_ids: list[Hashable] | None = None,
    ) -> Iterable[GraphQLDataModel]:
        return iter(GraphQLDataModel._load(d.dump()) for d in self.client.data_modeling.data_models)

    def count(self, ids: SequenceNotStr[DataModelId]) -> int:
        retrieved = self.retrieve(ids)
        return sum(len(d.views or []) for d in retrieved)

    def drop_data(self, ids: SequenceNotStr[DataModelId]) -> int:
        return self.delete(ids)

    def _topological_sort(self, items: GraphQLDataModelWriteList) -> list[GraphQLDataModelWrite]:
        to_sort = {item.as_id(): item for item in items}
        dependencies: dict[DataModelId, set[DataModelId]] = {}
        for item in items:
            item_id = item.as_id()
            dependencies[item_id] = set()
            for dependency in self._dependencies_by_datamodel_id.get(item_id, []):
                if isinstance(dependency, DataModelId) and dependency in to_sort:
                    dependencies[item_id].add(dependency)
                elif isinstance(dependency, ViewId):
                    for model_id in self._datamodels_by_view_id.get(dependency, set()):
                        if model_id in to_sort:
                            dependencies[item_id].add(model_id)
        try:
            return [to_sort[item_id] for item_id in TopologicalSorter(dependencies).static_order()]
        except CycleError as e:
            raise ToolkitCycleError(
                f"Cannot create GraphQL schemas. Cycle detected between models {e.args} using the @import directive.",
                *e.args[1:],
            )


@final
class EdgeLoader(ResourceContainerLoader[EdgeId, EdgeApply, Edge, EdgeApplyList, EdgeList]):
    item_name = "edges"
    folder_name = "data_models"
    filename_pattern = r"^.*edge"
    resource_cls = Edge
    resource_write_cls = EdgeApply
    list_cls = EdgeList
    list_write_cls = EdgeApplyList
    kind = "Edge"
    dependencies = frozenset({SpaceLoader, ViewLoader, ContainerLoader, NodeLoader})
    _doc_url = "Instances/operation/applyNodeAndEdges"

    @property
    def display_name(self) -> str:
        return "edges"

    @classmethod
    def get_required_capability(
        cls, items: Sequence[EdgeApply] | None, read_only: bool
    ) -> Capability | list[Capability]:
        if not items and items is not None:
            return []

        actions = (
            [DataModelInstancesAcl.Action.Read]
            if read_only
            else [DataModelInstancesAcl.Action.Read, DataModelInstancesAcl.Action.Write]
        )

        return DataModelInstancesAcl(
            actions,
            DataModelInstancesAcl.Scope.SpaceID(list({item.space for item in items}))
            if items is not None
            else DataModelInstancesAcl.Scope.All(),
        )

    @classmethod
    def get_id(cls, item: EdgeApply | Edge | dict) -> EdgeId:
        if isinstance(item, dict):
            if missing := tuple(k for k in {"space", "externalId"} if k not in item):
                # We need to raise a KeyError with all missing keys to get the correct error message.
                raise KeyError(*missing)
            return EdgeId(space=item["space"], external_id=item["externalId"])
        return item.as_id()

    @classmethod
    def dump_id(cls, id: EdgeId) -> dict[str, Any]:
        return id.dump()

    @classmethod
    def get_dependent_items(cls, item: dict) -> Iterable[tuple[type[ResourceLoader], Hashable]]:
        if "space" in item:
            yield SpaceLoader, item["space"]
        for source in item.get("sources", []):
            if (identifier := source.get("source")) and isinstance(identifier, dict):
                if identifier.get("type") == "view" and in_dict(("space", "externalId", "version"), identifier):
                    yield (
                        ViewLoader,
                        ViewId(
                            identifier["space"],
                            identifier["externalId"],
                            str(v) if (v := identifier.get("version")) else None,
                        ),
                    )
                elif identifier.get("type") == "container" and in_dict(("space", "externalId"), identifier):
                    yield ContainerLoader, ContainerId(identifier["space"], identifier["externalId"])

        for key in ["startNode", "endNode", "type"]:
            if node_ref := item.get(key):
                if isinstance(node_ref, dict) and in_dict(("space", "externalId"), node_ref):
                    yield NodeLoader, NodeId(node_ref["space"], node_ref["externalId"])

    def dump_resource(self, resource: Edge, local: dict[str, Any]) -> dict[str, Any]:
        # CDF resource does not have properties set, so we need to do a lookup
        sources = [ViewId.load(source["source"]) for source in local.get("sources", []) if "source" in source]
        try:
            cdf_resource_with_properties = self.client.data_modeling.instances.retrieve(
                edges=resource.as_id(), sources=sources
            ).edges[0]
        except CogniteAPIError:
            # View does not exist
            dumped = resource.as_write().dump()
        else:
            dumped = cdf_resource_with_properties.as_write().dump()

        if "existingVersion" not in local:
            # Existing version is typically not set when creating nodes, but we get it back
            # when we retrieve the node from the server.
            dumped.pop("existingVersion", None)

        return dumped

    def dump_resource_legacy(
        self, resource: EdgeApply, source_file: Path, local_resource: EdgeApply
    ) -> tuple[dict[str, Any], dict[Path, str]]:
        resource_edge = resource
        local_node = local_resource
        # Retrieve node again to get properties.
        view_ids = {source.source for source in local_node.sources or [] if isinstance(source.source, ViewId)}
        edges = self.client.data_modeling.instances.retrieve(edges=local_node.as_id(), sources=list(view_ids)).edges
        if not edges:
            print(
                f"  [bold yellow]WARNING:[/] Node {local_resource.as_id()} does not exist. Failed to fetch properties."
            )
            return resource_edge.dump(), {}
        node = edges[0]
        edge_dumped = node.as_write().dump()
        edge_dumped.pop("existingVersion", None)

        # Node files have configuration in the first 3 lines, we need to include this in the dumped file.
        dumped = yaml.safe_load("\n".join(safe_read(source_file).splitlines()[:3]))

        dumped["edges"] = [edge_dumped]

        return dumped, {}

    def create(self, items: EdgeApplyList) -> EdgeApplyResultList:
        result = self.client.data_modeling.instances.apply(
            edges=items, auto_create_direct_relations=True, replace=False
        )
        return result.edges

    def retrieve(self, ids: SequenceNotStr[EdgeId]) -> EdgeList:
        return self.client.data_modeling.instances.retrieve(nodes=cast(Sequence, ids)).edges

    def update(self, items: EdgeApplyList) -> EdgeApplyResultList:
        result = self.client.data_modeling.instances.apply(
            edges=items, auto_create_direct_relations=False, replace=True
        )
        return result.edges

    def delete(self, ids: SequenceNotStr[EdgeId]) -> int:
        try:
            deleted = self.client.data_modeling.instances.delete(edges=cast(Sequence, ids))
        except CogniteAPIError as e:
            if "not exist" in e.message and "space" in e.message.lower():
                return 0
            raise e
        return len(deleted.edges)

    def _iterate(
        self,
        data_set_external_id: str | None = None,
        space: str | None = None,
        parent_ids: list[Hashable] | None = None,
    ) -> Iterable[Edge]:
        return iter(self.client.data_modeling.instances(chunk_size=None, instance_type="edge", space=space))

    def count(self, ids: SequenceNotStr[EdgeId]) -> int:
        return len(ids)

    def drop_data(self, ids: SequenceNotStr[EdgeId]) -> int:
        # Edges will be deleted in .delete call.
        return 0

    @classmethod
    @lru_cache(maxsize=1)
    def get_write_cls_parameter_spec(cls) -> ParameterSpecSet:
        node_spec = super().get_write_cls_parameter_spec()
        # This is a deviation between the SDK and the API
        node_spec.add(ParameterSpec(("instanceType",), frozenset({"str"}), is_required=False, _is_nullable=False))
        node_spec.add(
            ParameterSpec(
                ("sources", ANY_INT, "source", "type"),
                frozenset({"str"}),
                is_required=True,
                _is_nullable=False,
            )
        )
        return ParameterSpecSet(node_spec, spec_name=cls.__name__)
