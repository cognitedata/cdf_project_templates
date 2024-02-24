from __future__ import annotations

import abc
import hashlib
import itertools
import json as JSON
from collections import defaultdict
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, BinaryIO, Callable, TextIO, cast
from unittest.mock import MagicMock

import pandas as pd
from cognite.client import CogniteClient
from cognite.client._api.iam import IAMAPI
from cognite.client.data_classes import (
    Database,
    ExtractionPipelineConfig,
    ExtractionPipelineConfigWrite,
    FileMetadata,
    Function,
    FunctionCall,
    FunctionWrite,
    Group,
    GroupList,
    capabilities,
)
from cognite.client.data_classes._base import CogniteResource, T_CogniteResource
from cognite.client.data_classes.capabilities import AllProjectsScope, ProjectCapability, ProjectCapabilityList
from cognite.client.data_classes.data_modeling import (
    EdgeApply,
    EdgeApplyResultList,
    EdgeId,
    InstancesApplyResult,
    InstancesDeleteResult,
    NodeApply,
    NodeApplyResult,
    NodeApplyResultList,
    NodeId,
    VersionedDataModelingId,
    View,
)
from cognite.client.data_classes.data_modeling.ids import InstanceId
from cognite.client.data_classes.functions import FunctionsStatus
from cognite.client.data_classes.iam import ProjectSpec, TokenInspection
from cognite.client.testing import CogniteClientMock
from cognite.client.utils._text import to_camel_case
from requests import Response

from .config import API_RESOURCES
from .data_classes import APIResource, AuthGroupCalls

TEST_FOLDER = Path(__file__).resolve().parent.parent

_ALL_CAPABILITIES = []
_to_check = list(capabilities.Capability.__subclasses__())
while _to_check:
    capability_cls = _to_check.pop()
    _to_check.extend(capability_cls.__subclasses__())
    if abc.ABC in capability_cls.__bases__:
        continue
    actions = list(capability_cls.Action.__members__.values())
    scopes = [var_ for name, var_ in vars(capability_cls.Scope).items() if not name.startswith("_")]
    for action, scope in itertools.product(actions, scopes):
        try:
            _ALL_CAPABILITIES.append(capability_cls([action], scope()))
        except TypeError:
            # Skipping all scopes that require arguments
            ...
del _to_check, capability_cls, actions, scopes, action, scope


