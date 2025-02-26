from asyncio import sleep

import pytest
from cognite.client import CogniteClient
from cognite.client import data_modeling as dm
from cognite.client.credentials import OAuthClientCredentials
from cognite.client.data_classes import (
    AssetWrite,
    AssetWriteList,
    ClientCredentials,
    DataPointSubscriptionWrite,
    Function,
    FunctionSchedule,
    FunctionSchedulesList,
    FunctionScheduleWrite,
    FunctionScheduleWriteList,
    LabelDefinitionWrite,
    filters,
)
from cognite.client.data_classes.data_modeling.cdm.v1 import CogniteFileApply
from cognite.client.data_classes.datapoints_subscriptions import (
    DatapointSubscriptionProperty,
    DatapointSubscriptionWriteList,
)
from cognite.client.data_classes.labels import LabelDefinitionWriteList
from cognite.client.exceptions import CogniteAPIError

from cognite_toolkit._cdf_tk.client import ToolkitClient, ToolkitClientConfig
from cognite_toolkit._cdf_tk.client.data_classes.extendable_cognite_file import (
    ExtendableCogniteFileApply,
    ExtendableCogniteFileApplyList,
)
from cognite_toolkit._cdf_tk.client.data_classes.robotics import (
    DataPostProcessingWrite,
    DataPostProcessingWriteList,
    RobotCapability,
    RobotCapabilityWrite,
    RobotCapabilityWriteList,
)
from cognite_toolkit._cdf_tk.loaders import (
    AssetLoader,
    CogniteFileLoader,
    DataModelLoader,
    DatapointSubscriptionLoader,
    FunctionScheduleLoader,
    LabelLoader,
    RobotCapabilityLoader,
    RoboticsDataPostProcessingLoader,
    ViewLoader,
)
from tests.test_integration.constants import RUN_UNIQUE_ID


@pytest.fixture
def dummy_function(cognite_client: CogniteClient) -> Function:
    external_id = "integration_test_function_dummy"

    if existing := cognite_client.functions.retrieve(external_id=external_id):
        return existing

    def handle(client: CogniteClient, data: dict, function_call_info: dict) -> str:
        """
        [requirements]
        cognite-sdk>=7.37.0
        [/requirements]
        """
        print("Print statements will be shown in the logs.")
        print("Running with the following configuration:\n")
        return {
            "data": data,
            "functionInfo": function_call_info,
        }

    return cognite_client.functions.create(
        name="integration_test_function_dummy",
        function_handle=handle,
        external_id="integration_test_function_dummy",
    )


@pytest.fixture
def dummy_schedule(cognite_client: CogniteClient, dummy_function: Function) -> FunctionSchedule:
    name = "integration_test_schedule_dummy"
    if existing_list := cognite_client.functions.schedules.list(name=name):
        if len(existing_list) > 1:
            for existing in existing_list[1:]:
                cognite_client.functions.schedules.delete(existing.id)
        schedule = existing_list[0]
    else:
        schedule = cognite_client.functions.schedules.create(
            name=name,
            cron_expression="0 7 * * MON",
            description="Original description.",
            function_external_id=dummy_function.external_id,
        )
    if schedule.function_external_id is None:
        schedule.function_external_id = dummy_function.external_id
    if schedule.function_id is not None:
        schedule.function_id = None
    return schedule


