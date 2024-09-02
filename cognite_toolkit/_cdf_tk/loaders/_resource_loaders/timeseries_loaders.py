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

from collections.abc import Hashable, Iterable
from functools import lru_cache
from pathlib import Path
from typing import Any, cast, final

from cognite.client.data_classes import (
    DatapointsList,
    DatapointSubscription,
    DatapointSubscriptionList,
    DataPointSubscriptionUpdate,
    DataPointSubscriptionWrite,
    DatapointSubscriptionWriteList,
    TimeSeries,
    TimeSeriesList,
    TimeSeriesWrite,
    TimeSeriesWriteList,
)
from cognite.client.data_classes.capabilities import (
    Capability,
    TimeSeriesAcl,
    TimeSeriesSubscriptionsAcl,
)
from cognite.client.exceptions import CogniteAPIError, CogniteNotFoundError
from cognite.client.utils.useful_types import SequenceNotStr

from cognite_toolkit._cdf_tk._parameters import ANY_STR, ParameterSpec, ParameterSpecSet
from cognite_toolkit._cdf_tk.constants import MAX_TIMESTAMP_MS, MIN_TIMESTAMP_MS
from cognite_toolkit._cdf_tk.exceptions import (
    ToolkitRequiredValueError,
)
from cognite_toolkit._cdf_tk.loaders._base_loaders import ResourceContainerLoader, ResourceLoader
from cognite_toolkit._cdf_tk.utils import (
    CDFToolConfig,
    load_yaml_inject_variables,
)

from .asset_loaders import AssetLoader
from .auth_loaders import GroupAllScopedLoader, SecurityCategoryLoader
from .data_organization_loaders import DataSetsLoader


