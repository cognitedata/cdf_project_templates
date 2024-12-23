from __future__ import annotations

import collections.abc
import io
from collections.abc import Hashable, Iterable
from functools import lru_cache
from pathlib import Path
from typing import Any, final

import pandas as pd
from cognite.client.data_classes import (
    Asset,
    AssetList,
    AssetWrite,
    AssetWriteList,
    Event,
    EventList,
    EventWrite,
    EventWriteList,
    Sequence,
    SequenceList,
    SequenceWrite,
    SequenceWriteList,
    capabilities,
)
from cognite.client.data_classes.capabilities import Capability
from cognite.client.exceptions import CogniteAPIError, CogniteNotFoundError
from cognite.client.utils.useful_types import SequenceNotStr

from cognite_toolkit._cdf_tk._parameters import ANY_INT, ParameterSpec, ParameterSpecSet
from cognite_toolkit._cdf_tk.loaders._base_loaders import ResourceLoader
from cognite_toolkit._cdf_tk.utils import load_yaml_inject_variables

from .data_organization_loaders import DataSetsLoader, LabelLoader


@final
class AssetLoader(ResourceLoader[str, AssetWrite, Asset, AssetWriteList, AssetList]):
    folder_name = "classic"
    filename_pattern = r"^.*\.Asset$"  # Matches all yaml files whose stem ends with '.Asset'.
    filetypes = frozenset({"yaml", "yml", "csv", "parquet"})
    resource_cls = Asset
    resource_write_cls = AssetWrite
    list_cls = AssetList
    list_write_cls = AssetWriteList
    kind = "Asset"
    dependencies = frozenset({DataSetsLoader, LabelLoader})
    _doc_url = "Assets/operation/createAssets"

    @property
    def display_name(self) -> str:
        return "assets"

    @classmethod
    def get_id(cls, item: Asset | AssetWrite | dict) -> str:
        if isinstance(item, dict):
            return item["externalId"]
        if not item.external_id:
            raise KeyError("Asset must have external_id")
        return item.external_id

    @classmethod
    def get_internal_id(cls, item: Asset | dict) -> int:
        if isinstance(item, dict):
            return item["id"]
        if not item.id:
            raise KeyError("Asset must have id")
        return item.id

    @classmethod
    def dump_id(cls, id: str) -> dict[str, Any]:
        return {"externalId": id}

    @classmethod
    def get_required_capability(
        cls, items: collections.abc.Sequence[AssetWrite] | None, read_only: bool
    ) -> Capability | list[Capability]:
        if not items and items is not None:
            return []
        scope: capabilities.AssetsAcl.Scope.All | capabilities.AssetsAcl.Scope.DataSet = (  # type: ignore[valid-type]
            capabilities.AssetsAcl.Scope.All()
        )

        actions = (
            [capabilities.AssetsAcl.Action.Read]
            if read_only
            else [capabilities.AssetsAcl.Action.Read, capabilities.AssetsAcl.Action.Write]
        )

        if items:
            if data_set_ids := {item.data_set_id for item in items if item.data_set_id}:
                scope = capabilities.AssetsAcl.Scope.DataSet(list(data_set_ids))

        return capabilities.AssetsAcl(
            actions,
            scope,  # type: ignore[arg-type]
        )

    def create(self, items: AssetWriteList) -> AssetList:
        return self.client.assets.create(items)

    def retrieve(self, ids: SequenceNotStr[str]) -> AssetList:
        return self.client.assets.retrieve_multiple(external_ids=ids, ignore_unknown_ids=True)

    def update(self, items: AssetWriteList) -> AssetList:
        return self.client.assets.update(items, mode="replace")

    def delete(self, ids: SequenceNotStr[str | int]) -> int:
        internal_ids, external_ids = self._split_ids(ids)
        try:
            self.client.assets.delete(id=internal_ids, external_id=external_ids)
        except (CogniteAPIError, CogniteNotFoundError) as e:
            non_existing = set(e.failed or [])
            if existing := [id_ for id_ in ids if id_ not in non_existing]:
                internal_ids, external_ids = self._split_ids(existing)
                self.client.assets.delete(id=internal_ids, external_id=external_ids)
            return len(existing)
        else:
            return len(ids)

    def _iterate(
        self,
        data_set_external_id: str | None = None,
        space: str | None = None,
        parent_ids: list[Hashable] | None = None,
    ) -> Iterable[Asset]:
        return iter(self.client.assets(data_set_external_ids=[data_set_external_id] if data_set_external_id else None))

    @classmethod
    @lru_cache(maxsize=1)
    def get_write_cls_parameter_spec(cls) -> ParameterSpecSet:
        spec = super().get_write_cls_parameter_spec()
        # Added by toolkit
        spec.add(ParameterSpec(("dataSetExternalId",), frozenset({"str"}), is_required=False, _is_nullable=False))
        spec.discard(ParameterSpec(("dataSetId",), frozenset({"int"}), is_required=False, _is_nullable=False))

        # Failed to be inferred from the AssetWrite.__init__ method.
        spec.add(
            ParameterSpec(("labels", ANY_INT, "externalId"), frozenset({"str"}), is_required=True, _is_nullable=True)
        )

        # Should not be used, used for parentExternalId instead
        spec.discard(ParameterSpec(("parentId",), frozenset({"int"}), is_required=False, _is_nullable=False))
        return spec

    @classmethod
    def get_dependent_items(cls, item: dict) -> Iterable[tuple[type[ResourceLoader], Hashable]]:
        """Returns all items that this item requires.

        For example, a TimeSeries requires a DataSet, so this method would return the
        DatasetLoader and identifier of that dataset.
        """
        if "dataSetExternalId" in item:
            yield DataSetsLoader, item["dataSetExternalId"]
        for label in item.get("labels", []):
            if isinstance(label, dict):
                yield LabelLoader, label["externalId"]
            elif isinstance(label, str):
                yield LabelLoader, label
        if "parentExternalId" in item:
            yield cls, item["parentExternalId"]

    def load_resource_file(
        self, filepath: Path, environment_variables: dict[str, str | None] | None = None
    ) -> list[dict[str, Any]]:
        resources: list[dict[str, Any]]
        if filepath.suffix in {".yaml", ".yml"}:
            raw_yaml = load_yaml_inject_variables(
                filepath, environment_variables or {} if self.do_environment_variable_injection else {}
            )
            resources = [raw_yaml] if isinstance(raw_yaml, dict) else raw_yaml
        elif filepath.suffix == ".csv" or filepath.suffix == ".parquet":
            if filepath.suffix == ".csv":
                # The replacement is used to ensure that we read exactly the same file on Windows and Linux
                file_content = filepath.read_bytes().replace(b"\r\n", b"\n").decode("utf-8")
                data = pd.read_csv(io.StringIO(file_content))
            else:
                data = pd.read_parquet(filepath)
            data.replace(pd.NA, None, inplace=True)
            data.replace("", None, inplace=True)
            resources = data.to_dict(orient="records")
        else:
            raise ValueError(f"Unsupported file type: {filepath.suffix}")

        return resources

    def load_resource(self, resource: dict[str, Any], is_dry_run: bool = False) -> AssetWrite:
        # Unpack metadata keys from table formats (e.g. csv, parquet)
        metadata: dict = resource.get("metadata", {})
        for key, value in list(resource.items()):
            if key.startswith("metadata."):
                if value not in {None, float("nan")} and str(value) not in {"", " ", "nan", "null", "none"}:
                    metadata[key.removeprefix("metadata.")] = str(value)
                del resource[key]
        if metadata:
            resource["metadata"] = metadata
        if isinstance(resource.get("labels"), str):
            resource["labels"] = [
                label.strip() for label in resource["labels"].removeprefix("[").removesuffix("]").split(",")
            ]

        if ds_external_id := resource.pop("dataSetExternalId", None):
            resource["dataSetId"] = self.client.lookup.data_sets.id(ds_external_id, is_dry_run)
        return AssetWrite._load(resource)

    def dump_resource(self, resource: Asset, local: dict[str, Any]) -> dict[str, Any]:
        dumped = resource.as_write().dump()
        if data_set_id := dumped.pop("dataSetId", None):
            dumped["dataSetExternalId"] = self.client.lookup.data_sets.external_id(data_set_id)
        if not dumped.get("metadata") and "metadata" not in local:
            dumped.pop("metadata", None)
        return dumped


