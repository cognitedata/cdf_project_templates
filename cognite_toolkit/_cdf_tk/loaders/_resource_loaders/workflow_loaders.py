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

import json
from collections.abc import Hashable, Iterable, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any, final

from cognite.client.data_classes import (
    ClientCredentials,
    Workflow,
    WorkflowList,
    WorkflowTrigger,
    WorkflowTriggerList,
    WorkflowTriggerUpsert,
    WorkflowTriggerUpsertList,
    WorkflowUpsert,
    WorkflowUpsertList,
    WorkflowVersion,
    WorkflowVersionId,
    WorkflowVersionList,
    WorkflowVersionUpsert,
    WorkflowVersionUpsertList,
)
from cognite.client.data_classes.capabilities import (
    Capability,
    WorkflowOrchestrationAcl,
)
from cognite.client.exceptions import CogniteAuthError, CogniteNotFoundError
from cognite.client.utils.useful_types import SequenceNotStr
from rich import print
from rich.console import Console

from cognite_toolkit._cdf_tk._parameters import ANY_INT, ANY_STR, ANYTHING, ParameterSpec, ParameterSpecSet
from cognite_toolkit._cdf_tk.client import ToolkitClient
from cognite_toolkit._cdf_tk.exceptions import (
    ResourceCreationError,
    ToolkitRequiredValueError,
)
from cognite_toolkit._cdf_tk.feature_flags import Flags
from cognite_toolkit._cdf_tk.loaders._base_loaders import ResourceLoader
from cognite_toolkit._cdf_tk.tk_warnings import (
    LowSeverityWarning,
    MissingReferencedWarning,
    ToolkitWarning,
)
from cognite_toolkit._cdf_tk.utils import calculate_secure_hash, humanize_collection, to_directory_compatible
from cognite_toolkit._cdf_tk.utils.cdf import read_auth, try_find_error
from cognite_toolkit._cdf_tk.utils.diff_list import diff_list_hashable, diff_list_identifiable

from .auth_loaders import GroupAllScopedLoader
from .data_organization_loaders import DataSetsLoader
from .function_loaders import FunctionLoader
from .group_scoped_loader import GroupResourceScopedLoader
from .transformation_loaders import TransformationLoader


