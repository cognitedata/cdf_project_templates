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

import collections
import importlib
import inspect
import json
import logging
import os
import re
import typing
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from functools import total_ordering
from pathlib import Path
from typing import Any, get_origin, get_type_hints

import yaml
from cognite.client import ClientConfig, CogniteClient
from cognite.client.config import global_config
from cognite.client.credentials import OAuthClientCredentials, Token
from cognite.client.data_classes._base import CogniteObject
from cognite.client.data_classes.capabilities import Capability
from cognite.client.exceptions import CogniteAPIError, CogniteAuthError
from rich import print

logger = logging.getLogger(__name__)


class CDFToolConfig:
    """Configurations for how to store data in CDF

    Properties:
        client: active CogniteClient
    Functions:
        verify_client: verify that the client has correct credentials and specified access capabilities
        verify_dataset: verify that the data set exists and that the client has access to it

    """

    def __init__(
        self,
        client_name: str = "Generic Cognite config deploy tool",
        token: str | None = None,
        cluster: str | None = None,
        project: str | None = None,
    ) -> None:
        self._data_set_id: int = 0
        self._data_set = None
        self._failed = False
        self._environ = {}
        self._data_set_id_by_external_id: dict[str, id] = {}
        self.oauth_credentials = OAuthClientCredentials(
            token_url="",
            client_id="",
            client_secret="",
            scopes=[],
        )

        # CDF_CLUSTER and CDF_PROJECT are minimum requirements and can be overridden
        # when instansiating the class.
        if cluster is not None and len(cluster) > 0:
            self._cluster = cluster
            self._environ["CDF_CLUSTER"] = cluster
        if project is not None and len(project) > 0:
            self._project = project
            self._environ["CDF_PROJECT"] = project
        if token is not None:
            self._environ["CDF_TOKEN"] = token
        if (
            self.environ("CDF_URL", default=None, fail=False) is None
            and self.environ("CDF_CLUSTER", default=None, fail=False) is None
        ):
            # If CDF_URL and CDF_CLUSTER are not set, we may be in a Jupyter notebook in Fusion,
            # and credentials are preset to logged in user (no env vars are set!).
            try:
                self._client = CogniteClient()
            except Exception:
                print(
                    "[bold yellow]WARNING[/] Not able to successfully configure a Cognite client. Requirements: CDF_CLUSTER and CDF_PROJECT environment variables or CDF_TOKEN to a valid OAuth2 token."
                )
            return

        # CDF_CLUSTER and CDF_PROJECT are minimum requirements to know where to connect.
        # Above they were forced default to None and fail was False, here we
        # will fail with an exception if they are not set.
        self._cluster = self.environ("CDF_CLUSTER")
        self._project = self.environ("CDF_PROJECT")
        # CDF_URL is optional, but if set, we use that instead of the default URL using cluster.
        self._cdf_url = self.environ("CDF_URL", f"https://{self._cluster}.cognitedata.com")
        # If CDF_TOKEN is set, we want to use that token instead of client credentials.
        if self.environ("CDF_TOKEN", default=None, fail=False) is not None or token is not None:
            self._client = CogniteClient(
                ClientConfig(
                    client_name=client_name,
                    base_url=self._cdf_url,
                    project=self._project,
                    credentials=Token(token or self.environ("CDF_TOKEN")),
                )
            )
        else:
            # We are now doing OAuth2 client credentials flow, so we need to set the
            # required variables.
            # We can infer scopes and audience from the cluster value.
            # However, the URL to use to retrieve the token, as well as
            # the client id and secret, must be set as environment variables.
            self._scopes = [
                self.environ(
                    "IDP_SCOPES",
                    f"https://{self._cluster}.cognitedata.com/.default",
                )
            ]
            self._audience = self.environ("IDP_AUDIENCE", f"https://{self._cluster}.cognitedata.com")
            self.oauth_credentials = OAuthClientCredentials(
                token_url=self.environ("IDP_TOKEN_URL"),
                client_id=self.environ("IDP_CLIENT_ID"),
                # client secret should not be stored in-code, so we load it from an environment variable
                client_secret=self.environ("IDP_CLIENT_SECRET"),
                scopes=self._scopes,
                audience=self._audience,
            )
            global_config.disable_pypi_version_check = True
            self._client = CogniteClient(
                ClientConfig(
                    client_name=client_name,
                    base_url=self._cdf_url,
                    project=self._project,
                    credentials=self.oauth_credentials,
                )
            )

    def environment_variables(self) -> dict[str, str]:
        return self._environ.copy()

    def as_string(self):
        environment = self._environ.copy()
        if "IDP_CLIENT_SECRET" in environment:
            environment["IDP_CLIENT_SECRET"] = "***"
        if "TRANSFORMATIONS_CLIENT_SECRET" in environment:
            environment["TRANSFORMATIONS_CLIENT_SECRET"] = "***"
        envs = ""
        for e in environment:
            envs += f"  {e}={environment[e]}\n"
        return f"Cluster {self._cluster} with project {self._project} and config:\n{envs}"

    def __str__(self):
        environment = self._environ.copy()
        if "IDP_CLIENT_SECRET" in environment:
            environment["IDP_CLIENT_SECRET"] = "***"
        if "TRANSFORMATIONS_CLIENT_SECRET" in environment:
            environment["TRANSFORMATIONS_CLIENT_SECRET"] = "***"
        return f"Cluster {self._cluster} with project {self._project} and config:\n" + json.dumps(
            environment, indent=2, sort_keys=True
        )

    @property
    # Flag set if something that should have worked failed if a data set is
    # loaded and/or deleted.
    def failed(self) -> bool:
        return self._failed

    @failed.setter
    def failed(self, value: bool):
        self._failed = value

    @property
    def client(self) -> CogniteClient:
        return self._client

    @property
    def project(self) -> str:
        return self._project

    @property
    def data_set_id(self) -> int | None:
        return self._data_set_id if self._data_set_id > 0 else None

    # Use this to ignore the data set when verifying the client's access capabilities
    def clear_dataset(self):
        self._data_set_id = 0
        self._data_set = None

    def environ(self, attr: str, default: str | list[str] | None = None, fail: bool = True) -> str:
        """Helper function to load variables from the environment.

        Use python-dotenv to load environment variables from an .env file before
        using this function.

        If the environment variable has spaces, it will be split into a list of strings.

        Args:
            attr: name of environment variable
            default: default value if environment variable is not set
            fail: if True, raise ValueError if environment variable is not set

        Yields:
            Value of the environment variable
            Raises ValueError if environment variable is not set and fail=True
        """
        if attr in self._environ and self._environ[attr] is not None:
            return self._environ[attr]
        # If the var was none, we want to re-evaluate from environment.
        self._environ[attr] = os.environ.get(attr, None)
        if self._environ[attr] is None:
            if default is None and fail:
                raise ValueError(f"{attr} property is not available as an environment variable and no default set.")
            self._environ[attr] = default
        return self._environ[attr]

    @property
    def data_set(self) -> str:
        return self._data_set

    @data_set.setter
    def data_set(self, value: str):
        if value is None:
            raise ValueError("Please provide an externalId of a dataset.")
        self._data_set = value
        # Since we now have a new configuration, check the dataset and set the id
        self._data_set_id = self.verify_dataset(data_set_external_id=value)

    def verify_client(
        self,
        capabilities: list[dict[str, list[str]]] | None = None,
        data_set_id: int = 0,
        space_id: str | None = None,
    ) -> CogniteClient:
        """Verify that the client has correct credentials and required access rights

        Supply requirement CDF ACLs to verify if you have correct access
        capabilities = {
            "filesAcl": ["READ", "WRITE"],
            "datasetsAcl": ["READ", "WRITE"]
        }
        The data_set_id will be used when verifying that the client has access to the dataset.
        This approach can be reused for any usage of the Cognite Python SDK.

        Args:
            capabilities (dict[list], optional): access capabilities to verify
            data_set_id (int): id of dataset that access should be granted to
            space_id (str): id of space that access should be granted to

        Yields:
            CogniteClient: Verified client with access rights
            Re-raises underlying SDK exception
        """
        capabilities = capabilities or {}
        try:
            # Using the token/inspect endpoint to check if the client has access to the project.
            # The response also includes access rights, which can be used to check if the client has the
            # correct access for what you want to do.
            resp = self.client.iam.token.inspect()
            if resp is None or len(resp.capabilities.data) == 0:
                raise CogniteAuthError("Don't have any access rights. Check credentials.")
        except Exception as e:
            raise e
        scope = {}
        if data_set_id > 0:
            scope["dataSetScope"] = {"ids": [data_set_id]}
        if space_id is not None:
            scope["spaceScope"] = {"ids": [space_id]}
        if space_id is None and data_set_id == 0:
            scope["all"] = {}
        try:
            caps = [
                Capability.load(
                    {
                        cap: {
                            "actions": actions,
                            "scope": scope,
                        },
                    }
                )
                for cap, actions in capabilities.items()
            ] or None
        except Exception:
            raise ValueError(f"Failed to load capabilities from {capabilities}. Wrong syntax?")
        comp = self.client.iam.compare_capabilities(resp.capabilities, caps)
        if len(comp) > 0:
            print(f"Missing necessary CDF access capabilities: {comp}")
            raise CogniteAuthError("Don't have correct access rights.")
        return self._client

    def verify_capabilities(self, capability: Capability | Sequence[Capability]) -> CogniteClient:
        missing_capabilities = self._client.iam.verify_capabilities(capability)
        if len(missing_capabilities) > 0:
            raise CogniteAuthError(f"Missing capabilities: {missing_capabilities}")
        return self._client

    def verify_dataset(self, data_set_external_id: str) -> int:
        """Verify that the configured data set exists and is accessible

        Args:
            data_set_external_id (str): External_id of the data set to verify
        Returns:
            data_set_id (int)
            Re-raises underlying SDK exception
        """
        if data_set_external_id in self._data_set_id_by_external_id:
            return self._data_set_id_by_external_id[data_set_external_id]

        self.verify_client(capabilities={"datasetsAcl": ["READ"]})
        try:
            data_set = self.client.data_sets.retrieve(external_id=data_set_external_id)
        except CogniteAPIError as e:
            raise CogniteAuthError("Don't have correct access rights. Need READ and WRITE on datasetsAcl.") from e
        if data_set is not None:
            self._data_set_id_by_external_id[data_set_external_id] = data_set.id
            return data_set.id
        raise ValueError(
            f"Data set {data_set_external_id} does not exist, you need to create it first. Do this by adding a config file to the data_sets folder."
        )

    def verify_extraction_pipeline(self, external_id: str) -> int:
        """Verify that the configured extraction pipeline exists and is accessible

        Args:
            external_id (str): External id of the extraction pipeline to verify
        Yields:
            extraction pipeline id (int)
            Re-raises underlying SDK exception
        """

        self.verify_client(capabilities={"extractionPipelinesAcl": ["READ"]})
        try:
            pipeline = self.client.extraction_pipelines.retrieve(external_id=external_id)
        except CogniteAPIError as e:
            raise CogniteAuthError("Don't have correct access rights. Need READ on datasetsAcl.") from e

        if pipeline is not None:
            return pipeline.id
        raise ValueError(
            f"Extraction pipeline {external_id} does not exist, you need to create it first. Do this by adding a config file to the extraction_pipelines folder."
        )