@final
class SequenceLoader(ResourceLoader[str, SequenceWrite, Sequence, SequenceWriteList, SequenceList]):
    folder_name = "classic"
    filename_pattern = r"^.*\.Sequence$"
    resource_cls = Sequence
    resource_write_cls = SequenceWrite
    list_cls = SequenceList
    list_write_cls = SequenceWriteList
    kind = "Sequence"
    dependencies = frozenset({DataSetsLoader, AssetLoader})
    _doc_url = "Sequences/operation/createSequence"

    @property
    def display_name(self) -> str:
        return "sequences"

    @classmethod
    def get_id(cls, item: Sequence | SequenceWrite | dict) -> str:
        if isinstance(item, dict):
            return item["externalId"]
        if not item.external_id:
            raise KeyError("Sequence must have external_id")
        return item.external_id

    @classmethod
    def get_internal_id(cls, item: Sequence | dict) -> int:
        if isinstance(item, dict):
            return item["id"]
        if not item.id:
            raise KeyError("Sequence must have id")
        return item.id

    @classmethod
    def dump_id(cls, id: str) -> dict[str, Any]:
        return {"externalId": id}

    @classmethod
    def get_required_capability(
        cls, items: collections.abc.Sequence[SequenceWrite] | None, read_only: bool
    ) -> Capability | list[Capability]:
        if not items and items is not None:
            return []
        scope: Any = capabilities.SequencesAcl.Scope.All()
        if items:
            if data_set_ids := {item.data_set_id for item in items if item.data_set_id}:
                scope = capabilities.SequencesAcl.Scope.DataSet(list(data_set_ids))

        actions = (
            [capabilities.SequencesAcl.Action.Read]
            if read_only
            else [capabilities.SequencesAcl.Action.Read, capabilities.SequencesAcl.Action.Write]
        )

        return capabilities.SequencesAcl(
            actions,
            scope,  # type: ignore[arg-type]
        )

    def load_resource(self, resource: dict[str, Any], is_dry_run: bool = False) -> SequenceWrite:
        if ds_external_id := resource.pop("dataSetExternalId", None):
            resource["dataSetId"] = self.client.lookup.data_sets.id(ds_external_id, is_dry_run)
        return SequenceWrite._load(resource)

    def dump_resource(self, resource: Sequence, local: dict[str, Any]) -> dict[str, Any]:
        dumped = resource.as_write().dump()
        if data_set_id := dumped.pop("dataSetId", None):
            dumped["dataSetExternalId"] = self.client.lookup.data_sets.external_id(data_set_id)
        if not dumped.get("metadata") and "metadata" not in local:
            dumped.pop("metadata", None)
        return dumped

    def create(self, items: SequenceWriteList) -> SequenceList:
        return self.client.sequences.create(items)

    def retrieve(self, ids: SequenceNotStr[str]) -> SequenceList:
        return self.client.sequences.retrieve_multiple(external_ids=ids, ignore_unknown_ids=True)

    def update(self, items: SequenceWriteList) -> SequenceList:
        return self.client.sequences.upsert(items, mode="replace")

    def delete(self, ids: SequenceNotStr[str | int]) -> int:
        internal_ids, external_ids = self._split_ids(ids)
        try:
            self.client.sequences.delete(id=internal_ids, external_id=external_ids)
        except (CogniteAPIError, CogniteNotFoundError) as e:
            non_existing = set(e.failed or [])
            if existing := [id_ for id_ in ids if id_ not in non_existing]:
                internal_ids, external_ids = self._split_ids(existing)
                self.client.sequences.delete(id=internal_ids, external_id=external_ids)
            return len(existing)
        else:
            return len(ids)

    def _iterate(
        self,
        data_set_external_id: str | None = None,
        space: str | None = None,
        parent_ids: list[Hashable] | None = None,
    ) -> Iterable[Sequence]:
        return iter(
            self.client.sequences(data_set_external_ids=[data_set_external_id] if data_set_external_id else None)
        )

    @classmethod
    @lru_cache(maxsize=1)
    def get_write_cls_parameter_spec(cls) -> ParameterSpecSet:
        spec = super().get_write_cls_parameter_spec()
        # Added by toolkit
        spec.add(ParameterSpec(("dataSetExternalId",), frozenset({"str"}), is_required=False, _is_nullable=False))
        spec.discard(ParameterSpec(("dataSetId",), frozenset({"int"}), is_required=False, _is_nullable=False))
        spec.add(ParameterSpec(("assetExternalId",), frozenset({"int"}), is_required=False, _is_nullable=False))
        spec.discard(ParameterSpec(("assetId",), frozenset({"int"}), is_required=False, _is_nullable=False))
        return spec

    @classmethod
    def get_dependent_items(cls, item: dict) -> Iterable[tuple[type[ResourceLoader], Hashable]]:
        if "dataSetExternalId" in item:
            yield DataSetsLoader, item["dataSetExternalId"]
        if "assetExternalId" in item:
            yield AssetLoader, item["assetExternalId"]