class TestFunctionScheduleLoader:
    # The function schedule service is fairly unstable, so we need to rerun the tests if they fail.
    @pytest.mark.flaky(reruns=3, reruns_delay=10, only_rerun=["AssertionError"])
    def test_update_function_schedule(
        self,
        toolkit_client: ToolkitClient,
        toolkit_client_config: ToolkitClientConfig,
        dummy_function: Function,
        dummy_schedule: FunctionSchedule,
    ) -> None:
        loader = FunctionScheduleLoader(toolkit_client, None, None)
        function_schedule = dummy_schedule.as_write()

        function_schedule.description = (
            "Updated description."
            if function_schedule.description != "Updated description."
            else "Original description."
        )
        identifier = loader.get_id(function_schedule)
        assert isinstance(toolkit_client_config.credentials, OAuthClientCredentials)
        loader.authentication_by_id[identifier] = ClientCredentials(
            toolkit_client_config.credentials.client_id, toolkit_client_config.credentials.client_secret
        )

        # Function schedules cannot be updated, they must be deleted and recreated.
        loader.delete([identifier])
        loader.create(FunctionScheduleWriteList([function_schedule]))

        retrieved = loader.retrieve([identifier])
        if not retrieved or retrieved[0].description != function_schedule.description:
            # The service can be a bit slow in returning the updated description,
            # so we wait a bit and try again. (Eventual consistency)
            sleep(2)
            retrieved = loader.retrieve([identifier])

        assert retrieved, "Function schedule not found after update."
        assert retrieved[0].description == function_schedule.description

    def test_creating_schedule_then_print_ids(
        self, toolkit_client: ToolkitClient, toolkit_client_config: ToolkitClientConfig, dummy_function: Function
    ) -> None:
        local = FunctionScheduleWrite(
            name="test_creating_schedule_then_print_ids",
            cron_expression="0 7 * * TUE",
            function_external_id=dummy_function.external_id,
            description="This schedule should be ignored as it does not have a function_external_id",
        )
        loader = FunctionScheduleLoader(toolkit_client, None, None)
        assert isinstance(toolkit_client_config.credentials, OAuthClientCredentials)
        loader.authentication_by_id[loader.get_id(local)] = ClientCredentials(
            toolkit_client_config.credentials.client_id, toolkit_client_config.credentials.client_secret
        )

        created: FunctionSchedulesList | None = None
        try:
            created = loader.create(FunctionScheduleWriteList([local]))
            loader.get_ids(created)
        finally:
            if created:
                toolkit_client.functions.schedules.delete(created[0].id)


class TestDatapointSubscriptionLoader:
    def test_delete_non_existing(self, cognite_client: CogniteClient) -> None:
        loader = DatapointSubscriptionLoader(cognite_client, None)
        delete_count = loader.delete(["non_existing"])
        assert delete_count == 0

    def test_create_update_delete_subscription(self, cognite_client: CogniteClient) -> None:
        sub = DataPointSubscriptionWrite(
            external_id=f"tmp_test_create_update_delete_subscription_{RUN_UNIQUE_ID}",
            partition_count=1,
            name="Initial name",
            filter=filters.Prefix(DatapointSubscriptionProperty.external_id, "ts_value"),
        )
        update = DataPointSubscriptionWrite(
            external_id=f"tmp_test_create_update_delete_subscription_{RUN_UNIQUE_ID}",
            partition_count=1,
            name="Updated name",
            filter=filters.Prefix(DatapointSubscriptionProperty.external_id, "ts_value"),
        )

        loader = DatapointSubscriptionLoader(cognite_client, None)

        try:
            created = loader.create(DatapointSubscriptionWriteList([sub]))
            assert len(created) == 1

            updated = loader.update(DatapointSubscriptionWriteList([update]))
            assert len(updated) == 1
            assert updated[0].name == "Updated name"
        finally:
            loader.delete([sub.external_id])


class TestLabelLoader:
    def test_delete_non_existing(self, cognite_client: CogniteClient) -> None:
        loader = LabelLoader(cognite_client, None)
        delete_count = loader.delete(["non_existing"])
        assert delete_count == 0

    def test_create_update_delete_label(self, cognite_client: CogniteClient) -> None:
        initial = LabelDefinitionWrite(
            external_id=f"tmp_test_create_update_delete_label_{RUN_UNIQUE_ID}",
            name="Initial name",
        )
        update = LabelDefinitionWrite(
            external_id=f"tmp_test_create_update_delete_label_{RUN_UNIQUE_ID}",
            name="Updated name",
        )

        loader = LabelLoader(cognite_client, None)

        try:
            created = loader.create(LabelDefinitionWriteList([initial]))
            assert len(created) == 1

            updated = loader.update(LabelDefinitionWriteList([update]))
            assert len(updated) == 1
            assert updated[0].name == "Updated name"
        finally:
            loader.delete([initial.external_id])


class TestAssetLoader:
    def test_create_delete_asset(self, cognite_client: CogniteClient) -> None:
        asset = AssetWrite(
            external_id=f"tmp_test_create_delete_asset_{RUN_UNIQUE_ID}",
            name="My Asset",
            description="My description",
        )

        loader = AssetLoader(cognite_client, None)

        try:
            created = loader.create(AssetWriteList([asset]))
            assert len(created) == 1

            delete_count = loader.delete([asset.external_id])
            assert delete_count == 1
        finally:
            # Ensure that the asset is deleted even if the test fails.
            cognite_client.assets.delete(external_id=asset.external_id, ignore_unknown_ids=True)