@final
class WorkflowLoader(ResourceLoader[str, WorkflowUpsert, Workflow, WorkflowUpsertList, WorkflowList]):
    folder_name = "workflows"
    filename_pattern = r"^.*Workflow$"
    resource_cls = Workflow
    resource_write_cls = WorkflowUpsert
    list_cls = WorkflowList
    list_write_cls = WorkflowUpsertList
    kind = "Workflow"
    dependencies = frozenset(
        {
            GroupAllScopedLoader,
            TransformationLoader,
            FunctionLoader,
            DataSetsLoader,
        }
    )
    _doc_base_url = "https://api-docs.cognite.com/20230101-beta/tag/"
    _doc_url = "Workflows/operation/CreateOrUpdateWorkflow"

    @property
    def display_name(self) -> str:
        return "workflows"

    @classmethod
    def get_required_capability(
        cls, items: Sequence[WorkflowUpsert] | None, read_only: bool
    ) -> Capability | list[Capability]:
        if not items and items is not None:
            return []

        actions = (
            [WorkflowOrchestrationAcl.Action.Read]
            if read_only
            else [WorkflowOrchestrationAcl.Action.Read, WorkflowOrchestrationAcl.Action.Write]
        )

        return WorkflowOrchestrationAcl(
            actions,
            WorkflowOrchestrationAcl.Scope.All(),
        )

    @classmethod
    def get_id(cls, item: Workflow | WorkflowUpsert | dict) -> str:
        if isinstance(item, dict):
            return item["externalId"]
        if item.external_id is None:
            raise ToolkitRequiredValueError("Workflow must have external_id set.")
        return item.external_id

    @classmethod
    def dump_id(cls, id: str) -> dict[str, Any]:
        return {"externalId": id}

    def load_resource(self, resource: dict[str, Any], is_dry_run: bool = False) -> WorkflowUpsert:
        if ds_external_id := resource.pop("dataSetExternalId", None):
            resource["dataSetId"] = self.client.lookup.data_sets.id(ds_external_id, is_dry_run)
        return WorkflowUpsert._load(resource)

    def dump_resource(self, resource: Workflow, local: dict[str, Any] | None = None) -> dict[str, Any]:
        dumped = resource.as_write().dump()
        if data_set_id := dumped.pop("dataSetId", None):
            dumped["dataSetExternalId"] = self.client.lookup.data_sets.external_id(data_set_id)
        return dumped

    def retrieve(self, ids: SequenceNotStr[str]) -> WorkflowList:
        workflows = []
        for ext_id in ids:
            workflow = self.client.workflows.retrieve(external_id=ext_id)
            if workflow:
                workflows.append(workflow)
        return WorkflowList(workflows)

    def _upsert(self, items: WorkflowUpsert | WorkflowUpsertList) -> WorkflowList:
        upserts = [items] if isinstance(items, WorkflowUpsert) else items
        return WorkflowList([self.client.workflows.upsert(upsert) for upsert in upserts])

    def create(self, items: WorkflowUpsert | WorkflowUpsertList) -> WorkflowList:
        return self._upsert(items)

    def update(self, items: WorkflowUpsertList) -> WorkflowList:
        return self._upsert(items)

    def delete(self, ids: SequenceNotStr[str]) -> int:
        successes = 0
        for id_ in ids:
            try:
                self.client.workflows.delete(external_id=id_)
            except CogniteNotFoundError:
                print(f"  [bold yellow]WARNING:[/] Workflow {id_} does not exist, skipping delete.")
            else:
                successes += 1
        return successes

    def _iterate(
        self,
        data_set_external_id: str | None = None,
        space: str | None = None,
        parent_ids: list[Hashable] | None = None,
    ) -> Iterable[Workflow]:
        if data_set_external_id is None:
            yield from self.client.workflows.list(limit=-1)
            return
        data_set = self.client.data_sets.retrieve(external_id=data_set_external_id)
        if data_set is None:
            raise ToolkitRequiredValueError(f"DataSet {data_set_external_id!r} does not exist")
        for workflow in self.client.workflows.list(limit=-1):
            if workflow.data_set_id == data_set.id:
                yield workflow

    @classmethod
    @lru_cache(maxsize=1)
    def get_write_cls_parameter_spec(cls) -> ParameterSpecSet:
        spec = super().get_write_cls_parameter_spec()
        spec.add(
            ParameterSpec(
                ("dataSetExternalId",),
                frozenset({"str"}),
                is_required=False,
                _is_nullable=True,
            )
        )
        spec.discard(
            ParameterSpec(
                ("dataSetId",),
                frozenset({"str"}),
                is_required=False,
                _is_nullable=True,
            )
        )
        return spec

    @classmethod
    def get_dependent_items(cls, item: dict) -> Iterable[tuple[type[ResourceLoader], Hashable]]:
        """Returns all items that this item requires.

        For example, a TimeSeries requires a DataSet, so this method would return the
        DatasetLoader and identifier of that dataset.
        """
        if "dataSetExternalId" in item:
            yield DataSetsLoader, item["dataSetExternalId"]