@final
class EventLoader(ResourceLoader[str, EventWrite, Event, EventWriteList, EventList]):
    folder_name = "classic"
    filename_pattern = r"^.*\.Event$"  # Matches all yaml files whose stem ends with '.Event'.
    filetypes = frozenset({"yaml", "yml"})
    resource_cls = Event
    resource_write_cls = EventWrite
    list_cls = EventList
    list_write_cls = EventWriteList
    kind = "Event"
    dependencies = frozenset({DataSetsLoader, AssetLoader})
    _doc_url = "Events/operation/createEvents"

    @property
    def display_name(self) -> str:
        return "events"

    @classmethod
    def get_id(cls, item: Event | EventWrite | dict) -> str:
        if isinstance(item, dict):
            return item["externalId"]
        if not item.external_id:
            raise KeyError("Event must have external_id")
        return item.external_id

    @classmethod
    def get_internal_id(cls, item: Event | dict) -> int:
        if isinstance(item, dict):
            return item["id"]
        if not item.id:
            raise KeyError("Event must have id")
        return item.id

    @classmethod
    def dump_id(cls, id: str) -> dict[str, Any]:
        return {"externalId": id}

    @classmethod
    def get_required_capability(
        cls, items: collections.abc.Sequence[EventWrite] | None, read_only: bool
    ) -> Capability | list[Capability]:
        if not items and items is not None:
            return []
        scope: capabilities.EventsAcl.Scope.All | capabilities.EventsAcl.Scope.DataSet = (  # type: ignore[valid-type]
            capabilities.EventsAcl.Scope.All()
        )

        actions = (
            [capabilities.EventsAcl.Action.Read]
            if read_only
            else [capabilities.EventsAcl.Action.Read, capabilities.EventsAcl.Action.Write]
        )

        if items:
            if data_set_ids := {item.data_set_id for item in items if item.data_set_id}:
                scope = capabilities.EventsAcl.Scope.DataSet(list(data_set_ids))

        return capabilities.EventsAcl(
            actions,
            scope,  # type: ignore[arg-type]
        )

    def create(self, items: EventWriteList) -> EventList:
        return self.client.events.create(items)

    def retrieve(self, ids: SequenceNotStr[str]) -> EventList:
        return self.client.events.retrieve_multiple(external_ids=ids, ignore_unknown_ids=True)

    def update(self, items: EventWriteList) -> EventList:
        return self.client.events.update(items, mode="replace")

    def delete(self, ids: SequenceNotStr[str | int]) -> int:
        internal_ids, external_ids = self._split_ids(ids)
        try:
            self.client.events.delete(id=internal_ids, external_id=external_ids)
        except (CogniteAPIError, CogniteNotFoundError) as e:
            non_existing = set(e.failed or [])
            if existing := [id_ for id_ in ids if id_ not in non_existing]:
                internal_ids, external_ids = self._split_ids(existing)
                self.client.events.delete(id=internal_ids, external_id=external_ids)
            return len(existing)
        else:
            return len(ids)

    def _iterate(
        self,
        data_set_external_id: str | None = None,
        space: str | None = None,
        parent_ids: list[Hashable] | None = None,
    ) -> Iterable[Event]:
        return iter(self.client.events(data_set_external_ids=[data_set_external_id] if data_set_external_id else None))

    @classmethod
    @lru_cache(maxsize=1)
    def get_write_cls_parameter_spec(cls) -> ParameterSpecSet:
        spec = super().get_write_cls_parameter_spec()
        # Added by toolkit
        spec.add(ParameterSpec(("dataSetExternalId",), frozenset({"str"}), is_required=False, _is_nullable=False))
        spec.discard(ParameterSpec(("dataSetId",), frozenset({"int"}), is_required=False, _is_nullable=False))

        spec.add(ParameterSpec(("assetExternalIds",), frozenset({"list"}), is_required=False, _is_nullable=False))
        spec.add(
            ParameterSpec(
                ("assetExternalIds", ANY_INT, "externalId"), frozenset({"str"}), is_required=False, _is_nullable=False
            )
        )
        spec.discard(ParameterSpec(("assetIds",), frozenset({"int"}), is_required=False, _is_nullable=False))
        spec.discard(ParameterSpec(("assetIds", ANY_INT), frozenset({"int"}), is_required=False, _is_nullable=False))
        return spec

    @classmethod
    def get_dependent_items(cls, item: dict) -> Iterable[tuple[type[ResourceLoader], Hashable]]:
        """Returns all items that this item requires.

        For example, a TimeSeries requires a DataSet, so this method would return the
        DatasetLoader and identifier of that dataset.
        """
        if "dataSetExternalId" in item:
            yield DataSetsLoader, item["dataSetExternalId"]
        for asset_id in item.get("assetExternalIds", []):
            if isinstance(asset_id, str):
                yield AssetLoader, asset_id

    def load_resource(self, resource: dict[str, Any], is_dry_run: bool = False) -> EventWrite:
        if ds_external_id := resource.get("dataSetExternalId", None):
            resource["dataSetId"] = self.client.lookup.data_sets.id(ds_external_id, is_dry_run)
        if asset_external_ids := resource.pop("assetExternalIds", []):
            resource["assetIds"] = self.client.lookup.assets.id(asset_external_ids, is_dry_run)
        return EventWrite._load(resource)

    def dump_resource(self, resource: Event, local: dict[str, Any]) -> dict[str, Any]:
        dumped = resource.as_write().dump()
        if data_set_id := dumped.pop("dataSetId", None):
            dumped["dataSetExternalId"] = self.client.lookup.data_sets.external_id(data_set_id)
        if asset_ids := dumped.pop("assetIds", None):
            dumped["assetExternalIds"] = self.client.lookup.assets.external_id(asset_ids)
        if not dumped.get("metadata") and "metadata" not in local:
            dumped.pop("metadata", None)
        return dumped