@final
class TimeSeriesLoader(ResourceContainerLoader[str, TimeSeriesWrite, TimeSeries, TimeSeriesWriteList, TimeSeriesList]):
    item_name = "datapoints"
    folder_name = "timeseries"
    filename_pattern = r"^(?!.*DatapointSubscription$).*"
    resource_cls = TimeSeries
    resource_write_cls = TimeSeriesWrite
    list_cls = TimeSeriesList
    list_write_cls = TimeSeriesWriteList
    kind = "TimeSeries"
    dependencies = frozenset({DataSetsLoader, GroupAllScopedLoader, AssetLoader})
    _doc_url = "Time-series/operation/postTimeSeries"

    @classmethod
    def get_required_capability(cls, items: TimeSeriesWriteList) -> Capability | list[Capability]:
        if not items:
            return []

        dataset_ids = {item.data_set_id for item in items if item.data_set_id}

        scope = TimeSeriesAcl.Scope.DataSet(list(dataset_ids)) if dataset_ids else TimeSeriesAcl.Scope.All()

        return TimeSeriesAcl(
            [TimeSeriesAcl.Action.Read, TimeSeriesAcl.Action.Write],
            scope,  # type: ignore[arg-type]
        )

    @classmethod
    def get_id(cls, item: TimeSeries | TimeSeriesWrite | dict) -> str:
        if isinstance(item, dict):
            return item["externalId"]
        if item.external_id is None:
            raise ToolkitRequiredValueError("TimeSeries must have external_id set.")
        return item.external_id

    @classmethod
    def dump_id(cls, id: str) -> dict[str, Any]:
        return {"externalId": id}

    @classmethod
    def get_dependent_items(cls, item: dict) -> Iterable[tuple[type[ResourceLoader], Hashable]]:
        if "dataSetExternalId" in item:
            yield DataSetsLoader, item["dataSetExternalId"]
        if "securityCategoryNames" in item:
            for security_category in item["securityCategoryNames"]:
                yield SecurityCategoryLoader, security_category
        if "assetExternalId" in item:
            yield AssetLoader, item["assetExternalId"]

    def load_resource(
        self, filepath: Path | str, ToolGlobals: CDFToolConfig, skip_validation: bool
    ) -> TimeSeriesWriteList:
        resources = load_yaml_inject_variables(filepath, {})
        if not isinstance(resources, list):
            resources = [resources]
        for resource in resources:
            if resource.get("dataSetExternalId") is not None:
                ds_external_id = resource.pop("dataSetExternalId")
                resource["dataSetId"] = ToolGlobals.verify_dataset(
                    ds_external_id, skip_validation, action="replace dataSetExternalId with dataSetId in time series"
                )
            if "securityCategoryNames" in resource:
                if security_categories_names := resource.pop("securityCategoryNames", []):
                    security_categories = ToolGlobals.verify_security_categories(
                        security_categories_names,
                        skip_validation,
                        action="replace securityCategoryNames with securityCategoryIDs in time series",
                    )
                    resource["securityCategories"] = security_categories
            if resource.get("securityCategories") is None:
                # Bug in SDK, the read version sets security categories to an empty list.
                resource["securityCategories"] = []
            if "assetExternalId" in resource:
                asset_external_id = resource.pop("assetExternalId")
                resource["assetId"] = ToolGlobals.verify_asset(
                    asset_external_id, skip_validation, action="replace assetExternalId with assetId in time series"
                )
        return TimeSeriesWriteList.load(resources)

    def _are_equal(
        self, local: TimeSeriesWrite, cdf_resource: TimeSeries, return_dumped: bool = False
    ) -> bool | tuple[bool, dict[str, Any], dict[str, Any]]:
        local_dumped = local.dump()
        cdf_dumped = cdf_resource.as_write().dump()

        # If dataSetId or SecurityCategories are not set in the local, but are set in the CDF, it is a dry run
        # and we assume they are the same.
        if local_dumped.get("dataSetId") == -1 and "dataSetId" in cdf_dumped:
            local_dumped["dataSetId"] = cdf_dumped["dataSetId"]
        if (
            all(s == -1 for s in local_dumped.get("securityCategories", []))
            and "securityCategories" in cdf_dumped
            and len(cdf_dumped["securityCategories"]) == len(local_dumped.get("securityCategories", []))
        ):
            local_dumped["securityCategories"] = cdf_dumped["securityCategories"]
        if local_dumped.get("assetId") == -1 and "assetId" in cdf_dumped:
            local_dumped["assetId"] = cdf_dumped["assetId"]
        return self._return_are_equal(local_dumped, cdf_dumped, return_dumped)

    def create(self, items: TimeSeriesWriteList) -> TimeSeriesList:
        return self.client.time_series.create(items)

    def retrieve(self, ids: SequenceNotStr[str]) -> TimeSeriesList:
        return self.client.time_series.retrieve_multiple(
            external_ids=cast(SequenceNotStr[str], ids), ignore_unknown_ids=True
        )

    def update(self, items: TimeSeriesWriteList) -> TimeSeriesList:
        return self.client.time_series.update(items)

    def delete(self, ids: SequenceNotStr[str]) -> int:
        existing = self.retrieve(ids).as_external_ids()
        if existing:
            self.client.time_series.delete(external_id=existing, ignore_unknown_ids=True)
        return len(existing)

    def iterate(self) -> Iterable[TimeSeries]:
        return iter(self.client.time_series)

    def count(self, ids: str | dict[str, Any] | SequenceNotStr[str | dict[str, Any]] | None) -> int:
        datapoints = cast(
            DatapointsList,
            self.client.time_series.data.retrieve(
                external_id=cast(SequenceNotStr[str], ids),
                start=MIN_TIMESTAMP_MS,
                end=MAX_TIMESTAMP_MS + 1,
                aggregates="count",
                granularity="1000d",
                ignore_unknown_ids=True,
            ),
        )
        return sum(sum(data.count or []) for data in datapoints)

    def drop_data(self, ids: SequenceNotStr[str] | None) -> int:
        count = self.count(ids)
        existing = self.client.time_series.retrieve_multiple(
            external_ids=cast(SequenceNotStr[str], ids), ignore_unknown_ids=True
        ).as_external_ids()
        for external_id in existing:
            self.client.time_series.data.delete_range(
                external_id=external_id, start=MIN_TIMESTAMP_MS, end=MAX_TIMESTAMP_MS + 1
            )
        return count

    @classmethod
    @lru_cache(maxsize=1)
    def get_write_cls_parameter_spec(cls) -> ParameterSpecSet:
        spec = super().get_write_cls_parameter_spec()
        # Added by toolkit
        spec.add(ParameterSpec(("dataSetExternalId",), frozenset({"str"}), is_required=False, _is_nullable=False))

        spec.add(ParameterSpec(("securityCategoryNames",), frozenset({"list"}), is_required=False, _is_nullable=False))

        spec.add(
            ParameterSpec(("securityCategoryNames", ANY_STR), frozenset({"str"}), is_required=False, _is_nullable=False)
        )
        spec.add(ParameterSpec(("assetExternalId",), frozenset({"str"}), is_required=False, _is_nullable=False))
        spec.discard(ParameterSpec(("assetId",), frozenset({"int"}), is_required=False, _is_nullable=False))
        return spec


