import os
from multiprocessing.context import AuthenticationError
from typing import Any
from unittest import mock

import pytest
from requests.exceptions import ConnectionError

from cognite_toolkit._cdf_tk.client import ToolkitClientConfig
from cognite_toolkit._cdf_tk.exceptions import ToolkitMissingValueError
from cognite_toolkit._cdf_tk.utils.auth2 import EnvironmentVariables

PROJECT_AND_CLUSTER = {
    "CDF_CLUSTER": "toolkit-cluster",
    "CDF_PROJECT": "the-toolkit-project",
}


class TestEnvironmentVariables:
    @pytest.mark.parametrize(
        "args",
        [
            pytest.param({**PROJECT_AND_CLUSTER, "LOGIN_FLOW": "token", "CDF_TOKEN": "super-token"}, id="token flow"),
            pytest.param(
                {
                    **PROJECT_AND_CLUSTER,
                    "LOGIN_FLOW": "client_credentials",
                    "PROVIDER": "entra_id",
                    "IDP_TENANT_ID": "my_tenant.onmicrosoft.com",
                    "IDP_CLIENT_ID": "my-identifier",
                    "IDP_CLIENT_SECRET": "my***super***secret",
                },
                id="client-credentials entra",
            ),
            pytest.param(
                {
                    **PROJECT_AND_CLUSTER,
                    "LOGIN_FLOW": "client_credentials",
                    "PROVIDER": "other",
                    "IDP_TOKEN_URL": "https://auth.login.my_domian.io/oauth/token",
                    "IDP_AUDIENCE": "https://toolkit-cluster.fusion.cognite.com/the-toolkit-project",
                    "IDP_SCOPES": "IDENTITY,ADMIN,client:cognite-cicd@my_domain.io,user_impersonation",
                    "IDP_CLIENT_ID": "my-identifier",
                    "IDP_CLIENT_SECRET": "my***super***secret",
                },
                id="client-credentials other (auth0)",
            ),
            pytest.param(
                {
                    **PROJECT_AND_CLUSTER,
                    "LOGIN_FLOW": "interactive",
                    "PROVIDER": "entra_id",
                    "IDP_TENANT_ID": "my_tenant.onmicrosoft.com",
                    "IDP_CLIENT_ID": "my-identifier",
                },
                id="interactive entra",
            ),
            pytest.param(
                {
                    **PROJECT_AND_CLUSTER,
                    "LOGIN_FLOW": "device_code",
                    "PROVIDER": "entra_id",
                    "IDP_TENANT_ID": "my_tenant.onmicrosoft.com",
                },
                id="device enta",
            ),
            pytest.param(
                {
                    **PROJECT_AND_CLUSTER,
                    "LOGIN_FLOW": "device_code",
                    "PROVIDER": "other",
                    "IDP_CLIENT_ID": "my-identifier",
                    "IDP_DISCOVERY_URL": "https://auth.login.my_domian.io/oauth",
                },
                id="device other",
            ),
        ],
    )
    def test_get_valid_config(self, args: dict[str, Any]) -> None:
        env_vars = EnvironmentVariables(**args)

        try:
            config = env_vars.get_config()
        except (KeyError, AuthenticationError) as e:
            assert False, f"Failed to get config: {e}"
        except (ValueError, ConnectionError):
            # When we try to instantiate config for interactive login, we get an error
            # because the domain is not valid. In this test we are only interested in
            # the config object, so we ignore this error.
            assert True
        else:
            assert isinstance(config, ToolkitClientConfig)

    def test_get_invalid_config(self) -> None:
        args = {
            **PROJECT_AND_CLUSTER,
            "LOGIN_FLOW": "client_credentials",
            "PROVIDER": "entra_id",
            "IDP_CLIENT_ID": "my-identifier",
        }

        with pytest.raises(ToolkitMissingValueError) as error:
            _ = EnvironmentVariables(**args).get_config()

        assert (
            str(error.value)
            == "The login flow 'client_credentials' requires the following environment variables: IDP_CLIENT_SECRET."
        )

    @mock.patch.dict(
        os.environ,
        {
            **PROJECT_AND_CLUSTER,
            "LOGIN_FLOW": "client_credentials",
            "IDP_CLIENT_ID": "my-identifier",
            "IDP_CLIENT_SECRET": "my-secret",
            "IDP_TENANT_ID": "my_tenant.onmicrosoft.com",
            "CDF_CLIENT_TIMEOUT": "10",
            "CDF_CLIENT_MAX_WORKERS": "5000",
        },
    )
    def test_create_environment_variables(
        self,
    ) -> None:
        env_vars = EnvironmentVariables.create_from_environment()

        assert env_vars.LOGIN_FLOW == "client_credentials"
        assert env_vars.CDF_CLUSTER == "toolkit-cluster"
        assert env_vars.CDF_PROJECT == "the-toolkit-project"
        assert env_vars.IDP_CLIENT_ID == "my-identifier"
        assert env_vars.IDP_CLIENT_SECRET == "my-secret"
        assert env_vars.IDP_TENANT_ID == "my_tenant.onmicrosoft.com"
        assert env_vars.CDF_CLIENT_TIMEOUT == 10
        assert env_vars.CDF_CLIENT_MAX_WORKERS == 5000
