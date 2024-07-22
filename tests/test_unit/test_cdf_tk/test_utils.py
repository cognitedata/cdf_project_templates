from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any
from unittest import mock
from unittest.mock import MagicMock, Mock, patch

import pytest
import yaml
from cognite.client._api.iam import IAMAPI, TokenAPI, TokenInspection
from cognite.client.credentials import OAuthClientCredentials, OAuthInteractive
from cognite.client.data_classes.capabilities import (
    DataSetsAcl,
    ProjectCapability,
    ProjectCapabilityList,
    ProjectsScope,
)
from cognite.client.data_classes.iam import ProjectSpec
from cognite.client.exceptions import CogniteAuthError
from cognite.client.testing import CogniteClientMock, monkeypatch_cognite_client
from pytest import MonkeyPatch

from cognite_toolkit._cdf_tk.exceptions import AuthenticationError
from cognite_toolkit._cdf_tk.tk_warnings import TemplateVariableWarning
from cognite_toolkit._cdf_tk.utils import (
    AuthVariables,
    CDFToolConfig,
    calculate_directory_hash,
    flatten_dict,
    iterate_modules,
    load_yaml_inject_variables,
    module_from_path,
)
from cognite_toolkit._cdf_tk.validation import validate_modules_variables
from tests.data import DATA_FOLDER, PYTEST_PROJECT
from tests.tests_unit.utils import PrintCapture


def mocked_init(self):
    self._client = CogniteClientMock()
    self._cache = CDFToolConfig._Cache()


def test_init():
    with patch.object(CDFToolConfig, "__init__", mocked_init):
        instance = CDFToolConfig()
        assert isinstance(instance._client, CogniteClientMock)


@pytest.mark.skip("Rewrite to use ApprovalClient")
def test_dataset_missing_acl():
    with patch.object(CDFToolConfig, "__init__", mocked_init):
        with pytest.raises(CogniteAuthError):
            instance = CDFToolConfig()
            instance.verify_dataset("test")


def test_dataset_create():
    with patch.object(CDFToolConfig, "__init__", mocked_init):
        instance = CDFToolConfig()
        instance._client.config.project = "cdf-project-templates"
        instance._client.iam.compare_capabilities = IAMAPI.compare_capabilities
        instance._client.iam.token.inspect = Mock(
            spec=TokenAPI.inspect,
            return_value=TokenInspection(
                subject="",
                capabilities=ProjectCapabilityList(
                    [
                        ProjectCapability(
                            capability=DataSetsAcl(
                                [DataSetsAcl.Action.Read, DataSetsAcl.Action.Write], scope=DataSetsAcl.Scope.All()
                            ),
                            project_scope=ProjectsScope(["cdf-project-templates"]),
                        )
                    ],
                    cognite_client=instance._client,
                ),
                projects=[ProjectSpec(url_name="cdf-project-templates", groups=[])],
            ),
        )

        # the dataset exists
        instance.verify_dataset("test")
        assert instance._client.data_sets.retrieve.call_count == 1


class TestLoadYamlInjectVariables:
    def test_load_yaml_inject_variables(self, tmp_path: Path) -> None:
        my_file = tmp_path / "test.yaml"
        my_file.write_text(yaml.safe_dump({"test": "${TEST}"}))

        loaded = load_yaml_inject_variables(my_file, {"TEST": "my_injected_value"})

        assert loaded["test"] == "my_injected_value"

    def test_warning_when_missing_env_variable(self, tmp_path: Path, capture_print: PrintCapture) -> None:
        my_file = tmp_path / "test.yaml"
        my_file.write_text(yaml.safe_dump({"test": "${TEST}"}))
        expected_warning = f"WARNING: Variable TEST is not set in the environment. It is expected in {my_file.name}."

        load_yaml_inject_variables(my_file, {})

        assert capture_print.messages, "Nothing was printed"
        last_message = capture_print.messages[-1]
        assert last_message == expected_warning