@pytest.fixture
def existing_robot_capability(toolkit_client: ToolkitClient) -> RobotCapability:
    write = RobotCapabilityWrite(
        name="integration_test_robot_capability",
        description="Test robot capability",
        external_id="integration_test_robot_capability",
        method="ptz",
        input_schema={},
        data_handling_schema={},
    )

    try:
        return toolkit_client.robotics.capabilities.retrieve(write.external_id)
    except CogniteAPIError:
        return toolkit_client.robotics.capabilities.create(write)


class TestRobotCapability:
    def test_retrieve_existing_and_not_existing(
        self, toolkit_client: ToolkitClient, existing_robot_capability: RobotCapability
    ) -> None:
        loader = RobotCapabilityLoader(toolkit_client, None)

        capabilities = loader.retrieve([existing_robot_capability.external_id, "non_existing_robot"])

        assert len(capabilities) == 1

    def test_create_update_retrieve_delete(self, toolkit_client: ToolkitClient) -> None:
        loader = RobotCapabilityLoader(toolkit_client, None)

        original = RobotCapabilityWrite.load("""name: Read dial gauge
externalId: read_dial_gauge
method: read_dial_gauge
description: Original Description
inputSchema:
    $schema: http://json-schema.org/draft-07/schema#
    id: robotics/schemas/0.1.0/capabilities/ptz
    title: PTZ camera capability input
dataHandlingSchema:
    $schema: http://json-schema.org/draft-07/schema#
    id: robotics/schemas/0.1.0/data_handling/read_dial_gauge
    title: Read dial gauge data handling
""")

        update = RobotCapabilityWrite.load("""name: Read dial gauge
externalId: read_dial_gauge
method: read_dial_gauge
description: Original Description
inputSchema:
    $schema: http://json-schema.org/draft-07/schema#
    id: robotics/schemas/0.2.0/capabilities/ptz
    title: Updated PTZ camera capability input
dataHandlingSchema:
    $schema: http://json-schema.org/draft-07/schema#
    id: robotics/schemas/0.2.0/data_handling/read_dial_gauge
    title: Updated read dial gauge data handling
""")
        try:
            created = loader.create(RobotCapabilityWriteList([original]))
            assert len(created) == 1

            updated = loader.update(RobotCapabilityWriteList([update]))
            assert len(updated) == 1
            assert updated[0].input_schema == update.input_schema

            retrieved = loader.retrieve([original.external_id])
            assert len(retrieved) == 1
            assert retrieved[0].input_schema == update.input_schema
        finally:
            loader.delete([original.external_id])


class TestRobotDataPostProcessing:
    def test_create_update_retrieve_delete(self, toolkit_client: ToolkitClient) -> None:
        loader = RoboticsDataPostProcessingLoader(toolkit_client, None)

        original = DataPostProcessingWrite.load("""name: Read dial gauge
externalId: read_dial_gauge
method: read_dial_gauge
description: Original Description
inputSchema:
  $schema: http://json-schema.org/draft-07/schema#
  id: robotics/schemas/0.1.0/capabilities/ptz
  title: PTZ camera capability input
  type: object
  properties:
    method:
      type: string
    parameters:
      type: object
      properties:
        tilt:
          type: number
          minimum: -90
          maximum: 90
        pan:
          type: number
          minimum: -180
          maximum: 180
        zoom:
          type: number
          minimum: 0
          maximum: 100
      required:
      - tilt
      - pan
      - zoom
  required:
  - method
  - parameters
  additionalProperties: false
""")

        update = DataPostProcessingWrite.load("""method: read_dial_gauge
name: Read dial gauge
externalId: read_dial_gauge
description: Read dial gauge from an image using Cognite Vision gauge reader
inputSchema:
  $schema: http://json-schema.org/draft-07/schema#
  id: robotics/schemas/0.1.0/data_postprocessing/read_dial_gauge
  title: Read dial gauge input
  type: object
  properties:
    image:
      type: object
      properties:
        method:
          type: string
        parameters:
          type: object
          properties:
            unit:
              type: string
            deadAngle:
              type: number
            minLevel:
              type: number
            maxLevel:
              type: number
      required:
        - method
        - parameters
      additionalProperties: false
  additionalProperties: false""")

        # Ensure the original is deleted even if the test fails
        loader.delete([original.external_id])

        try:
            created = loader.create(DataPostProcessingWriteList([original]))
            assert len(created) == 1

            updated = loader.update(DataPostProcessingWriteList([update]))
            assert len(updated) == 1
            assert updated[0].input_schema == update.input_schema

            retrieved = loader.retrieve([original.external_id])
            assert len(retrieved) == 1
            assert retrieved[0].input_schema == update.input_schema
        finally:
            loader.delete([original.external_id])


