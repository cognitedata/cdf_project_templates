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
import logging
import os

from cognite.client import ClientConfig, CogniteClient
from cognite.client.credentials import OAuthClientCredentials, Token
from cognite.client.data_classes.data_sets import DataSet
from cognite.client.exceptions import CogniteAuthError

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
    ) -> None:
        self._data_set_id: int = 0
        self._data_set = None
        self._failed = False
        self._environ = {}

        if token is not None:
            self._environ["CDF_TOKEN"] = token
        if (
            self.environ("CDF_URL", default=None, fail=False) is None
            and self.environ("CDF_CLUSTER", default=None, fail=False) is None
        ):
            # If CDF_URL and CDF_CLUSTER are not set, we may be in a Jupyter notebook in Fusion,
            # and credentials are preset to logged in user (no env vars are set!).
            self._client = CogniteClient()
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
            self._client = CogniteClient(
                ClientConfig(
                    client_name=client_name,
                    base_url=self._cdf_url,
                    project=self._project,
                    credentials=OAuthClientCredentials(
                        token_url=self.environ("IDP_TOKEN_URL"),
                        client_id=self.environ("IDP_CLIENT_ID"),
                        # client secret should not be stored in-code, so we load it from an environment variable
                        client_secret=self.environ("IDP_CLIENT_SECRET"),
                        scopes=self._scopes,
                        audience=self._audience,
                    ),
                )
            )

    def __str__(self):
        return f"Cluster {self._cluster} with project {self._project} and config:\n" + json.dumps(
            self._environ, indent=2, sort_keys=True
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
    def data_set_id(self) -> int:
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
        self._data_set_id = self.verify_dataset(data_set_name=value)

    def verify_client(self, capabilities: dict[str, list[str]] | None = None) -> None:
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
            if resp is None or len(resp.capabilities) == 0:
                raise CogniteAuthError("Don't have any access rights. Check credentials.")
        except Exception as e:
            raise e
        # iterate over all the capabilities we need
        for cap, actions in capabilities.items():
            # Find the right capability in our granted capabilities
            for k in resp.capabilities:
                if len(k.get(cap, {})) == 0:
                    continue
                # For each of the actions (e.g. READ or WRITE) we need, check if we have it
                for a in actions:
                    if a not in k.get(cap, {}).get("actions", []):
                        raise CogniteAuthError(f"Don't have correct access rights. Need {a} on {cap}")
                # Check if we either have all scope or data_set_id scope
                if "all" not in k.get(cap, {}).get("scope", {}) and (
                    self._data_set_id != 0
                    and str(self._data_set_id) not in k.get(cap, {}).get("scope", {}).get("datasetScope").get("ids", [])
                ):
                    raise CogniteAuthError(f"Don't have correct access rights. Need {a} on {cap}")
                continue
        return self._client

    def verify_dataset(self, data_set_name: str | None = None, create: bool = True) -> int | None:
        """Verify that the configured data set exists and is accessible

        If the data set does not exist, it will be created unless create=False.
        If create=False and the data set does not exist, verify_dataset will return 0.

        Args:
            data_set_name (str, optional): name of the data set to verify
        Yields:
            data_set_id (int)
            Re-raises underlying SDK exception
        """

        self.verify_client(capabilities={"datasetsAcl": ["READ", "WRITE"]})
        try:
            data_set = self.client.data_sets.retrieve(external_id=data_set_name)
            if data_set is not None:
                return data_set.id
        except Exception:
            raise CogniteAuthError("Don't have correct access rights. Need READ and WRITE on datasetsAcl.")
        if not create:
            return 0
        try:
            # name can be empty, but is useful for UI purposes
            data_set = DataSet(
                external_id=data_set_name,
                name=data_set_name,
            )
            data_set = self.client.data_sets.create(data_set)
            return data_set.id
        except Exception:
            raise CogniteAuthError(
                "Don't have correct access rights. Need also WRITE on "
                + "datasetsAcl or that the data set {get_dataset_name()} has been created."
            )