@pytest.mark.parametrize(
    "config_yaml, expected_warnings",
    [
        pytest.param(
            {"sourceId": "<change_me>"},
            [TemplateVariableWarning(Path("config.yaml"), "<change_me>", "sourceId", "")],
            id="Single warning",
        ),
        pytest.param(
            {"a_module": {"sourceId": "<change_me>"}},
            [TemplateVariableWarning(Path("config.yaml"), "<change_me>", "sourceId", "a_module")],
            id="Nested warning",
        ),
        pytest.param(
            {"a_super_module": {"a_module": {"sourceId": "<change_me>"}}},
            [TemplateVariableWarning(Path("config.yaml"), "<change_me>", "sourceId", "a_super_module.a_module")],
            id="Deep nested warning",
        ),
        pytest.param({"a_module": {"sourceId": "123"}}, [], id="No warning"),
    ],
)
def test_validate_config_yaml(config_yaml: dict[str, Any], expected_warnings: list[TemplateVariableWarning]) -> None:
    warnings = validate_modules_variables(config_yaml, Path("config.yaml"))

    assert sorted(warnings) == sorted(expected_warnings)


def test_calculate_hash_on_folder():
    folder = Path(DATA_FOLDER / "calc_hash_data")
    hash1 = calculate_directory_hash(folder)
    hash2 = calculate_directory_hash(folder)

    print(hash1)

    assert (
        hash1 == "e60120ed03ebc1de314222a6a330dce08b7e2d77ec0929cd3c603cfdc08999ad"
    ), f"The hash should not change as long as content in {folder} is not changed."
    assert hash1 == hash2
    tempdir = Path(tempfile.mkdtemp())
    shutil.rmtree(tempdir)
    shutil.copytree(folder, tempdir)
    hash3 = calculate_directory_hash(tempdir)
    shutil.rmtree(tempdir)

    assert hash1 == hash3


class TestCDFToolConfig:
    def test_initialize_token(self):
        expected = """# .env file generated by cognite-toolkit
CDF_CLUSTER=my_cluster
CDF_PROJECT=my_project
LOGIN_FLOW=token
# When using a token, the IDP variables are not needed, so they are not included.
CDF_TOKEN=12345
# The below variables are the defaults, they are automatically constructed unless they are set.
CDF_URL=https://my_cluster.cognitedata.com"""
        with monkeypatch_cognite_client() as _:
            config = CDFToolConfig(token="12345", cluster="my_cluster", project="my_project")
            env_file = AuthVariables.from_env(config._environ).create_dotenv_file()
        not_equal = set(env_file.splitlines()) ^ set(expected.splitlines())
        assert not not_equal, "Found differences in the generated .env file: \n" + "\n".join(not_equal)

    @pytest.mark.skipif(
        os.environ.get("IS_GITHUB_ACTIONS") == "true",
        reason="GitHub Actions will mask, IDP_TOKEN_URL=***, which causes this test to fail",
    )
    def test_initialize_interactive_login(self):
        expected = """# .env file generated by cognite-toolkit
CDF_CLUSTER=my_cluster
CDF_PROJECT=my_project
LOGIN_FLOW=interactive
IDP_CLIENT_ID=7890
# Note: Either the TENANT_ID or the TENANT_URL must be written.
IDP_TENANT_ID={tenant}
IDP_TOKEN_URL=https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token
# The below variables are the defaults, they are automatically constructed unless they are set.
CDF_URL=https://my_cluster.cognitedata.com
IDP_SCOPES=https://my_cluster.cognitedata.com/.default
IDP_AUTHORITY_URL=https://login.microsoftonline.com/{tenant}"""

        envs = {
            "LOGIN_FLOW": "interactive",
            "CDF_CLUSTER": "my_cluster",
            "CDF_PROJECT": "my_project",
            "IDP_TENANT_ID": "{tenant}",
            "IDP_CLIENT_ID": "7890",
        }

        with mock.patch.dict(os.environ, envs, clear=True):
            with MonkeyPatch.context() as mp:
                mp.setattr("cognite_toolkit._cdf_tk.utils.OAuthInteractive", MagicMock(spec=OAuthInteractive))
                with monkeypatch_cognite_client() as _:
                    config = CDFToolConfig()
                    env_file = AuthVariables.from_env(config._environ).create_dotenv_file()
            not_equal = set(env_file.splitlines()) ^ set(expected.splitlines())
            assert not not_equal, "Found differences in the generated .env file: \n" + "\n".join(not_equal)

    @pytest.mark.skipif(
        os.environ.get("IS_GITHUB_ACTIONS") == "true",
        reason="GitHub Actions will mask, IDP_TOKEN_URL=***, which causes this test to fail",
    )
    def test_initialize_client_credentials_login(self):
        expected = """# .env file generated by cognite-toolkit
CDF_CLUSTER=my_cluster
CDF_PROJECT=my_project
LOGIN_FLOW=client_credentials
IDP_CLIENT_ID=7890
IDP_CLIENT_SECRET=12345
# Note: Either the TENANT_ID or the TENANT_URL must be written.
IDP_TENANT_ID=12345
IDP_TOKEN_URL=https://login.microsoftonline.com/12345/oauth2/v2.0/token
# The below variables are the defaults, they are automatically constructed unless they are set.
CDF_URL=https://my_cluster.cognitedata.com
IDP_SCOPES=https://my_cluster.cognitedata.com/.default
IDP_AUDIENCE=https://my_cluster.cognitedata.com"""

        envs = {
            "LOGIN_FLOW": "client_credentials",
            "CDF_CLUSTER": "my_cluster",
            "CDF_PROJECT": "my_project",
            "IDP_TENANT_ID": "12345",
            "IDP_CLIENT_ID": "7890",
            "IDP_CLIENT_SECRET": "12345",
        }
        with mock.patch.dict(os.environ, envs, clear=True):
            with MonkeyPatch.context() as mp:
                mp.setattr(
                    "cognite_toolkit._cdf_tk.utils.OAuthClientCredentials", MagicMock(spec=OAuthClientCredentials)
                )
                with monkeypatch_cognite_client() as _:
                    config = CDFToolConfig()
                    env_file = AuthVariables.from_env(config._environ).create_dotenv_file()
            not_equal = set(env_file.splitlines()) ^ set(expected.splitlines())
            assert not not_equal, "Found differences in the generated .env file: \n" + "\n".join(not_equal)


