from datetime import datetime
from unittest.mock import MagicMock

import pytest
from cognite.client.data_classes import ClientCredentials
from cognite.client.data_classes.functions import Function, FunctionCall
from cognite.client.data_classes.transformations import Transformation
from cognite.client.data_classes.workflows import (
    WorkflowExecution,
)

from cognite_toolkit._cdf_tk.commands import RunFunctionCommand, RunTransformationCommand, RunWorkflowCommand
from cognite_toolkit._cdf_tk.commands.run import FunctionCallArgs
from cognite_toolkit._cdf_tk.data_classes import ModuleResources
from cognite_toolkit._cdf_tk.feature_flags import Flags
from cognite_toolkit._cdf_tk.utils import CDFToolConfig, get_oneshot_session
from tests.data import RUN_DATA
from tests.test_unit.approval_client import ApprovalToolkitClient


def test_get_oneshot_session(toolkit_client_approval: ApprovalToolkitClient):
    cdf_tool = MagicMock(spec=CDFToolConfig)
    cdf_tool.client = toolkit_client_approval.mock_client
    cdf_tool.verify_authorization.return_value = toolkit_client_approval.mock_client
    session = get_oneshot_session(cdf_tool.client)
    assert session.id == 5192234284402249
    assert session.nonce == "QhlCnImCBwBNc72N"
    assert session.status == "READY"
    assert session.type == "ONESHOT_TOKEN_EXCHANGE"


class TestRunTransformation:
    def test_run_transformation(self, toolkit_client_approval: ApprovalToolkitClient):
        cdf_tool = MagicMock(spec=CDFToolConfig)
        cdf_tool.toolkit_client = toolkit_client_approval.mock_client
        cdf_tool.verify_authorization.return_value = toolkit_client_approval.mock_client
        transformation = Transformation(
            name="Test transformation",
            external_id="test",
            query="SELECT * FROM timeseries",
        )
        toolkit_client_approval.append(Transformation, transformation)

        assert RunTransformationCommand().run_transformation(cdf_tool, "test") is True


@pytest.fixture(scope="session")
def functon_module_resources() -> ModuleResources:
    return ModuleResources(RUN_DATA, "dev")


class TestRunFunction:
    def test_run_function_live(
        self, cdf_tool_mock: CDFToolConfig, toolkit_client_approval: ApprovalToolkitClient
    ) -> None:
        function = Function(
            id=1234567890,
            name="test3",
            external_id="fn_test3",
            description="Returns the input data, secrets, and function info.",
            owner="pytest",
            status="RUNNING",
            file_id=1234567890,
            function_path="./handler.py",
            created_time=int(datetime.now().timestamp() / 1000),
            secrets={"my_secret": "***"},
        )
        toolkit_client_approval.append(Function, function)
        toolkit_client_approval.mock_client.functions.call.return_value = FunctionCall(
            id=1234567890,
            status="RUNNING",
            start_time=int(datetime.now().timestamp() / 1000),
        )
        cmd = RunFunctionCommand()

        cmd.run_cdf(
            cdf_tool_mock,
            organization_dir=RUN_DATA,
            build_env_name="dev",
            external_id="fn_test3",
            data_source="daily-8pm-utc",
            wait=False,
        )
        assert toolkit_client_approval.mock_client.functions.call.called

    def test_run_local_function(self, cdf_tool_mock: CDFToolConfig) -> None:
        cmd = RunFunctionCommand()

        cmd.run_local(
            ToolGlobals=cdf_tool_mock,
            organization_dir=RUN_DATA,
            build_env_name="dev",
            external_id="fn_test3",
            data_source="daily-8pm-utc",
            rebuild_env=False,
        )

    @pytest.mark.skipif(not Flags.RUN_WORKFLOW.is_enabled(), reason="Neets workflow feature flag enabled")
    def test_run_local_function_with_workflow(self, cdf_tool_mock: CDFToolConfig) -> None:
        cmd = RunFunctionCommand()

        cmd.run_local(
            ToolGlobals=cdf_tool_mock,
            organization_dir=RUN_DATA,
            build_env_name="dev",
            external_id="fn_test3",
            data_source="workflow",
            rebuild_env=False,
        )

    # Note we are skipping a tests that does not require the feature flag to be enabled
    # However, this is a cleaner way to ship the tests, and that test will be run when the feature flag is enabled
    @pytest.mark.skipif(not Flags.RUN_WORKFLOW.is_enabled(), reason="Neets workflow feature flag enabled")
    @pytest.mark.parametrize(
        "data_source, expected",
        [
            pytest.param(
                "workflow",
                FunctionCallArgs(
                    data={
                        "breakfast": "today: egg and bacon",
                        "lunch": "today: a chicken",
                        "dinner": "today: steak with stakes on the side",
                    },
                    authentication=ClientCredentials(
                        client_id="workflow_client_id",
                        client_secret="workflow_client_secret",
                    ),
                    client_id_env_name="IDP_WF_CLIENT_ID",
                    client_secret_env_name="IDP_WF_CLIENT_SECRET",
                ),
                id="workflow",
            ),
            pytest.param(
                "daily-8am-utc",
                FunctionCallArgs(
                    data={
                        "breakfast": "today: peanut butter sandwich and coffee",
                        "lunch": "today: greek salad and water",
                        "dinner": "today: steak and red wine",
                    },
                    authentication=ClientCredentials(
                        client_id="function_client_id",
                        client_secret="function_client_secret",
                    ),
                    client_id_env_name="IDP_FUN_CLIENT_ID",
                    client_secret_env_name="IDP_FUN_CLIENT_SECRET",
                ),
                id="daily-8pm-utc",
            ),
        ],
    )
    def test_get_call_args(
        self, data_source: str, expected: FunctionCallArgs, functon_module_resources: ModuleResources
    ) -> None:
        environment_variables = {
            expected.client_id_env_name: expected.authentication.client_id,
            expected.client_secret_env_name: expected.authentication.client_secret,
        }
        actual = RunFunctionCommand._get_call_args(
            data_source, "fn_test3", functon_module_resources, environment_variables, is_interactive=False
        )

        assert actual == expected


class TestRunWorkflow:
    def test_run_workflow(self, cdf_tool_mock: CDFToolConfig, toolkit_client_approval: ApprovalToolkitClient):
        cdf_tool = MagicMock(spec=CDFToolConfig)
        cdf_tool.toolkit_client = toolkit_client_approval.mock_client
        cdf_tool.verify_authorization.return_value = toolkit_client_approval.mock_client
        toolkit_client_approval.mock_client.workflows.executions.run.return_value = WorkflowExecution(
            id="1234567890",
            workflow_external_id="workflow",
            status="running",
            created_time=int(datetime.now().timestamp() / 1000),
            version="v1",
        )

        assert (
            RunWorkflowCommand().run_workflow(
                cdf_tool_mock,
                organization_dir=RUN_DATA,
                build_env_name="dev",
                external_id="workflow",
                version="v1",
                wait=False,
            )
            is True
        )
