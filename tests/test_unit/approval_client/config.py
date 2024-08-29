from __future__ import annotations

from cognite.client.data_classes import (
    Asset,
    AssetList,
    AssetWrite,
    AssetWriteList,
    Database,
    DatabaseList,
    DatabaseWrite,
    DatabaseWriteList,
    Datapoints,
    DatapointsList,
    DatapointSubscription,
    DatapointSubscriptionList,
    DataPointSubscriptionWrite,
    DatapointSubscriptionWriteList,
    DataSet,
    DataSetList,
    DataSetWrite,
    DataSetWriteList,
    ExtractionPipeline,
    ExtractionPipelineConfig,
    ExtractionPipelineConfigWrite,
    ExtractionPipelineConfigWriteList,
    ExtractionPipelineList,
    ExtractionPipelineWrite,
    ExtractionPipelineWriteList,
    FileMetadata,
    FileMetadataList,
    FileMetadataWrite,
    FileMetadataWriteList,
    Function,
    FunctionList,
    FunctionSchedule,
    FunctionSchedulesList,
    FunctionScheduleWrite,
    FunctionScheduleWriteList,
    FunctionWrite,
    FunctionWriteList,
    Group,
    GroupList,
    GroupWrite,
    GroupWriteList,
    LabelDefinition,
    LabelDefinitionList,
    LabelDefinitionWrite,
    Row,
    RowList,
    RowWrite,
    RowWriteList,
    SecurityCategory,
    SecurityCategoryList,
    SecurityCategoryWrite,
    SecurityCategoryWriteList,
    Table,
    TableList,
    TableWrite,
    TableWriteList,
    ThreeDModel,
    ThreeDModelList,
    ThreeDModelWrite,
    ThreeDModelWriteList,
    TimeSeries,
    TimeSeriesList,
    TimeSeriesWrite,
    TimeSeriesWriteList,
    Transformation,
    TransformationList,
    TransformationNotification,
    TransformationNotificationList,
    TransformationSchedule,
    TransformationScheduleList,
    TransformationScheduleWrite,
    TransformationScheduleWriteList,
    TransformationWrite,
    TransformationWriteList,
    Workflow,
    WorkflowList,
    WorkflowUpsert,
    WorkflowUpsertList,
    WorkflowVersion,
    WorkflowVersionList,
    WorkflowVersionUpsert,
    WorkflowVersionUpsertList,
)
from cognite.client.data_classes.data_modeling import (
    Container,
    ContainerApply,
    ContainerApplyList,
    ContainerList,
    DataModel,
    DataModelApply,
    DataModelApplyList,
    DataModelList,
    Node,
    NodeApply,
    NodeApplyList,
    NodeList,
    Space,
    SpaceApply,
    SpaceApplyList,
    SpaceList,
    View,
    ViewApply,
    ViewApplyList,
    ViewList,
)
from cognite.client.data_classes.extractionpipelines import ExtractionPipelineConfigList
from cognite.client.data_classes.iam import TokenInspection
from cognite.client.data_classes.labels import LabelDefinitionWriteList
from cognite.client.data_classes.transformations.notifications import (
    TransformationNotificationWrite,
    TransformationNotificationWriteList,
)

from cognite_toolkit._cdf_tk.client.data_classes import (
    locations,
    robotics,
)

from .data_classes import APIResource, Method