def load_yaml_inject_variables(filepath: Path, variables: dict[str, str]) -> dict[str, Any] | list[dict[str, Any]]:
    content = filepath.read_text()
    for key, value in variables.items():
        if value is None:
            continue
        content = content.replace("${%s}" % key, value)
    return yaml.safe_load(content)


@dataclass(frozen=True)
class Warning:
    filepath: Path
    id_value: str
    id_name: str


@total_ordering
@dataclass(frozen=True)
class CaseWarning(Warning):
    actual: str
    expected: str | None

    def __lt__(self, other: CaseWarning) -> bool:
        if not isinstance(other, CaseWarning):
            return NotImplemented
        return (self.filepath, self.id_value, self.expected, self.actual) < (
            other.filepath,
            other.id_value,
            other.expected,
            other.actual,
        )

    def __eq__(self, other: CaseWarning) -> bool:
        if not isinstance(other, CaseWarning):
            return NotImplemented
        return (self.filepath, self.id_value, self.expected, self.actual) == (
            other.filepath,
            other.id_value,
            other.expected,
            other.actual,
        )


def validate_raw(
    raw: dict[str, Any] | list[dict[str, Any]],
    resource_cls: CogniteObject,
    filepath: Path,
    identifier_key: str = "externalId",
) -> list[CaseWarning]:
    """Checks whether camel casing the raw data would match a parameter in the resource class.

    Args:
        raw: The raw data to check.
        resource_cls: The resource class to check against init method
        filepath: The filepath of the raw data. This is used to pass to the warnings for easy
            grouping of warnings.
        identifier_key: The key to use as identifier. Defaults to "externalId". This is used to pass to the warnings
            for easy grouping of warnings.

    Returns:
        A list of CaseWarning objects.

    """
    return _validate_raw(raw, resource_cls, filepath, identifier_key)