class ApprovalCogniteClient:
    """A mock CogniteClient that is used for testing the clean, deploy commands
    of the cognite-toolkit.

    Args:
        mock_client: The mock client to use.

    """

    def __init__(self, mock_client: CogniteClientMock):
        self.mock_client = mock_client
        # This is used to simulate the existing resources in CDF
        self._existing_resources: dict[str, list[CogniteResource]] = defaultdict(list)
        # This is used to log all delete operations
        self._deleted_resources: dict[str, list[str | int | dict[str, Any]]] = defaultdict(list)
        # This is used to log all create operations
        self._created_resources: dict[str, list[CogniteResource | dict[str, Any]]] = defaultdict(list)

        # This is used to log all operations
        self._delete_methods: dict[str, list[MagicMock]] = defaultdict(list)
        self._create_methods: dict[str, list[MagicMock]] = defaultdict(list)
        self._retrieve_methods: dict[str, list[MagicMock]] = defaultdict(list)
        self._inspect_methods: dict[str, list[MagicMock]] = defaultdict(list)
        self._post_methods: dict[str, list[MagicMock]] = defaultdict(list)

        # Set the side effect of the MagicMock to the real method
        self.mock_client.iam.compare_capabilities.side_effect = IAMAPI.compare_capabilities
        # Set functions to be activated
        self.mock_client.functions.status.return_value = FunctionsStatus(status="activated")
        # Activate authorization_header()
        self.mock_client.config.credentials.authorization_header.return_value = ("Bearer", "123")
        # Set project
        self.mock_client.config.project = "test_project"
        self.mock_client.config.base_url = "https://bluefield.cognitedata.com"

        # Setup all mock methods
        for resource in API_RESOURCES:
            parts = resource.api_name.split(".")
            mock_api = mock_client
            for part in parts:
                if not hasattr(mock_api, part):
                    raise ValueError(f"Invalid api name {resource.api_name}, could not find {part}")
                # To avoid registering the side effect on the mock_client.post.post and use
                # just mock_client.post instead, we need to skip the "step into" post mock here.
                if part != "post":
                    mock_api = getattr(mock_api, part)
            for method_type, methods in resource.methods.items():
                method_factory: Callable = {
                    "create": self._create_create_method,
                    "delete": self._create_delete_method,
                    "retrieve": self._create_retrieve_method,
                    "inspect": self._create_inspect_method,
                    "post": self._create_post_method,
                }[method_type]
                method_dict = {
                    "create": self._create_methods,
                    "delete": self._delete_methods,
                    "retrieve": self._retrieve_methods,
                    "inspect": self._inspect_methods,
                    "post": self._post_methods,
                }[method_type]
                for mock_method in methods:
                    if not hasattr(mock_api, mock_method.api_class_method):
                        raise ValueError(
                            f"Invalid api method {mock_method.api_class_method} for resource {resource.api_name}"
                        )
                    method = getattr(mock_api, mock_method.api_class_method)
                    method.side_effect = method_factory(resource, mock_method.mock_name, mock_client)
                    method_dict[resource.resource_cls.__name__].append(method)

    @property
    def client(self) -> CogniteClient:
        """Returns a mock CogniteClient"""
        return cast(CogniteClient, self.mock_client)

    def append(self, resource_cls: type[CogniteResource], items: CogniteResource | Sequence[CogniteResource]) -> None:
        """This is used to simulate existing resources in CDF.

        Args:
            resource_cls: The type of resource this is.
            items: The list of resources to append.

        """
        if isinstance(items, Sequence):
            self._existing_resources[resource_cls.__name__].extend(items)
        else:
            self._existing_resources[resource_cls.__name__].append(items)

    def _create_delete_method(self, resource: APIResource, mock_method: str, client: CogniteClient) -> Callable:
        deleted_resources = self._deleted_resources
        resource_cls = resource.resource_cls

        def delete_id_external_id(
            id: int | Sequence[int] | None = None,
            external_id: str | Sequence[str] | None = None,
            **_,
        ) -> list:
            deleted = []
            if not isinstance(id, str) and isinstance(id, Sequence):
                deleted.extend({"id": i} for i in id)
            elif isinstance(id, int):
                deleted.append({"id": id})
            if isinstance(external_id, str):
                deleted.append({"externalId": external_id})
            elif isinstance(external_id, Sequence):
                deleted.extend({"externalId": i} for i in external_id)
            if deleted:
                deleted_resources[resource_cls.__name__].extend(deleted)
            return deleted

        def delete_data_modeling(ids: VersionedDataModelingId | Sequence[VersionedDataModelingId]) -> list:
            deleted = []
            if isinstance(ids, (VersionedDataModelingId, InstanceId)):
                deleted.append(ids.dump(camel_case=True))
            elif isinstance(ids, Sequence):
                deleted.extend([id.dump(camel_case=True) for id in ids])
            if deleted:
                deleted_resources[resource_cls.__name__].extend(deleted)
            return deleted

        def delete_instances(
            nodes: NodeId | Sequence[NodeId] | tuple[str, str] | Sequence[tuple[str, str]] | None = None,
            edges: EdgeId | Sequence[EdgeId] | tuple[str, str] | Sequence[tuple[str, str]] | None = None,
        ) -> InstancesDeleteResult:
            deleted = []
            if isinstance(nodes, NodeId):
                deleted.append(nodes.dump(camel_case=True, include_instance_type=True))
            elif isinstance(nodes, tuple):
                deleted.append(NodeId(*nodes).dump(camel_case=True, include_instance_type=True))
            elif isinstance(edges, EdgeId):
                deleted.append(edges.dump(camel_case=True, include_instance_type=True))
            elif isinstance(edges, tuple):
                deleted.append(EdgeId(*edges).dump(camel_case=True, include_instance_type=True))
            elif isinstance(nodes, Sequence):
                deleted.extend(
                    [
                        node.dump(camel_case=True, include_instance_type=True) if isinstance(node, NodeId) else node
                        for node in nodes
                    ]
                )
            elif isinstance(edges, Sequence):
                deleted.extend(
                    [
                        edge.dump(camel_case=True, include_instance_type=True) if isinstance(edge, EdgeId) else edge
                        for edge in edges
                    ]
                )

            if deleted:
                deleted_resources[resource_cls.__name__].extend(deleted)

            if nodes:
                return InstancesDeleteResult(nodes=deleted, edges=[])
            elif edges:
                return InstancesDeleteResult(nodes=[], edges=deleted)
            else:
                return InstancesDeleteResult(nodes=[], edges=[])

        def delete_space(spaces: str | Sequence[str]) -> list:
            deleted = []
            if isinstance(spaces, str):
                deleted.append(spaces)
            elif isinstance(spaces, Sequence):
                deleted.extend(spaces)
            if deleted:
                deleted_resources[resource_cls.__name__].extend(deleted)
            return deleted

        def delete_raw(db_name: str | Sequence[str], name: str | Sequence[str] | None = None) -> list:
            if name:
                deleted = [{"db_name": db_name, "name": name if isinstance(name, str) else sorted(name)}]
            else:
                deleted = [{"db_name": name} for name in (db_name if isinstance(db_name, Sequence) else [db_name])]
            deleted_resources[resource_cls.__name__].extend(deleted)
            return deleted

        available_delete_methods = {
            fn.__name__: fn
            for fn in [
                delete_id_external_id,
                delete_instances,
                delete_raw,
                delete_data_modeling,
                delete_space,
            ]
        }
        if mock_method not in available_delete_methods:
            raise ValueError(
                f"Invalid mock delete method {mock_method} for resource {resource_cls.__name__}. "
                f"Supported {list(available_delete_methods)}"
            )

        method = available_delete_methods[mock_method]
        return method

    def _create_create_method(self, resource: APIResource, mock_method: str, client: CogniteClient) -> Callable:
        created_resources = self._created_resources
        write_resource_cls = resource.write_cls
        write_list_cls = resource.write_list_cls
        resource_cls = resource.resource_cls
        resource_list_cls = resource.list_cls

        def create(*args, **kwargs) -> Any:
            created = []
            for value in itertools.chain(args, kwargs.values()):
                if isinstance(value, write_resource_cls):
                    created.append(value)
                elif isinstance(value, Sequence) and all(isinstance(v, write_resource_cls) for v in value):
                    created.extend(value)
                elif isinstance(value, str) and issubclass(write_resource_cls, Database):
                    created.append(Database(name=value))
            created_resources[resource_cls.__name__].extend(created)
            if resource_cls is View:
                return write_list_cls(created)
            if resource_cls is ExtractionPipelineConfig:
                print("stop")
            return resource_list_cls.load(
                [
                    {
                        "isGlobal": False,
                        "lastUpdatedTime": 0,
                        "createdTime": 0,
                        "writable": True,
                        "ignoreNullFields": False,
                        "usedFor": "nodes",
                        **c.dump(camel_case=True),
                    }
                    for c in created
                ],
                cognite_client=client,
            )

        def insert_dataframe(*args, **kwargs) -> None:
            args = list(args)
            kwargs = dict(kwargs)
            dataframe_hash = ""
            dataframe_cols = []
            for arg in list(args):
                if isinstance(arg, pd.DataFrame):
                    args.remove(arg)
                    dataframe_hash = int(
                        hashlib.sha256(
                            pd.util.hash_pandas_object(arg, index=False, encoding="utf-8").values
                        ).hexdigest(),
                        16,
                    )
                    dataframe_cols = list(arg.columns)
                    break

            for key in list(kwargs):
                if isinstance(kwargs[key], pd.DataFrame):
                    value = kwargs.pop(key)
                    dataframe_hash = int(
                        hashlib.sha256(
                            pd.util.hash_pandas_object(value, index=False, encoding="utf-8").values
                        ).hexdigest(),
                        16,
                    )
                    dataframe_cols = list(value.columns)
                    break
            if not dataframe_hash:
                raise ValueError("No dataframe found in arguments")
            name = "_".join([str(arg) for arg in itertools.chain(args, kwargs.values())])
            if not name:
                name = "_".join(dataframe_cols)
            created_resources[resource_cls.__name__].append(
                {
                    "name": name,
                    "args": args,
                    "kwargs": kwargs,
                    "dataframe": dataframe_hash,
                    "columns": dataframe_cols,
                }
            )

        def upload(*args, **kwargs) -> None:
            name = ""
            for k, v in kwargs.items():
                if isinstance(v, Path) or (isinstance(v, str) and Path(v).exists()):
                    kwargs[k] = "/".join(Path(v).relative_to(TEST_FOLDER).parts)
                    name = Path(v).name

            created_resources[resource_cls.__name__].append(
                {
                    "name": name,
                    "args": list(args),
                    "kwargs": dict(kwargs),
                }
            )

        def create_instances(
            nodes: NodeApply | Sequence[NodeApply] | None = None,
            edges: EdgeApply | Sequence[EdgeApply] | None = None,
            **kwargs,
        ) -> InstancesApplyResult:
            created = []
            if isinstance(nodes, NodeApply):
                created.append(nodes)
            elif isinstance(nodes, Sequence) and all(isinstance(v, NodeApply) for v in nodes):
                created.extend(nodes)
            if edges is not None:
                raise NotImplementedError("Edges not supported yet")
            created_resources[resource_cls.__name__].extend(created)
            return InstancesApplyResult(
                nodes=NodeApplyResultList(
                    [
                        NodeApplyResult(
                            space=node.space,
                            external_id=node.external_id,
                            version=node.existing_version or 1,
                            was_modified=True,
                            last_updated_time=1,
                            created_time=1,
                        )
                        for node in (nodes if isinstance(nodes, Sequence) else [nodes])
                    ]
                ),
                edges=EdgeApplyResultList([]),
            )

        def create_extraction_pipeline_config(config: ExtractionPipelineConfigWrite) -> ExtractionPipelineConfig:
            created_resources[resource_cls.__name__].append(config)
            return ExtractionPipelineConfig.load(config.dump(camel_case=True))

        def upload_bytes_files_api(content: str | bytes | TextIO | BinaryIO, **kwargs) -> FileMetadata:
            if not isinstance(content, bytes):
                raise NotImplementedError("Only bytes content is supported")

            created_resources[resource_cls.__name__].append(
                {
                    **kwargs,
                }
            )
            return FileMetadata.load({to_camel_case(k): v for k, v in kwargs.items()})

        def create_function_api(**kwargs) -> Function:
            # Function API does not follow the same pattern as the other APIs
            # So needs special handling
            created = FunctionWrite.load({to_camel_case(k): v for k, v in kwargs.items()})
            created_resources[resource_cls.__name__].append(created)
            return Function.load(created.dump(camel_case=True))

        available_create_methods = {
            fn.__name__: fn
            for fn in [
                create,
                insert_dataframe,
                upload,
                create_instances,
                create_extraction_pipeline_config,
                upload_bytes_files_api,
                create_function_api,
            ]
        }
        if mock_method not in available_create_methods:
            raise ValueError(
                f"Invalid mock create method {mock_method} for resource {resource_cls.__name__}. Supported {list(available_create_methods.keys())}"
            )
        method = available_create_methods[mock_method]
        return method

    def _create_retrieve_method(self, resource: APIResource, mock_method: str, client: CogniteClient) -> Callable:
        existing_resources = self._existing_resources
        resource_cls = resource.resource_cls
        read_list_cls = resource.list_cls

        def return_values(*args, **kwargs):
            return read_list_cls(existing_resources[resource_cls.__name__], cognite_client=client)

        def return_value(*args, **kwargs):
            if value := existing_resources[resource_cls.__name__]:
                return read_list_cls(value, cognite_client=client)[0]
            else:
                return None

        def data_model_retrieve(ids, *args, **kwargs):
            id_list = list(ids) if isinstance(ids, Sequence) else [ids]
            to_return = read_list_cls([], cognite_client=client)
            for resource in existing_resources[resource_cls.__name__]:
                if resource.as_id() in id_list:
                    to_return.append(resource)
            return to_return

        available_retrieve_methods = {
            fn.__name__: fn
            for fn in [
                return_values,
                return_value,
                data_model_retrieve,
            ]
        }
        if mock_method not in available_retrieve_methods:
            raise ValueError(
                f"Invalid mock retrieve method {mock_method} for resource {resource_cls.__name__}. Supported {available_retrieve_methods.keys()}"
            )
        method = available_retrieve_methods[mock_method]
        return method

    def _create_inspect_method(self, resource: APIResource, mock_method: str, client: CogniteClient) -> Callable:
        existing_resources = self._existing_resources
        resource_cls = resource.resource_cls

        def return_value(*args, **kwargs):
            if value := existing_resources[resource_cls.__name__]:
                return value[0]

            return TokenInspection(
                subject="test",
                projects=[ProjectSpec(url_name="test_project", groups=[123, 456])],
                capabilities=ProjectCapabilityList(
                    [
                        ProjectCapability(capability=capability, project_scope=AllProjectsScope())
                        for capability in _ALL_CAPABILITIES
                    ],
                    cognite_client=client,
                ),
            )

        available_inspect_methods = {
            fn.__name__: fn
            for fn in [
                return_value,
            ]
        }
        if mock_method not in available_inspect_methods:
            raise ValueError(
                f"Invalid mock retrieve method {mock_method} for resource {resource_cls.__name__}. Supported {available_inspect_methods.keys()}"
            )
        method = available_inspect_methods[mock_method]
        return method

    def _create_post_method(self, resource: APIResource, mock_method: str, client: CogniteClient) -> Callable:
        def post_method(
            url: str, json: dict[str, Any], params: dict[str, Any] | None = None, headers: dict[str, Any] | None = None
        ) -> Response:
            sessionResponse = Response()
            if url.endswith("/sessions"):
                sessionResponse.status_code = 200
                sessionResponse._content = b'{"items":[{"id":5192234284402249,"nonce":"QhlCnImCBwBNc72N","status":"READY","type":"ONESHOT_TOKEN_EXCHANGE"}]}'
            elif url.endswith("/functions/schedules"):
                sessionResponse.status_code = 201
                sessionResponse._content = str.encode(JSON.dumps(json))
            elif url.split("/")[-3] == "functions" and url.split("/")[-2].isdigit() and url.endswith("call"):
                sessionResponse.status_code = 201
                sessionResponse._content = str.encode(
                    JSON.dumps(FunctionCall(id=1, status="RUNNING").dump(camel_case=True))
                )
            else:
                raise ValueError(
                    f"The url {url} is called with post method, but not mocked. Please add in _create_post_method in approval.client.py"
                )
            return sessionResponse

        existing_resources = self._existing_resources
        resource_cls = resource.resource_cls

        def return_value(*args, **kwargs):
            return existing_resources[resource_cls.__name__][0]

        available_post_methods = {
            fn.__name__: fn
            for fn in [
                return_value,
                post_method,
            ]
        }
        if mock_method not in available_post_methods:
            raise ValueError(
                f"Invalid mock retrieve method {mock_method} for resource {resource_cls.__name__}. Supported {available_post_methods.keys()}"
            )
        method = available_post_methods[mock_method]
        return method

    def dump(self, sort: bool = True) -> dict[str, Any]:
        """This returns a dictionary with all the resources that have been created and deleted.

        The sorting is useful in snapshot testing, as it makes for a consistent output. If you want to check the order
        that the resources were created, you can set sort=False.

        Args:
            sort: If True, the resources will be sorted by externalId, dbName, name, or name[0] if externalId is not available.


        Returns:
            A dict with the resources that have been created and deleted, {resource_name: [resource, ...]}
        """
        dumped = {}
        if sort:
            created_resources = sorted(self._created_resources)
        else:
            created_resources = list(self._created_resources)
        for key in created_resources:
            values = self._created_resources[key]
            if values:
                dumped_resource = (value.dump(camel_case=True) if hasattr(value, "dump") else value for value in values)
                if sort:
                    dumped[key] = sorted(
                        dumped_resource,
                        key=lambda x: x.get("externalId", x.get("dbName", x.get("db_name", x.get("name")))),
                    )
                else:
                    dumped[key] = list(dumped_resource)

        if self._deleted_resources:
            dumped["deleted"] = {}
            if sort:
                deleted_resources = sorted(self._deleted_resources)
            else:
                deleted_resources = list(self._deleted_resources)

            for key in deleted_resources:
                values = self._deleted_resources[key]

                def sort_deleted(x):
                    if not isinstance(x, dict):
                        return x
                    if "externalId" in x:
                        return x["externalId"]
                    if "db_name" in x and "name" in x and isinstance(x["name"], list):
                        return x["db_name"] + "/" + x["name"][0]
                    if "db_name" in x:
                        return x["db_name"]
                    return "missing"

                if values:
                    dumped["deleted"][key] = (
                        sorted(
                            values,
                            key=sort_deleted,
                        )
                        if sort
                        else list(values)
                    )

        return dumped

    def created_resources_of_type(self, resource_type: type[T_CogniteResource]) -> list[T_CogniteResource]:
        """This returns all the resources that have been created of a specific type.

        Args:
            resource_type: The type of resource to return, for example, 'TimeSeries', 'DataSet', 'Transformation'

        Returns:
            A list of all the resources that have been created of a specific type.
        """
        return self._created_resources.get(resource_type.__name__, [])

    def create_calls(self) -> dict[str, int]:
        """This returns all the calls that have been made to the mock client to create methods.

        For example, if you have mocked the 'time_series' API, and the code you test calls the 'time_series.create' method,
        then this method will return {'time_series': 1}
        """
        return {
            key: call_count
            for key, methods in self._create_methods.items()
            if (call_count := sum(method.call_count for method in methods))
        }

    def retrieve_calls(self) -> dict[str, int]:
        """This returns all the calls that have been made to the mock client to retrieve methods.

        For example, if you have mocked the 'time_series' API, and the code you test calls the 'time_series.list' method,
        then this method will return {'time_series': 1}
        """
        return {
            key: call_count
            for key, methods in self._retrieve_methods.items()
            if (call_count := sum(method.call_count for method in methods))
        }

    def inspect_calls(self) -> dict[str, int]:
        """This returns all the calls that have been made to the mock client to the inspect method."""
        return {
            key: call_count
            for key, methods in self._inspect_methods.items()
            if (call_count := sum(method.call_count for method in methods))
        }

    def delete_calls(self) -> dict[str, int]:
        """This returns all the calls that have been made to the mock client to delete methods.

        For example, if you have mocked the 'time_series' API, and the code you test calls the 'time_series.delete' method,
        then this method will return {'time_series': 1}
        """
        return {
            key: call_count
            for key, methods in self._delete_methods.items()
            if (call_count := sum(method.call_count for method in methods))
        }

    def not_mocked_calls(self) -> dict[str, int]:
        """This returns all the calls that have been made to the mock client to sub APIs that have not been mocked.

        For example, if you have not mocked the 'time_series' API, and the code you test calls the 'time_series.list' method,
        then this method will return {'time_series.list': 1}

        Returns:
            A dict with the calls that have been made to sub APIs that have not been mocked, {api_name.method_name: call_count}
        """
        mocked_apis: dict[str : set[str]] = defaultdict(set)
        for r in API_RESOURCES:
            if r.api_name.count(".") == 1:
                api_name, sub_api = r.api_name.split(".")
            elif r.api_name.count(".") == 0:
                api_name, sub_api = r.api_name, ""
            else:
                raise ValueError(f"Invalid api name {r.api_name}")
            mocked_apis[api_name] |= {sub_api} if sub_api else set()

        not_mocked: dict[str, int] = defaultdict(int)
        for api_name, api in vars(self.mock_client).items():
            if not isinstance(api, MagicMock) or api_name.startswith("_") or api_name.startswith("assert_"):
                continue
            mocked_sub_apis = mocked_apis.get(api_name, set())
            for method_name in dir(api):
                if method_name.startswith("_") or method_name.startswith("assert_"):
                    continue
                method = getattr(api, method_name)
                if api_name not in mocked_apis and isinstance(method, MagicMock) and method.call_count:
                    not_mocked[f"{api_name}.{method_name}"] += method.call_count
                if hasattr(method, "_spec_set") and method._spec_set and method_name not in mocked_sub_apis:
                    # this is a sub api that must be checked
                    for sub_method_name in dir(method):
                        if sub_method_name.startswith("_") or sub_method_name.startswith("assert_"):
                            continue
                        sub_method = getattr(method, sub_method_name)
                        if isinstance(sub_method, MagicMock) and sub_method.call_count:
                            not_mocked[f"{api_name}.{method_name}.{sub_method_name}"] += sub_method.call_count
        return dict(not_mocked)

    def auth_create_group_calls(self) -> Iterable[AuthGroupCalls]:
        groups = cast(GroupList, self._created_resources[Group.__name__])
        groups = sorted(groups, key=lambda x: x.name)
        for name, group in itertools.groupby(groups, key=lambda x: x.name):
            yield AuthGroupCalls(name=name, calls=list(group))