@pytest.fixture(scope="module")
def schema_space(toolkit_client: ToolkitClient) -> dm.Space:
    return toolkit_client.data_modeling.spaces.apply(
        dm.SpaceApply(
            space=f"sp_test_resource_loaders_{RUN_UNIQUE_ID}",
        )
    )


@pytest.fixture(scope="module")
def instance_space(toolkit_client: ToolkitClient) -> dm.Space:
    return toolkit_client.data_modeling.spaces.apply(
        dm.SpaceApply(
            space=f"sp_instances_{RUN_UNIQUE_ID}",
        )
    )


@pytest.fixture(scope="module")
def a_container(toolkit_client: ToolkitClient, schema_space: dm.Space) -> dm.Container:
    return toolkit_client.data_modeling.containers.apply(
        dm.ContainerApply(
            name=f"container_test_resource_loaders_{RUN_UNIQUE_ID}",
            space=schema_space.space,
            external_id=f"container_test_resource_loaders_{RUN_UNIQUE_ID}",
            properties={"name": dm.ContainerProperty(type=dm.Text())},
        )
    )


@pytest.fixture(scope="module")
def two_views(toolkit_client: ToolkitClient, schema_space: dm.Space, a_container: dm.Container) -> dm.ViewList:
    return toolkit_client.data_modeling.views.apply(
        [
            dm.ViewApply(
                space=schema_space.space,
                external_id="first_view",
                version="1",
                properties={
                    "name": dm.MappedPropertyApply(container=a_container.as_id(), container_property_identifier="name")
                },
            ),
            dm.ViewApply(
                space=schema_space.space,
                external_id="second_view",
                version="1",
                properties={
                    "alsoName": dm.MappedPropertyApply(
                        container=a_container.as_id(), container_property_identifier="name", name="name2"
                    )
                },
            ),
        ]
    )


class TestDataModelLoader:
    def test_create_update_delete(
        self, toolkit_client: ToolkitClient, schema_space: dm.Space, two_views: dm.ViewList
    ) -> None:
        loader = DataModelLoader(toolkit_client, None)
        view_list = two_views.as_ids()
        assert len(view_list) == 2, "Expected 2 views in the test data model"
        my_model = dm.DataModelApply(
            name="My model",
            description="Original description",
            views=view_list,
            space=schema_space.space,
            external_id=f"tmp_test_create_update_delete_data_model_{RUN_UNIQUE_ID}",
            version="1",
        )

        try:
            created = loader.create(dm.DataModelApplyList([my_model]))
            assert len(created) == 1

            update = dm.DataModelApply.load(my_model.dump())
            update.views = [view_list[0]]

            with pytest.raises(CogniteAPIError):
                loader.update(dm.DataModelApplyList([update]))
            # You need to update the version to update the model
            update.version = "2"

            updated = loader.update(dm.DataModelApplyList([update]))
            assert len(updated) == 1
            assert updated[0].views == [view_list[0]]
        finally:
            loader.delete([my_model.as_id()])


@pytest.fixture
def custom_file_container(toolkit_client: ToolkitClient, schema_space: dm.Space) -> dm.Container:
    return toolkit_client.data_modeling.containers.apply(
        dm.ContainerApply(
            name=f"container_test_resource_loaders_{RUN_UNIQUE_ID}",
            space=schema_space.space,
            external_id=f"container_test_resource_loaders_{RUN_UNIQUE_ID}",
            properties={
                "status": dm.ContainerProperty(type=dm.Text()),
                "fileCategory": dm.ContainerProperty(type=dm.Text()),
            },
        )
    )


@pytest.fixture
def cognite_file_extension(
    toolkit_client: ToolkitClient, custom_file_container: dm.Container, schema_space: dm.Space
) -> dm.View:
    container = custom_file_container.as_id()
    return toolkit_client.data_modeling.views.apply(
        dm.ViewApply(
            space=schema_space.space,
            external_id="CogniteFileExtension",
            version="v1",
            implements=[CogniteFileApply.get_source()],
            properties={
                "status": dm.MappedPropertyApply(container=container, container_property_identifier="status"),
                "fileCategory": dm.MappedPropertyApply(
                    container=container, container_property_identifier="fileCategory"
                ),
            },
        )
    )