# This is used to define the resources that should be mocked in the ApprovalCogniteClient
# You can add more resources here if you need to mock more resources
API_RESOURCES = [
    APIResource(
        api_name="post",
        resource_cls=TokenInspection,
        list_cls=list[TokenInspection],
        methods={
            "post": [Method(api_class_method="post", mock_class_method="post_method")],
        },
    ),
    APIResource(
        api_name="iam.groups",
        resource_cls=Group,
        _write_cls=GroupWrite,
        _write_list_cls=GroupWriteList,
        list_cls=GroupList,
        methods={
            "create": [Method(api_class_method="create", mock_class_method="create")],
            "delete": [Method(api_class_method="delete", mock_class_method="delete_id_external_id")],
            "retrieve": [Method(api_class_method="list", mock_class_method="return_values")],
        },
    ),
    APIResource(
        api_name="iam.token",
        resource_cls=TokenInspection,
        list_cls=list[TokenInspection],
        methods={
            "inspect": [Method(api_class_method="inspect", mock_class_method="return_value")],
        },
    ),
    APIResource(
        api_name="data_sets",
        resource_cls=DataSet,
        _write_cls=DataSetWrite,
        _write_list_cls=DataSetWriteList,
        list_cls=DataSetList,
        methods={
            "create": [Method(api_class_method="create", mock_class_method="create")],
            "retrieve": [
                Method(api_class_method="list", mock_class_method="return_values"),
                Method(api_class_method="retrieve", mock_class_method="return_value"),
                Method(api_class_method="retrieve_multiple", mock_class_method="return_values"),
            ],
        },
    ),
    APIResource(
        api_name="time_series",
        resource_cls=TimeSeries,
        _write_cls=TimeSeriesWrite,
        list_cls=TimeSeriesList,
        _write_list_cls=TimeSeriesWriteList,
        methods={
            "create": [Method(api_class_method="create", mock_class_method="create")],
            "delete": [Method(api_class_method="delete", mock_class_method="delete_id_external_id")],
            "retrieve": [
                Method(api_class_method="list", mock_class_method="return_values"),
                Method(api_class_method="retrieve", mock_class_method="return_values"),
                Method(api_class_method="retrieve_multiple", mock_class_method="return_values"),
            ],
        },
    ),
    APIResource(
        api_name="raw.databases",
        resource_cls=Database,
        _write_cls=DatabaseWrite,
        list_cls=DatabaseList,
        _write_list_cls=DatabaseWriteList,
        methods={
            "create": [Method(api_class_method="create", mock_class_method="create")],
            "retrieve": [Method(api_class_method="list", mock_class_method="return_values")],
            "delete": [Method(api_class_method="delete", mock_class_method="delete_raw")],
        },
    ),
    APIResource(
        api_name="raw.tables",
        resource_cls=Table,
        _write_cls=TableWrite,
        list_cls=TableList,
        _write_list_cls=TableWriteList,
        methods={
            "create": [Method(api_class_method="create", mock_class_method="create")],
            "retrieve": [Method(api_class_method="list", mock_class_method="return_values")],
            "delete": [Method(api_class_method="delete", mock_class_method="delete_raw")],
        },
    ),
    APIResource(
        api_name="raw.rows",
        resource_cls=Row,
        _write_cls=RowWrite,
        list_cls=RowList,
        _write_list_cls=RowWriteList,
        methods={
            "create": [Method(api_class_method="insert_dataframe", mock_class_method="insert_dataframe")],
            "delete": [Method(api_class_method="delete", mock_class_method="delete_raw")],
            "retrieve": [
                Method(api_class_method="list", mock_class_method="return_values"),
                Method(api_class_method="retrieve", mock_class_method="return_values"),
            ],
        },
    ),
    APIResource(
        api_name="functions",
        resource_cls=Function,
        _write_cls=FunctionWrite,
        list_cls=FunctionList,
        _write_list_cls=FunctionWriteList,
        methods={
            "create": [Method(api_class_method="create", mock_class_method="create")],
            "delete": [Method(api_class_method="delete", mock_class_method="delete_id_external_id")],
            "retrieve": [
                Method(api_class_method="list", mock_class_method="return_values"),
                Method(api_class_method="retrieve", mock_class_method="return_value"),
                Method(api_class_method="retrieve_multiple", mock_class_method="return_values"),
            ],
        },
    ),
    APIResource(
        api_name="functions.schedules",
        resource_cls=FunctionSchedule,
        _write_cls=FunctionScheduleWrite,
        list_cls=FunctionSchedulesList,
        _write_list_cls=FunctionScheduleWriteList,
        methods={
            "create": [Method(api_class_method="create", mock_class_method="create")],
        },
    ),
    APIResource(
        api_name="transformations",
        resource_cls=Transformation,
        _write_cls=TransformationWrite,
        list_cls=TransformationList,
        _write_list_cls=TransformationWriteList,
        methods={
            "create": [Method(api_class_method="create", mock_class_method="create")],
            "delete": [Method(api_class_method="delete", mock_class_method="delete_id_external_id")],
            "retrieve": [
                Method(api_class_method="list", mock_class_method="return_values"),
                Method(api_class_method="retrieve", mock_class_method="return_value"),
                Method(api_class_method="retrieve_multiple", mock_class_method="return_values"),
            ],
        },
    ),
    APIResource(
        api_name="transformations.schedules",
        resource_cls=TransformationSchedule,
        _write_cls=TransformationScheduleWrite,
        list_cls=TransformationScheduleList,
        _write_list_cls=TransformationScheduleWriteList,
        methods={
            "create": [Method(api_class_method="create", mock_class_method="create")],
            "delete": [Method(api_class_method="delete", mock_class_method="delete_id_external_id")],
            "retrieve": [
                Method(api_class_method="list", mock_class_method="return_values"),
                Method(api_class_method="retrieve", mock_class_method="return_value"),
            ],
        },
    ),
    APIResource(
        api_name="extraction_pipelines",
        resource_cls=ExtractionPipeline,
        _write_cls=ExtractionPipelineWrite,
        list_cls=ExtractionPipelineList,
        _write_list_cls=ExtractionPipelineWriteList,
        methods={
            "create": [Method(api_class_method="create", mock_class_method="create")],
            "delete": [Method(api_class_method="delete", mock_class_method="delete_id_external_id")],
            "retrieve": [
                Method(api_class_method="list", mock_class_method="return_values"),
                Method(api_class_method="retrieve", mock_class_method="return_value"),
                Method(api_class_method="retrieve_multiple", mock_class_method="return_values"),
            ],
        },
    ),
    APIResource(
        api_name="extraction_pipelines.config",
        resource_cls=ExtractionPipelineConfig,
        _write_cls=ExtractionPipelineConfigWrite,
        list_cls=ExtractionPipelineConfigList,
        _write_list_cls=ExtractionPipelineConfigWriteList,
        methods={
            "create": [Method(api_class_method="create", mock_class_method="create_extraction_pipeline_config")],
            "retrieve": [
                Method(api_class_method="list", mock_class_method="return_values"),
                Method(api_class_method="retrieve", mock_class_method="return_value"),
            ],
        },
    ),
    APIResource(
        api_name="data_modeling.containers",
        resource_cls=Container,
        list_cls=ContainerList,
        _write_cls=ContainerApply,
        _write_list_cls=ContainerApplyList,
        methods={
            "create": [Method(api_class_method="apply", mock_class_method="create")],
            "delete": [Method(api_class_method="delete", mock_class_method="delete_data_modeling")],
            "retrieve": [
                Method(api_class_method="list", mock_class_method="return_values"),
                Method(api_class_method="retrieve", mock_class_method="return_values"),
            ],
        },
    ),
    APIResource(
        api_name="data_modeling.views",
        resource_cls=View,
        list_cls=ViewList,
        _write_cls=ViewApply,
        _write_list_cls=ViewApplyList,
        methods={
            "create": [Method(api_class_method="apply", mock_class_method="create")],
            "delete": [Method(api_class_method="delete", mock_class_method="delete_data_modeling")],
            "retrieve": [
                Method(api_class_method="list", mock_class_method="return_values"),
                Method(api_class_method="retrieve", mock_class_method="data_model_retrieve"),
            ],
        },
    ),
    APIResource(
        api_name="data_modeling.data_models",
        resource_cls=DataModel,
        list_cls=DataModelList,
        _write_cls=DataModelApply,
        _write_list_cls=DataModelApplyList,
        methods={
            "create": [Method(api_class_method="apply", mock_class_method="create")],
            "delete": [Method(api_class_method="delete", mock_class_method="delete_data_modeling")],
            "retrieve": [
                Method(api_class_method="list", mock_class_method="return_values"),
                Method(api_class_method="retrieve", mock_class_method="return_values"),
            ],
        },
    ),
    APIResource(
        api_name="data_modeling.spaces",
        resource_cls=Space,
        list_cls=SpaceList,
        _write_cls=SpaceApply,
        _write_list_cls=SpaceApplyList,
        methods={
            "create": [Method(api_class_method="apply", mock_class_method="create")],
            "delete": [Method(api_class_method="delete", mock_class_method="delete_space")],
            "retrieve": [
                Method(api_class_method="list", mock_class_method="return_values"),
                Method(api_class_method="retrieve", mock_class_method="return_values"),
            ],
        },
    ),
    APIResource(
        api_name="time_series.data",
        resource_cls=Datapoints,
        list_cls=DatapointsList,
        methods={
            "create": [
                Method(api_class_method="insert", mock_class_method="create"),
                Method(api_class_method="insert_dataframe", mock_class_method="insert_dataframe"),
            ],
        },
    ),
    APIResource(
        api_name="files",
        resource_cls=FileMetadata,
        list_cls=FileMetadataList,
        _write_cls=FileMetadataWrite,
        _write_list_cls=FileMetadataWriteList,
        methods={
            "create": [
                Method(api_class_method="upload", mock_class_method="upload"),
                Method(api_class_method="create", mock_class_method="create"),
                # This is used by functions to upload the file used for deployment.
                Method(api_class_method="upload_bytes", mock_class_method="upload_bytes_files_api"),
            ],
            "delete": [Method(api_class_method="delete", mock_class_method="delete_id_external_id")],
            "retrieve": [
                Method(api_class_method="list", mock_class_method="return_values"),
                Method(api_class_method="retrieve", mock_class_method="files_retrieve"),
                Method(api_class_method="retrieve_multiple", mock_class_method="return_values"),
            ],
        },
    ),
    APIResource(
        api_name="data_modeling.instances",
        resource_cls=Node,
        list_cls=NodeList,
        _write_cls=NodeApply,
        _write_list_cls=NodeApplyList,
        methods={
            "create": [Method(api_class_method="apply", mock_class_method="create_instances")],
            "delete": [Method(api_class_method="delete", mock_class_method="delete_instances")],
            "retrieve": [
                Method(api_class_method="list", mock_class_method="return_values"),
                Method(api_class_method="retrieve", mock_class_method="return_instances"),
            ],
        },
    ),
    APIResource(
        api_name="workflows",
        resource_cls=Workflow,
        list_cls=WorkflowList,
        _write_cls=WorkflowUpsert,
        _write_list_cls=WorkflowUpsertList,
        methods={
            "create": [Method(api_class_method="upsert", mock_class_method="upsert")],
            # "update": [Method(api_class_method="upsert", mock_name="upsert")],
            # "delete": [Method(api_class_method="delete", mock_name="delete_id_external_id")],
            "retrieve": [
                Method(api_class_method="retrieve", mock_class_method="return_value"),
            ],
        },
    ),
    APIResource(
        api_name="workflows.versions",
        resource_cls=WorkflowVersion,
        list_cls=WorkflowVersionList,
        _write_cls=WorkflowVersionUpsert,
        _write_list_cls=WorkflowVersionUpsertList,
        methods={
            "create": [Method(api_class_method="upsert", mock_class_method="upsert")],
            # "update": [Method(api_class_method="upsert", mock_name="upsert")],
            # "delete": [Method(api_class_method="delete", mock_name="delete")],
            "retrieve": [
                Method(api_class_method="retrieve", mock_class_method="return_value"),
            ],
        },
    ),
    APIResource(
        api_name="iam.security_categories",
        resource_cls=SecurityCategory,
        list_cls=SecurityCategoryList,
        _write_cls=SecurityCategoryWrite,
        _write_list_cls=SecurityCategoryWriteList,
        methods={
            "create": [Method(api_class_method="create", mock_class_method="create")],
            "retrieve": [Method(api_class_method="list", mock_class_method="return_values")],
        },
    ),
    APIResource(
        api_name="time_series.subscriptions",
        resource_cls=DatapointSubscription,
        list_cls=DatapointSubscriptionList,
        _write_cls=DataPointSubscriptionWrite,
        _write_list_cls=DatapointSubscriptionWriteList,
        methods={
            "create": [Method(api_class_method="create", mock_class_method="create")],
            "retrieve": [
                Method(api_class_method="retrieve", mock_class_method="return_value"),
            ],
        },
    ),
    APIResource(
        api_name="labels",
        resource_cls=LabelDefinition,
        list_cls=LabelDefinitionList,
        _write_cls=LabelDefinitionWrite,
        _write_list_cls=LabelDefinitionWriteList,
        methods={
            "create": [Method(api_class_method="create", mock_class_method="create")],
            "retrieve": [Method(api_class_method="list", mock_class_method="return_values")],
        },
    ),
    APIResource(
        api_name="transformations.notifications",
        resource_cls=TransformationNotification,
        list_cls=TransformationNotificationList,
        _write_cls=TransformationNotificationWrite,
        _write_list_cls=TransformationNotificationWriteList,
        methods={
            "create": [Method(api_class_method="create", mock_class_method="create")],
            "retrieve": [Method(api_class_method="list", mock_class_method="return_values")],
        },
    ),
    APIResource(
        api_name="assets",
        resource_cls=Asset,
        list_cls=AssetList,
        _write_cls=AssetWrite,
        _write_list_cls=AssetWriteList,
        methods={
            "create": [Method(api_class_method="create", mock_class_method="create")],
            "retrieve": [
                Method(api_class_method="list", mock_class_method="return_values"),
                Method(api_class_method="retrieve_multiple", mock_class_method="return_values"),
            ],
        },
    ),
    APIResource(
        api_name="three_d.models",
        resource_cls=ThreeDModel,
        list_cls=ThreeDModelList,
        _write_cls=ThreeDModelWrite,
        _write_list_cls=ThreeDModelWriteList,
        methods={
            "create": [Method(api_class_method="create", mock_class_method="create_3dmodel")],
            "retrieve": [
                Method(api_class_method="__iter__", mock_class_method="iterate_values"),
            ],
        },
    ),
    APIResource(
        api_name="robotics.data_postprocessing",
        resource_cls=robotics.DataPostProcessing,
        list_cls=robotics.DataPostProcessingList,
        _write_cls=robotics.DataPostProcessingWrite,
        _write_list_cls=robotics.DataPostProcessingWriteList,
        methods={
            "create": [Method(api_class_method="create", mock_class_method="create")],
            "retrieve": [
                Method(api_class_method="retrieve", mock_class_method="return_values"),
            ],
        },
    ),
    APIResource(
        api_name="robotics.frames",
        resource_cls=robotics.Frame,
        list_cls=robotics.FrameList,
        _write_cls=robotics.FrameWrite,
        _write_list_cls=robotics.FrameWriteList,
        methods={
            "create": [Method(api_class_method="create", mock_class_method="create")],
            "retrieve": [
                Method(api_class_method="retrieve", mock_class_method="return_values"),
            ],
        },
    ),
    APIResource(
        api_name="robotics.locations",
        resource_cls=robotics.Location,
        list_cls=robotics.LocationList,
        _write_cls=robotics.LocationWrite,
        _write_list_cls=robotics.LocationWriteList,
        methods={
            "create": [Method(api_class_method="create", mock_class_method="create")],
            "retrieve": [
                Method(api_class_method="retrieve", mock_class_method="return_values"),
            ],
        },
    ),
    APIResource(
        api_name="robotics.maps",
        resource_cls=robotics.Map,
        list_cls=robotics.MapList,
        _write_cls=robotics.MapWrite,
        _write_list_cls=robotics.MapWriteList,
        methods={
            "create": [Method(api_class_method="create", mock_class_method="create")],
            "retrieve": [
                Method(api_class_method="retrieve", mock_class_method="return_values"),
            ],
        },
    ),
    APIResource(
        api_name="robotics.capabilities",
        resource_cls=robotics.RobotCapability,
        list_cls=robotics.RobotCapabilityList,
        _write_cls=robotics.RobotCapabilityWrite,
        _write_list_cls=robotics.RobotCapabilityWriteList,
        methods={
            "create": [Method(api_class_method="create", mock_class_method="create")],
            "retrieve": [
                Method(api_class_method="retrieve", mock_class_method="return_values"),
            ],
        },
    ),
    APIResource(
        api_name="locations",
        resource_cls=locations.LocationFilter,
        list_cls=locations.LocationFilterList,
        _write_cls=locations.LocationFilterWrite,
        _write_list_cls=locations.LocationFilterWriteList,
        methods={
            "create": [Method(api_class_method="create", mock_class_method="create")],
            "retrieve": [
                Method(api_class_method="retrieve", mock_class_method="return_values"),
            ],
        },
    ),
    APIResource(
        api_name="location_filters",
        resource_cls=locations.LocationFilter,
        list_cls=locations.LocationFilterList,
        _write_cls=locations.LocationFilterWrite,
        _write_list_cls=locations.LocationFilterWriteList,
        methods={
            "create": [Method(api_class_method="create", mock_class_method="create")],
            "retrieve": [
                Method(api_class_method="retrieve", mock_class_method="return_values"),
            ],
        },
    ),
]