def _validate_raw(
    raw: dict[str, Any] | list[dict[str, Any]],
    resource_cls: CogniteObject,
    filepath: Path,
    identifier_key: str = "externalId",
    identifier_value: str = "",
) -> list[CaseWarning]:
    warnings = []
    if isinstance(raw, list):
        for item in raw:
            warnings.extend(_validate_raw(item, resource_cls, filepath, identifier_key))
        return warnings
    elif not isinstance(raw, dict):
        return warnings

    signature = inspect.signature(resource_cls.__init__)

    expected = set(map(to_camel, signature.parameters.keys())) - {"self"}

    actual = set(raw.keys())
    actual_camel_case = set(map(to_camel, actual))
    snake_cased = actual - actual_camel_case

    if not identifier_value:
        identifier_value = raw.get(identifier_key, raw.get(to_snake(identifier_key), f"No identifier {identifier_key}"))

    for key in snake_cased:
        if (camel_key := to_camel(key)) in expected:
            warnings.append(CaseWarning(filepath, identifier_value, identifier_key, str(key), str(camel_key)))
        else:
            warnings.append(CaseWarning(filepath, identifier_value, identifier_key, str(key), None))

    try:
        type_hint_by_name = _TypeHints()(signature, resource_cls)
    except Exception:
        # If we cannot get type hints, we cannot check if the type is correct.
        return warnings

    for key, value in raw.items():
        if not isinstance(value, dict):
            continue
        if (parameter := signature.parameters.get(to_snake(key))) and (
            type_hint := type_hint_by_name.get(parameter.name)
        ):
            if issubclass(type_hint, CogniteObject):
                warnings.extend(_validate_raw(value, type_hint, filepath, identifier_key, identifier_value))
                continue

            container_type = get_origin(type_hint)
            if container_type not in [dict, dict, collections.abc.MutableMapping, collections.abc.Mapping]:
                continue
            args = typing.get_args(type_hint)
            if not args:
                continue
            container_key, container_value = args
            if issubclass(container_value, CogniteObject):
                for sub_key, sub_value in value.items():
                    warnings.extend(
                        _validate_raw(sub_value, container_value, filepath, identifier_key, identifier_value)
                    )

    return warnings