@final
class WorkflowVersionLoader(
    ResourceLoader[
        WorkflowVersionId, WorkflowVersionUpsert, WorkflowVersion, WorkflowVersionUpsertList, WorkflowVersionList
    ]
):
    folder_name = "workflows"
    filename_pattern = r"^.*WorkflowVersion$"
    resource_cls = WorkflowVersion
    resource_write_cls = WorkflowVersionUpsert
    list_cls = WorkflowVersionList
    list_write_cls = WorkflowVersionUpsertList
    kind = "WorkflowVersion"
    dependencies = frozenset({WorkflowLoader})
    parent_resource = frozenset({WorkflowLoader})

    _doc_base_url = "https://api-docs.cognite.com/20230101-beta/tag/"
    _doc_url = "Workflow-versions/operation/CreateOrUpdateWorkflowVersion"

    @property
    def display_name(self) -> str:
        return "workflow versions"

    @classmethod
    def get_required_capability(
        cls, items: Sequence[WorkflowVersionUpsert] | None, read_only: bool
    ) -> Capability | list[Capability]:
        if not items and items is not None:
            return []

        actions = (
            [WorkflowOrchestrationAcl.Action.Read]
            if read_only
            else [WorkflowOrchestrationAcl.Action.Read, WorkflowOrchestrationAcl.Action.Write]
        )

        return WorkflowOrchestrationAcl(
            actions,
            WorkflowOrchestrationAcl.Scope.All(),
        )

    @classmethod
    def get_id(cls, item: WorkflowVersion | WorkflowVersionUpsert | dict) -> WorkflowVersionId:
        if isinstance(item, dict):
            if missing := tuple(k for k in {"workflowExternalId", "version"} if k not in item):
                # We need to raise a KeyError with all missing keys to get the correct error message.
                raise KeyError(*missing)
            return WorkflowVersionId(item["workflowExternalId"], item["version"])
        return item.as_id()

    @classmethod
    def dump_id(cls, id: WorkflowVersionId) -> dict[str, Any]:
        return id.dump()

    def dump_resource(self, resource: WorkflowVersion, local: dict[str, Any] | None = None) -> dict[str, Any]:
        dumped = resource.as_write().dump()
        if not local:
            return dumped
        # Sort to match the order of the local tasks
        local_task_order_by_id = {
            task["externalId"]: no for no, task in enumerate(local["workflowDefinition"]["tasks"])
        }
        end_of_list = len(local_task_order_by_id)
        dumped["workflowDefinition"]["tasks"] = sorted(
            dumped["workflowDefinition"]["tasks"],
            key=lambda t: local_task_order_by_id.get(t["externalId"], end_of_list),
        )

        # Function tasks with empty data can be an empty dict or missing data field
        # This ensures that these two are treated as the same
        local_task_by_id = {task["externalId"]: task for task in local["workflowDefinition"]["tasks"]}
        for cdf_task in dumped["workflowDefinition"]["tasks"]:
            task_id = cdf_task["externalId"]
            if task_id not in local_task_by_id:
                continue
            local_task = local_task_by_id[task_id]
            if local_task["type"] == "function" and cdf_task["type"] == "function":
                cdf_parameters = cdf_task["parameters"]
                local_parameters = local_task["parameters"]
                if "function" in cdf_parameters and "function" in local_parameters:
                    cdf_function = cdf_parameters["function"]
                    local_function = local_parameters["function"]
                    if local_function["data"] == {} and "data" not in cdf_function:
                        cdf_parameters["function"] = local_parameters["function"]
        return dumped

    def diff_list(
        self, local: list[Any], cdf: list[Any], json_path: tuple[str | int, ...]
    ) -> tuple[dict[int, int], list[int]]:
        if json_path == ("workflowDefinition", "tasks"):
            return diff_list_identifiable(local, cdf, get_identifier=lambda t: t["externalId"])
        elif len(json_path) == 4 and json_path[:2] == ("workflowDefinition", "tasks") and json_path[3] == "dependsOn":
            return diff_list_identifiable(local, cdf, get_identifier=lambda t: t["externalId"])
        elif len(json_path) >= 2 and json_path[:2] == ("workflowDefinition", "tasks"):
            # Assume all other arrays in the tasks are hashable
            return diff_list_hashable(local, cdf)
        return super().diff_list(local, cdf, json_path)

    @classmethod
    def get_dependent_items(cls, item: dict) -> Iterable[tuple[type[ResourceLoader], Hashable]]:
        if "workflowExternalId" in item:
            yield WorkflowLoader, item["workflowExternalId"]

    @classmethod
    def check_item(cls, item: dict, filepath: Path, element_no: int | None) -> list[ToolkitWarning]:
        warnings: list[ToolkitWarning] = []
        tasks = item.get("workflowDefinition", {}).get("tasks", [])
        if not tasks:
            # We do not check for tasks here, that is done by comparing the spec.
            return warnings
        # Checking for invalid dependsOn
        tasks_ids = {task["externalId"] for task in tasks if "externalId" in task}
        for task in tasks:
            if not isinstance(depends_on := task.get("dependsOn"), list):
                continue
            invalid_tasks = [
                dep["externalId"] for dep in depends_on if "externalId" in dep and dep["externalId"] not in tasks_ids
            ]
            if invalid_tasks:
                warnings.append(
                    MissingReferencedWarning(
                        filepath=filepath,
                        element_no=element_no,
                        path=tuple(),
                        message=f"Task {task['externalId']!r} depends on non-existing task(s): {humanize_collection(invalid_tasks)!r}",
                    )
                )
        return warnings

    def retrieve(self, ids: SequenceNotStr[WorkflowVersionId]) -> WorkflowVersionList:
        if not ids:
            return WorkflowVersionList([])
        return self.client.workflows.versions.list(list(ids))

    def _upsert(self, items: WorkflowVersionUpsertList) -> WorkflowVersionList:
        return WorkflowVersionList([self.client.workflows.versions.upsert(item) for item in items])

    def create(self, items: WorkflowVersionUpsertList) -> WorkflowVersionList:
        upserted = []
        for item in items:
            upserted.append(self.client.workflows.versions.upsert(item))
        return WorkflowVersionList(upserted)

    def update(self, items: WorkflowVersionUpsertList) -> WorkflowVersionList:
        updated = []
        for item in items:
            updated.append(self.client.workflows.versions.upsert(item))
        return WorkflowVersionList(updated)

    def delete(self, ids: SequenceNotStr[WorkflowVersionId]) -> int:
        successes = 0
        for id in ids:
            try:
                self.client.workflows.versions.delete(id)
            except CogniteNotFoundError:
                print(f"  [bold yellow]WARNING:[/] WorkflowVersion {id} does not exist, skipping delete.")
            else:
                successes += 1
        return successes

    def _iterate(
        self,
        data_set_external_id: str | None = None,
        space: str | None = None,
        parent_ids: list[Hashable] | None = None,
    ) -> Iterable[WorkflowVersion]:
        workflow_ids = [parent_id for parent_id in parent_ids if isinstance(parent_id, str)] if parent_ids else None
        return self.client.workflows.versions.list(limit=-1, workflow_version_ids=workflow_ids)  # type: ignore[arg-type]

    @classmethod
    @lru_cache(maxsize=1)
    def get_write_cls_parameter_spec(cls) -> ParameterSpecSet:
        spec = super().get_write_cls_parameter_spec()
        # The Parameter class in the SDK class WorkflowVersion implementation is deviating from the API.
        # So we need to modify the spec to match the API.
        parameter_path = ("workflowDefinition", "tasks", ANY_INT, "parameters")
        length = len(parameter_path)
        for item in spec:
            if len(item.path) >= length + 1 and item.path[:length] == parameter_path[:length]:
                # Add extra ANY_STR layer
                # The spec class is immutable, so we use this trick to modify it.
                object.__setattr__(item, "path", item.path[:length] + (ANY_STR,) + item.path[length:])
        spec.add(ParameterSpec((*parameter_path, ANY_STR), frozenset({"dict"}), is_required=True, _is_nullable=False))
        # The depends on is implemented as a list of string in the SDK, but in the API spec it
        # is a list of objects with one 'externalId' field.
        spec.add(
            ParameterSpec(
                ("workflowDefinition", "tasks", ANY_INT, "dependsOn", ANY_INT, "externalId"),
                frozenset({"str"}),
                is_required=False,
                _is_nullable=False,
            )
        )
        spec.add(
            ParameterSpec(
                ("workflowDefinition", "tasks", ANY_INT, "type"),
                frozenset({"str"}),
                is_required=True,
                _is_nullable=False,
            )
        )
        spec.add(
            ParameterSpec(
                ("workflowDefinition", "tasks", ANY_INT, "parameters", "subworkflow", ANYTHING),
                frozenset({"dict"}),
                is_required=False,
                _is_nullable=False,
            )
        )
        return spec

    @classmethod
    def as_str(cls, id: WorkflowVersionId) -> str:
        if id.version is None:
            version = ""
        elif id.version.startswith("v"):
            version = f"_{id.version}"
        else:
            version = f"_v{id.version}"

        return to_directory_compatible(f"{id.workflow_external_id}{version}")