def auth_variables_validate_test_cases():
    yield pytest.param(
        {
            "CDF_CLUSTER": "my_cluster",
            "CDF_PROJECT": "my_project",
            "LOGIN_FLOW": "token",
            "CDF_TOKEN": "12345",
        },
        False,
        "ok",
        [],
        {
            "cluster": "my_cluster",
            "project": "my_project",
            "cdf_url": "https://my_cluster.cognitedata.com",
            "login_flow": "token",
            "token": "12345",
            "client_id": None,
            "client_secret": None,
            "token_url": None,
            "tenant_id": None,
            "audience": "https://my_cluster.cognitedata.com",
            "scopes": "https://my_cluster.cognitedata.com/.default",
            "authority_url": None,
        },
        id="Happy path Token login",
    )

    yield pytest.param(
        {
            "CDF_CLUSTER": "my_cluster",
            "CDF_PROJECT": "my_project",
            "LOGIN_FLOW": "interactive",
            "IDP_CLIENT_ID": "7890",
            "IDP_TENANT_ID": "12345",
        },
        False,
        "ok",
        [],
        {
            "cluster": "my_cluster",
            "project": "my_project",
            "cdf_url": "https://my_cluster.cognitedata.com",
            "login_flow": "interactive",
            "token": None,
            "client_id": "7890",
            "client_secret": None,
            "token_url": "https://login.microsoftonline.com/12345/oauth2/v2.0/token",
            "tenant_id": "12345",
            "audience": "https://my_cluster.cognitedata.com",
            "scopes": "https://my_cluster.cognitedata.com/.default",
            "authority_url": "https://login.microsoftonline.com/12345",
        },
        id="Happy path Interactive login",
    )
    yield pytest.param(
        {
            "CDF_CLUSTER": "my_cluster",
            "CDF_PROJECT": "my_project",
            "LOGIN_FLOW": "client_credentials",
            "IDP_CLIENT_ID": "7890",
            "IDP_CLIENT_SECRET": "12345",
            "IDP_TENANT_ID": "12345",
        },
        False,
        "ok",
        [],
        {
            "cluster": "my_cluster",
            "project": "my_project",
            "cdf_url": "https://my_cluster.cognitedata.com",
            "login_flow": "client_credentials",
            "token": None,
            "client_id": "7890",
            "client_secret": "12345",
            "token_url": "https://login.microsoftonline.com/12345/oauth2/v2.0/token",
            "tenant_id": "12345",
            "audience": "https://my_cluster.cognitedata.com",
            "scopes": "https://my_cluster.cognitedata.com/.default",
            "authority_url": "https://login.microsoftonline.com/12345",
        },
        id="Happy path Client credentials login",
    )