def to_camel(string: str) -> str:
    """Convert snake_case_name to camelCaseName.

    Args:
        string: The string to convert.
    Returns:
        camelCase of the input string.

    Examples:
        >>> to_camel("a_b")
        'aB'
        >>> to_camel('camel_case')
        'camelCase'
        >>> to_camel('best_director')
        'bestDirector'
        >>> to_camel("ScenarioInstance_priceForecast")
        'scenarioInstancePriceForecast'
    """
    if "_" in string:
        # Could be a combination of snake and pascal/camel case
        parts = string.split("_")
        pascal_splits = [to_pascal(part) for part in parts]
    else:
        # Assume is pascal/camel case
        # Ensure pascal
        string = string[0].upper() + string[1:]
        pascal_splits = [string]
    string_split = []
    for part in pascal_splits:
        string_split.extend(re.findall(r"[A-Z][a-z]*", part))
    if not string_split:
        string_split = [string]
    try:
        return string_split[0].casefold() + "".join(word.capitalize() for word in string_split[1:])
    except IndexError:
        return ""


def to_pascal(string: str) -> str:
    """Convert string to PascalCaseName.

    Args:
        string: The string to convert.
    Returns:
        PascalCase of the input string.

    Examples:
        >>> to_pascal("a_b")
        'AB'
        >>> to_pascal('camel_case')
        'CamelCase'
        >>> to_pascal('best_director')
        'BestDirector'
        >>> to_pascal("ScenarioInstance_priceForecast")
        'ScenarioInstancePriceForecast'
    """
    camel = to_camel(string)
    return f"{camel[0].upper()}{camel[1:]}" if camel else ""