@final
class WorkflowTriggerLoader(
    ResourceLoader[str, WorkflowTriggerUpsert, WorkflowTrigger, WorkflowTriggerUpsertList, WorkflowTriggerList]
):
    folder_name = "workflows"
    filename_pattern = r"^.*WorkflowTrigger$"
    resource_cls = WorkflowTrigger
    resource_write_cls = WorkflowTriggerUpsert
    list_cls = WorkflowTriggerList
    list_write_cls = WorkflowTriggerUpsertList
    kind = "WorkflowTrigger"
    dependencies = frozenset({WorkflowLoader, WorkflowVersionLoader, GroupResourceScopedLoader, GroupAllScopedLoader})
    parent_resource = frozenset({WorkflowLoader})

    _doc_url = "Workflow-triggers/operation/CreateOrUpdateTriggers"

    class _MetadataKey:
        secret_hash = "cognite-toolkit-auth-hash"

    def __init__(self, client: ToolkitClient, build_dir: Path | None, console: Console | None = None):
        super().__init__(client, build_dir, console)
        self._authentication_by_id: dict[str, ClientCredentials] = {}

    @property
    def display_name(self) -> str:
        return "workflow triggers"

    @classmethod
    def get_id(cls, item: WorkflowTriggerUpsert | WorkflowTrigger | dict) -> str:
        if isinstance(item, dict):
            return item["externalId"]
        return item.external_id

    @classmethod
    def dump_id(cls, id: str) -> dict[str, Any]:
        return {"externalId": id}

    @classmethod
    def get_required_capability(
        cls, items: Sequence[WorkflowTriggerUpsert] | None, read_only: bool
    ) -> Capability | list[Capability]:
        if not items and items is not None:
            return []

        capability = (
            [WorkflowOrchestrationAcl.Action.Read]
            if read_only
            else [WorkflowOrchestrationAcl.Action.Read, WorkflowOrchestrationAcl.Action.Write]
        )

        return WorkflowOrchestrationAcl(
            capability,
            WorkflowOrchestrationAcl.Scope.All(),
        )

    def create(self, items: WorkflowTriggerUpsertList) -> WorkflowTriggerList:
        created = WorkflowTriggerList([])
        for item in items:
            created.append(self._create_item(item))
        return created

    def _create_item(self, item: WorkflowTriggerUpsert) -> WorkflowTrigger:
        credentials = self._authentication_by_id.get(item.external_id)
        try:
            return self.client.workflows.triggers.upsert(item, credentials)
        except CogniteAuthError as e:
            if hint := try_find_error(credentials):
                raise ResourceCreationError(f"Failed to create WorkflowTrigger {item.external_id}: {hint}") from e
            raise e

    def retrieve(self, ids: SequenceNotStr[str]) -> WorkflowTriggerList:
        all_triggers = self.client.workflows.triggers.list(limit=-1)
        lookup = set(ids)
        return WorkflowTriggerList([trigger for trigger in all_triggers if trigger.external_id in lookup])

    def update(self, items: WorkflowTriggerUpsertList) -> WorkflowTriggerList:
        exising = self.client.workflows.triggers.list(limit=-1)
        existing_lookup = {trigger.external_id: trigger for trigger in exising}
        updated = WorkflowTriggerList([])
        for item in items:
            if item.external_id in existing_lookup:
                self.client.workflows.triggers.delete(external_id=item.external_id)

            created = self._create_item(item)
            updated.append(created)
        return updated

    def delete(self, ids: SequenceNotStr[str]) -> int:
        successes = 0
        for id in ids:
            try:
                self.client.workflows.triggers.delete(external_id=id)
            except CogniteNotFoundError:
                LowSeverityWarning(f"WorkflowTrigger {id} does not exist, skipping delete.").print_warning()
            else:
                successes += 1
        return successes

    def _iterate(
        self,
        data_set_external_id: str | None = None,
        space: str | None = None,
        parent_ids: list[Hashable] | None = None,
    ) -> Iterable[WorkflowTrigger]:
        triggers = self.client.workflows.triggers.list(limit=-1)
        if parent_ids is not None:
            # Parent = Workflow
            workflow_ids = {parent_id for parent_id in parent_ids if isinstance(parent_id, str)}
            return (trigger for trigger in triggers if trigger.workflow_external_id in workflow_ids)
        return triggers

    @classmethod
    @lru_cache(maxsize=1)
    def get_write_cls_parameter_spec(cls) -> ParameterSpecSet:
        spec = super().get_write_cls_parameter_spec()
        # Removed by the SDK
        spec.add(
            ParameterSpec(
                ("triggerRule", "triggerType"),
                frozenset({"str"}),
                is_required=True,
                _is_nullable=False,
            )
        )
        spec.add(
            ParameterSpec(
                ("authentication",),
                frozenset({"dict"}),
                is_required=True,
                _is_nullable=False,
            )
        )
        spec.add(
            ParameterSpec(
                ("authentication", "clientId"),
                frozenset({"str"}),
                is_required=False,
                _is_nullable=False,
            )
        )
        spec.add(
            ParameterSpec(
                ("authentication", "clientSecret"),
                frozenset({"str"}),
                is_required=False,
                _is_nullable=False,
            )
        )
        return spec

    @classmethod
    def get_dependent_items(cls, item: dict) -> Iterable[tuple[type[ResourceLoader], Hashable]]:
        """Returns all items that this item requires."""
        if "workflowExternalId" in item:
            yield WorkflowLoader, item["workflowExternalId"]

            if "workflowVersion" in item:
                yield WorkflowVersionLoader, WorkflowVersionId(item["workflowExternalId"], item["workflowVersion"])

    def load_resource_file(
        self, filepath: Path, environment_variables: dict[str, str | None] | None = None
    ) -> list[dict[str, Any]]:
        resources = super().load_resource_file(filepath, environment_variables)

        # We need to the auth hash calculation here, as the output of the load_resource_file
        # is used to compare with the CDF resource.
        for resource in resources:
            identifier = self.get_id(resource)
            credentials = read_auth(identifier, resource, self.client, "workflow trigger", self.console)
            self._authentication_by_id[identifier] = credentials
            if Flags.CREDENTIALS_HASH.is_enabled():
                if "metadata" not in resource:
                    resource["metadata"] = {}
                    resource["metadata"][self._MetadataKey.secret_hash] = calculate_secure_hash(
                        credentials.dump(camel_case=True), shorten=True
                    )
        return resources

    def load_resource(self, resource: dict[str, Any], is_dry_run: bool = False) -> WorkflowTriggerUpsert:
        if isinstance(resource.get("data"), dict):
            resource["data"] = json.dumps(resource["data"])
        return WorkflowTriggerUpsert._load(resource)

    def dump_resource(self, resource: WorkflowTrigger, local: dict[str, Any] | None = None) -> dict[str, Any]:
        dumped = resource.as_write().dump()
        local = local or {}
        if isinstance(dumped.get("data"), str) and isinstance(local.get("data"), dict):
            dumped["data"] = json.loads(dumped["data"])

        if "authentication" in local:
            # Changes in auth will be detected by the hash. We need to do this to ensure
            # that the pull command works.
            dumped["authentication"] = local["authentication"]
        return dumped