@final
class DatapointSubscriptionLoader(
    ResourceLoader[
        str,
        DataPointSubscriptionWrite,
        DatapointSubscription,
        DatapointSubscriptionWriteList,
        DatapointSubscriptionList,
    ]
):
    folder_name = "timeseries"
    filename_pattern = r"^.*DatapointSubscription$"  # Matches all yaml files who end with *DatapointSubscription.
    resource_cls = DatapointSubscription
    resource_write_cls = DataPointSubscriptionWrite
    list_cls = DatapointSubscriptionList
    list_write_cls = DatapointSubscriptionWriteList
    kind = "DatapointSubscription"
    _doc_url = "Data-point-subscriptions/operation/postSubscriptions"
    dependencies = frozenset(
        {
            TimeSeriesLoader,
            GroupAllScopedLoader,
        }
    )

    @property
    def display_name(self) -> str:
        return "timeseries.subscription"

    @classmethod
    def get_id(cls, item: DataPointSubscriptionWrite | DatapointSubscription | dict) -> str:
        if isinstance(item, dict):
            return item["externalId"]
        return item.external_id

    @classmethod
    def dump_id(cls, id: str) -> dict[str, Any]:
        return {"externalId": id}

    @classmethod
    @lru_cache(maxsize=1)
    def get_write_cls_parameter_spec(cls) -> ParameterSpecSet:
        spec = super().get_write_cls_parameter_spec()
        # Added by toolkit
        spec.add(ParameterSpec(("dataSetExternalId",), frozenset({"str"}), is_required=False, _is_nullable=False))
        # The Filter class in the SDK class View implementation is deviating from the API.
        # So we need to modify the spec to match the API.
        parameter_path = ("filter",)
        length = len(parameter_path)
        for item in spec:
            if len(item.path) >= length + 1 and item.path[:length] == parameter_path[:length]:
                # Add extra ANY_STR layer
                # The spec class is immutable, so we use this trick to modify it.
                object.__setattr__(item, "path", item.path[:length] + (ANY_STR,) + item.path[length:])
        spec.add(ParameterSpec(("filter", ANY_STR), frozenset({"dict"}), is_required=False, _is_nullable=False))
        return spec

    @classmethod
    def get_dependent_items(cls, item: dict) -> Iterable[tuple[type[ResourceLoader], Hashable]]:
        if "dataSetExternalId" in item:
            yield DataSetsLoader, item["dataSetExternalId"]
        for timeseries_id in item.get("timeSeriesIds", []):
            yield TimeSeriesLoader, timeseries_id

    @classmethod
    def get_required_capability(cls, items: DatapointSubscriptionWriteList) -> Capability | list[Capability]:
        if not items:
            return []
        data_set_ids = {item.data_set_id for item in items if item.data_set_id}
        scope = (
            TimeSeriesSubscriptionsAcl.Scope.DataSet(list(data_set_ids))
            if data_set_ids
            else TimeSeriesSubscriptionsAcl.Scope.All()
        )
        return TimeSeriesSubscriptionsAcl(
            [TimeSeriesSubscriptionsAcl.Action.Read, TimeSeriesSubscriptionsAcl.Action.Write],
            scope,  # type: ignore[arg-type]
        )

    def create(self, items: DatapointSubscriptionWriteList) -> DatapointSubscriptionList:
        created = DatapointSubscriptionList([])
        for item in items:
            created.append(self.client.time_series.subscriptions.create(item))
        return created

    def retrieve(self, ids: SequenceNotStr[str]) -> DatapointSubscriptionList:
        items = DatapointSubscriptionList([])
        for id_ in ids:
            retrieved = self.client.time_series.subscriptions.retrieve(id_)
            if retrieved:
                items.append(retrieved)
        return items

    def update(self, items: DatapointSubscriptionWriteList) -> DatapointSubscriptionList:
        updated = DatapointSubscriptionList([])
        for item in items:
            # Todo update SDK to support taking in Write object
            update = self.client.time_series.subscriptions._update_multiple(
                item,
                list_cls=DatapointSubscriptionWriteList,
                resource_cls=DataPointSubscriptionWrite,
                update_cls=DataPointSubscriptionUpdate,
            )
            updated.append(update)

        return updated

    def delete(self, ids: SequenceNotStr[str]) -> int:
        try:
            self.client.time_series.subscriptions.delete(ids)
        except (CogniteAPIError, CogniteNotFoundError) as e:
            non_existing = set(e.failed or [])
            if existing := [id_ for id_ in ids if id_ not in non_existing]:
                self.client.time_series.subscriptions.delete(existing)
            return len(existing)
        else:
            # All deleted successfully
            return len(ids)

    def iterate(self) -> Iterable[DatapointSubscription]:
        return iter(self.client.time_series.subscriptions)

    def _are_equal(
        self, local: DataPointSubscriptionWrite, cdf_resource: DatapointSubscription, return_dumped: bool = False
    ) -> bool | tuple[bool, dict[str, Any], dict[str, Any]]:
        local_dumped = local.dump()
        cdf_dumped = cdf_resource.as_write().dump()
        # Two subscription objects are equal if they have the same timeSeriesIds
        if "timeSeriesIds" in local_dumped:
            local_dumped["timeSeriesIds"] = set(local_dumped["timeSeriesIds"])
        if "timeSeriesIds" in cdf_dumped:
            local_dumped["timeSeriesIds"] = set(cdf_dumped["timeSeriesIds"])

        return self._return_are_equal(local_dumped, cdf_dumped, return_dumped)