def to_snake(string: str) -> str:
    """
    Convert input string to snake_case

    Args:
        string: The string to convert.
    Returns:
        snake_case of the input string.

    Examples:
        >>> to_snake("aB")
        'a_b'
        >>> to_snake('CamelCase')
        'camel_case'
        >>> to_snake('camelCamelCase')
        'camel_camel_case'
        >>> to_snake('Camel2Camel2Case')
        'camel_2_camel_2_case'
        >>> to_snake('getHTTPResponseCode')
        'get_http_response_code'
        >>> to_snake('get200HTTPResponseCode')
        'get_200_http_response_code'
        >>> to_snake('getHTTP200ResponseCode')
        'get_http_200_response_code'
        >>> to_snake('HTTPResponseCode')
        'http_response_code'
        >>> to_snake('ResponseHTTP')
        'response_http'
        >>> to_snake('ResponseHTTP2')
        'response_http_2'
        >>> to_snake('Fun?!awesome')
        'fun_awesome'
        >>> to_snake('Fun?!Awesome')
        'fun_awesome'
        >>> to_snake('10CoolDudes')
        '10_cool_dudes'
        >>> to_snake('20coolDudes')
        '20_cool_dudes'
    """
    pattern = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|\d|\W|$)|\d+")
    if "_" in string:
        words = [word for section in string.split("_") for word in pattern.findall(section)]
    else:
        words = pattern.findall(string)
    return "_".join(map(str.lower, words))