class TestCogniteFileLoader:
    def test_create_update_retrieve_delete(self, toolkit_client: ToolkitClient, instance_space: dm.Space) -> None:
        loader = CogniteFileLoader(toolkit_client, None)
        # Loading from YAML to test the loading of extra properties as well
        file = ExtendableCogniteFileApply.load(f"""space: {instance_space.space}
externalId: tmp_test_create_update_delete_file_{RUN_UNIQUE_ID}
name: My file
description: Original description
""")
        try:
            created = loader.create(ExtendableCogniteFileApplyList([file]))
            assert len(created) == 1

            retrieved = loader.retrieve([file.as_id()])
            assert len(retrieved) == 1
            assert retrieved[0].name == "My file"
            assert retrieved[0].description == "Original description"

            update = ExtendableCogniteFileApply._load(file.dump(context="local"))
            update.description = "Updated description"

            updated = loader.update(ExtendableCogniteFileApplyList([update]))
            assert len(updated) == 1

            retrieved = loader.retrieve([file.as_id()])
            assert len(retrieved) == 1
            assert retrieved[0].description == "Updated description"
            assert retrieved[0].name == "My file"
        finally:
            loader.delete([file.as_id()])

    @pytest.mark.skip("For now, we do not support creating extensions")
    def test_create_update_retrieve_delete_extension(
        self, toolkit_client: ToolkitClient, cognite_file_extension: dm.View, instance_space: dm.Space
    ) -> None:
        loader = CogniteFileLoader(toolkit_client, None)
        view_id = cognite_file_extension.as_id()
        # Loading from YAML to test the loading of extra properties as well
        file = ExtendableCogniteFileApply.load(f"""space: {instance_space.space}
externalId: tmp_test_create_update_delete_file_extension_{RUN_UNIQUE_ID}
name: MyExtendedFile
description: Original description
nodeSource:
  space: {view_id.space}
  externalId: {view_id.external_id}
  version: {view_id.version}
  type: view
status: Active
fileCategory: Document
""")
        try:
            created = loader.create(ExtendableCogniteFileApplyList([file]))
            assert len(created) == 1

            update = ExtendableCogniteFileApply._load(file.dump(context="local"))
            # Ensure serialization and deserialization works
            assert update.name == "MyExtendedFile"
            assert update.extra_properties is not None
            assert update.extra_properties["fileCategory"] == "Document"
            update.extra_properties["status"] = "Inactive"

            updated = loader.update(ExtendableCogniteFileApplyList([update]))
            assert len(updated) == 1

            retrieved = loader.retrieve([file.as_id()])
            assert len(retrieved) == 1
            assert retrieved[0].name == "MyExtendedFile"
            assert retrieved[0].extra_properties is not None
            assert retrieved[0].extra_properties["status"] == "Inactive"
        finally:
            loader.delete([file.as_id()])


class TestViewLoader:
    def test_deploy_child_before_parent(
        self, toolkit_client: ToolkitClient, schema_space: dm.Space, a_container: dm.Container
    ) -> None:
        child_view = dm.ViewApply(
            space=schema_space.space,
            external_id="TestDeployChildBeforeParent_Child",
            version="v1",
            implements=[dm.ViewId(schema_space.space, "TestDeployChildBeforeParent_Parent", "v1")],
        )
        other_views = [
            dm.ViewApply(
                space=schema_space.space,
                external_id=f"TestDeployChildBeforeParent_Other_{i}",
                version="v1",
                properties={
                    "name": dm.MappedPropertyApply(container=a_container.as_id(), container_property_identifier="name")
                },
            )
            for i in range(10)
        ]

        parent_view = dm.ViewApply(
            space=schema_space.space,
            external_id="TestDeployChildBeforeParent_Parent",
            version="v1",
            properties={
                "name": dm.MappedPropertyApply(container=a_container.as_id(), container_property_identifier="name")
            },
            implements=[dm.ViewId("cdf_cdm", "CogniteDescribable", "v1")],
        )

        loader = ViewLoader.create_loader(toolkit_client, None)

        try:
            created = loader.create([child_view, *other_views, parent_view])

            assert len(created) == 2 + len(other_views)
        finally:
            toolkit_client.data_modeling.views.delete(
                [child_view.as_id(), parent_view.as_id()] + [view.as_id() for view in other_views]
            )
