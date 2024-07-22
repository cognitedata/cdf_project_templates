from __future__ import annotations

from cognite.client.data_classes import Function, Transformation

from cognite_toolkit._api import CogniteToolkit
from cognite_toolkit._cdf_tk.utils import CDFToolConfig
from tests.tests_unit.approval_client import ApprovalCogniteClient


class TestRunAPI:
    def test_run_transformation(
        self,
        cognite_toolkit: CogniteToolkit,
        cognite_client_approval: ApprovalCogniteClient,
        cdf_tool_config: CDFToolConfig,
    ) -> None:
        transformation = Transformation(
            name="Test transformation",
            external_id="test",
            query="SELECT * FROM timeseries",
        )
        cognite_client_approval.append(Transformation, transformation)

        result = cognite_toolkit.run.transformation("test")

        assert result is True

    def test_run_function(
        self,
        cognite_toolkit: CogniteToolkit,
        cognite_client_approval: ApprovalCogniteClient,
        cdf_tool_config: CDFToolConfig,
    ) -> None:
        function = Function(
            id=1234567890,
            name="Test function",
            external_id="test",
            description="Test function",
            owner="test",
            status="RUNNING",
            file_id=1234567890,
            function_path="./handler.py",
            created_time=1234567890,
            secrets={"my_secret": "a_secret,"},
        )
        cognite_client_approval.append(Function, function)

        result = cognite_toolkit.run.function("test", {"payload": "test"})

        assert result is True