class _TypeHints:
    def __call__(self, signature, resource_cls: CogniteObject):
        try:
            type_hint_by_name = get_type_hints(resource_cls.__init__, localns=self._type_checking)
        except TypeError:
            # Python 3.10 Type hints cannot be evaluated with get_type_hints,
            # ref https://stackoverflow.com/questions/66006087/how-to-use-typing-get-type-hints-with-pep585-in-python3-8
            resource_module_vars = vars(importlib.import_module(resource_cls.__module__))
            resource_module_vars.update(self._type_checking())
            type_hint_by_name = self._get_type_hints_3_10(resource_module_vars, signature, vars(resource_cls))
        return type_hint_by_name

    @classmethod
    def _type_checking(cls) -> dict[str, Any]:
        """
        When calling the get_type_hints function, it imports the module with the function TYPE_CHECKING is set to False.

        This function takes all the special types used in data classes and returns them as a dictionary so it
        can be used in the local namespaces.
        """
        import numpy as np
        import numpy.typing as npt
        from cognite.client import CogniteClient

        NumpyDatetime64NSArray = npt.NDArray[np.datetime64]
        NumpyInt64Array = npt.NDArray[np.int64]
        NumpyFloat64Array = npt.NDArray[np.float64]
        NumpyObjArray = npt.NDArray[np.object_]
        return {
            "CogniteClient": CogniteClient,
            "NumpyDatetime64NSArray": NumpyDatetime64NSArray,
            "NumpyInt64Array": NumpyInt64Array,
            "NumpyFloat64Array": NumpyFloat64Array,
            "NumpyObjArray": NumpyObjArray,
        }

    @classmethod
    def _get_type_hints_3_10(
        cls, resource_module_vars: dict[str, Any], signature310: inspect.Signature, local_vars: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            name: cls._create_type_hint_3_10(parameter.annotation, resource_module_vars, local_vars)
            for name, parameter in signature310.parameters.items()
            if name != "self"
        }

    @classmethod
    def _create_type_hint_3_10(
        cls, annotation: str, resource_module_vars: dict[str, Any], local_vars: dict[str, Any]
    ) -> Any:
        if annotation.endswith(" | None"):
            annotation = annotation[:-7]
        try:
            return eval(annotation, resource_module_vars, local_vars)
        except TypeError:
            # Python 3.10 Type Hint
            return cls._type_hint_3_10_to_8(annotation, resource_module_vars, local_vars)

    @classmethod
    def _type_hint_3_10_to_8(
        cls, annotation: str, resource_module_vars: dict[str, Any], local_vars: dict[str, Any]
    ) -> Any:
        if cls._is_vertical_union(annotation):
            alternatives = [
                cls._create_type_hint_3_10(a.strip(), resource_module_vars, local_vars) for a in annotation.split("|")
            ]
            return typing.Union[tuple(alternatives)]
        elif annotation.startswith("dict[") and annotation.endswith("]"):
            if Counter(annotation)[","] > 1:
                key, rest = annotation[5:-1].split(",", 1)
                return dict[key.strip(), cls._create_type_hint_3_10(rest.strip(), resource_module_vars, local_vars)]
            key, value = annotation[5:-1].split(",")
            return dict[
                cls._create_type_hint_3_10(key.strip(), resource_module_vars, local_vars),
                cls._create_type_hint_3_10(value.strip(), resource_module_vars, local_vars),
            ]
        elif annotation.startswith("Mapping[") and annotation.endswith("]"):
            if Counter(annotation)[","] > 1:
                key, rest = annotation[8:-1].split(",", 1)
                return typing.Mapping[
                    key.strip(), cls._create_type_hint_3_10(rest.strip(), resource_module_vars, local_vars)
                ]
            key, value = annotation[8:-1].split(",")
            return typing.Mapping[
                cls._create_type_hint_3_10(key.strip(), resource_module_vars, local_vars),
                cls._create_type_hint_3_10(value.strip(), resource_module_vars, local_vars),
            ]
        elif annotation.startswith("Optional[") and annotation.endswith("]"):
            return typing.Optional[cls._create_type_hint_3_10(annotation[9:-1], resource_module_vars, local_vars)]
        elif annotation.startswith("list[") and annotation.endswith("]"):
            return list[cls._create_type_hint_3_10(annotation[5:-1], resource_module_vars, local_vars)]
        elif annotation.startswith("tuple[") and annotation.endswith("]"):
            return tuple[cls._create_type_hint_3_10(annotation[6:-1], resource_module_vars, local_vars)]
        elif annotation.startswith("typing.Sequence[") and annotation.endswith("]"):
            # This is used in the Sequence data class file to avoid name collision
            return typing.Sequence[cls._create_type_hint_3_10(annotation[16:-1], resource_module_vars, local_vars)]
        raise NotImplementedError(f"Unsupported conversion of type hint {annotation!r}. {cls._error_msg}")

    @classmethod
    def _is_vertical_union(cls, annotation: str) -> bool:
        if "|" not in annotation:
            return False
        parts = [p.strip() for p in annotation.split("|")]
        for part in parts:
            counts = Counter(part)
            if counts["["] != counts["]"]:
                return False
        return True
