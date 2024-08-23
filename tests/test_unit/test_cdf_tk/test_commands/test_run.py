from datetime import datetime
from unittest.mock import MagicMock

from cognite.client.data_classes.functions import Function
from cognite.client.data_classes.transformations import Transformation

from cognite_toolkit._cdf_tk.commands import RunFunctionCommand, RunTransformationCommand
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


def test_run_transformation(toolkit_client_approval: ApprovalToolkitClient):
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


def test_run_function(toolkit_client_approval: ApprovalToolkitClient):
    cdf_tool = MagicMock(spec=CDFToolConfig)
    cdf_tool.toolkit_client = toolkit_client_approval.mock_client
    cdf_tool.verify_authorization.return_value = toolkit_client_approval.mock_client
    function = Function(
        id=1234567890,
        name="Test function",
        external_id="test",
        description="Test function",
        owner="test",
        status="RUNNING",
        file_id=1234567890,
        function_path="./handler.py",
        created_time=int(datetime.now().timestamp() / 1000),
        secrets={"my_secret": "a_secret,"},
    )
    toolkit_client_approval.append(Function, function)
    assert (
        RunFunctionCommand().run_function(cdf_tool, external_id="test", payload='{"var1": "value"}', follow=False)
        is True
    )
    cdf_tool.toolkit_client.functions.calls.get_response.return_value = {}
    assert (
        RunFunctionCommand().run_function(cdf_tool, external_id="test", payload='{"var1": "value"}', follow=True)
        is True
    )


def test_run_local_function(toolkit_client_approval: ApprovalToolkitClient) -> None:
    cdf_tool = MagicMock(spec=CDFToolConfig)
    cdf_tool.toolkit_client = toolkit_client_approval.mock_client
    cdf_tool.verify_authorization.return_value = toolkit_client_approval.mock_client
    function = Function(
        id=1234567890,
        name="Test function",
        external_id="fn_test2",
        description="Test function",
        owner="test",
        status="RUNNING",
        file_id=1234567890,
        function_path="./handler.py",
        created_time=int(datetime.now().timestamp() / 1000),
    )
    toolkit_client_approval.append(Function, function)

    cmd = RunFunctionCommand()

    result = cmd.run_local_function(
        ToolGlobals=cdf_tool,
        source_path=RUN_DATA,
        rebuild_env=True,
        build_env_name="dev",
        external_id="fn_test2",
        payload='{"var1": "value"}',
    )

    assert result is True