class TestEnvironmentVariables:
    def test_env_variable(self):
        with patch.dict(os.environ, {"MY_ENV_VAR": "test_value"}):
            # Inside this block, MY_ENV_VAR is set to 'test_value'
            assert os.environ["MY_ENV_VAR"] == "test_value"

        assert os.environ.get("MY_ENV_VAR") is None


class TestAuthVariables:
    @pytest.mark.skipif(
        os.environ.get("IS_GITHUB_ACTIONS") == "true",
        reason="GitHub Actions will mask, IDP_TOKEN_URL=***, which causes this test to fail",
    )
    @pytest.mark.parametrize(
        "environment_variables, verbose, expected_status, expected_messages, expected_vars",
        auth_variables_validate_test_cases(),
    )
    def test_validate(
        self,
        environment_variables: dict[str, str],
        verbose: bool,
        expected_status: str,
        expected_messages: list[str],
        expected_vars: dict[str, str],
    ) -> None:
        with mock.patch.dict(os.environ, environment_variables, clear=True):
            auth_var = AuthVariables.from_env()
            results = auth_var.validate(verbose)

            assert results.status == expected_status
            assert results.messages == expected_messages

            if expected_vars:
                assert vars(auth_var) == expected_vars

    def test_missing_project_raise_authentication_error(self):
        with mock.patch.dict(os.environ, {"CDF_CLUSTER": "my_cluster"}, clear=True):
            with pytest.raises(AuthenticationError) as exc_info:
                AuthVariables.from_env().validate(False)
            assert str(exc_info.value) == "CDF Cluster and project are required. Missing: project."


class TestModuleFromPath:
    @pytest.mark.parametrize(
        "path, expected",
        [
            pytest.param(Path("cognite_modules/a_module/data_models/my_model.datamodel.yaml"), "a_module"),
            pytest.param(Path("cognite_modules/another_module/data_models/views/my_view.view.yaml"), "another_module"),
            pytest.param(
                Path("cognite_modules/parent_module/child_module/data_models/containers/my_container.container.yaml"),
                "child_module",
            ),
            pytest.param(
                Path("cognite_modules/parent_module/child_module/data_models/auth/my_group.group.yaml"), "child_module"
            ),
            pytest.param(Path("custom_modules/child_module/functions/functions.yaml"), "child_module"),
            pytest.param(Path("custom_modules/parent_module/child_module/functions/functions.yaml"), "child_module"),
        ],
    )
    def test_module_from_path(self, path: Path, expected: str):
        assert module_from_path(path) == expected


class TestIterateModules:
    def test_modules_project_for_tests(self):
        expected_modules = {
            PYTEST_PROJECT / "cognite_modules" / "a_module",
            PYTEST_PROJECT / "cognite_modules" / "another_module",
            PYTEST_PROJECT / "cognite_modules" / "parent_module" / "child_module",
        }

        actual_modules = {module for module, _ in iterate_modules(PYTEST_PROJECT)}

        assert actual_modules == expected_modules


@pytest.mark.parametrize(
    "input_, expected",
    [
        pytest.param({"a": {"b": 1, "c": 2}}, {("a", "b"): 1, ("a", "c"): 2}, id="Simple"),
        pytest.param({"a": {"b": {"c": 1}}}, {("a", "b", "c"): 1}, id="Nested"),
    ],
)
def test_flatten_dict(input_: dict[str, Any], expected: dict[str, Any]) -> None:
    actual = flatten_dict(input_)

    assert actual == expected
