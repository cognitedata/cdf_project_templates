from pathlib import Path
from unittest.mock import MagicMock

import pytest
import typer
import yaml
from cognite.client import data_modeling as dm
from cognite.client.data_classes import Transformation, TransformationWrite
from pytest import MonkeyPatch

from cognite_toolkit._cdf import build, deploy, dump_datamodel_cmd, pull_transformation_cmd
from cognite_toolkit._cdf_tk.load import TransformationLoader
from cognite_toolkit._cdf_tk.templates import build_config
from cognite_toolkit._cdf_tk.templates.data_classes import BuildConfigYAML, Environment, SystemYAML
from cognite_toolkit._cdf_tk.utils import CDFToolConfig
from tests.tests_unit.approval_client import ApprovalCogniteClient
from tests.tests_unit.test_cdf_tk.constants import CUSTOM_PROJECT, PROJECT_WITH_DUPLICATES, PYTEST_PROJECT
from tests.tests_unit.utils import PrintCapture, mock_read_yaml_file


def test_inject_custom_environmental_variables(
    local_tmp_path: Path,
    monkeypatch: MonkeyPatch,
    cognite_client_approval: ApprovalCogniteClient,
    cdf_tool_config: CDFToolConfig,
    typer_context: typer.Context,
    init_project: Path,
) -> None:
    config_yaml = yaml.safe_load((init_project / "config.dev.yaml").read_text())
    config_yaml["variables"]["cognite_modules"]["cicd_clientId"] = "${MY_ENVIRONMENT_VARIABLE}"
    # Selecting a module with a transformation that uses the cicd_clientId variable
    config_yaml["environment"]["selected_modules_and_packages"] = ["cdf_infield_location"]
    config_yaml["environment"]["project"] = "pytest"
    mock_read_yaml_file(
        {
            "config.dev.yaml": config_yaml,
        },
        monkeypatch,
    )
    monkeypatch.setenv("MY_ENVIRONMENT_VARIABLE", "my_environment_variable_value")

    build(
        typer_context,
        source_dir=str(init_project),
        build_dir=str(local_tmp_path),
        build_env="dev",
        no_clean=False,
    )
    deploy(
        typer_context,
        build_dir=str(local_tmp_path),
        build_env="dev",
        interactive=False,
        drop=True,
        dry_run=False,
        include=[],
    )

    transformation = cognite_client_approval.created_resources_of_type(Transformation)[0]
    assert transformation.source_oidc_credentials.client_id == "my_environment_variable_value"


def test_duplicated_modules(local_tmp_path: Path, typer_context: typer.Context, capture_print: PrintCapture) -> None:
    config = MagicMock(spec=BuildConfigYAML)
    config.environment = MagicMock(spec=Environment)
    config.environment.name = "dev"
    config.environment.selected_modules_and_packages = ["module1"]
    with pytest.raises(SystemExit):
        build_config(
            build_dir=local_tmp_path,
            source_dir=PROJECT_WITH_DUPLICATES,
            config=config,
            system_config=MagicMock(spec=SystemYAML),
        )
    # Check that the error message is printed
    assert "module1" in capture_print.messages[-2]
    assert "Ambiguous module selected in config.dev.yaml:" in capture_print.messages[-3]


def test_pull_transformation(
    local_tmp_path: Path,
    monkeypatch: MonkeyPatch,
    cognite_client_approval: ApprovalCogniteClient,
    cdf_tool_config: CDFToolConfig,
    typer_context: typer.Context,
    init_project: Path,
) -> None:
    # Loading a selected transformation to be pulled
    transformation_yaml = (
        init_project
        / "cognite_modules"
        / "examples"
        / "example_pump_asset_hierarchy"
        / "transformations"
        / "pump_asset_hierarchy-load-collections_pump.yaml"
    )
    loader = TransformationLoader.create_loader(cdf_tool_config)

    def load_transformation() -> TransformationWrite:
        # Injecting variables into the transformation file, so we can load it.
        original = transformation_yaml.read_text()
        content = original.replace("{{data_set}}", "ds_test")
        content = content.replace("{{cicd_clientId}}", "123")
        content = content.replace("{{cicd_clientSecret}}", "123")
        content = content.replace("{{cicd_tokenUri}}", "123")
        content = content.replace("{{cdfProjectName}}", "123")
        content = content.replace("{{cicd_scopes}}", "scope")
        content = content.replace("{{cicd_audience}}", "123")
        transformation_yaml.write_text(content)

        transformation = loader.load_resource(transformation_yaml, cdf_tool_config, skip_validation=True)
        # Write back original content
        transformation_yaml.write_text(original)
        return transformation

    loaded = load_transformation()

    # Simulate a change in the transformation in CDF.
    loaded.name = "New transformation name"
    read_transformation = Transformation.load(loaded.dump())
    cognite_client_approval.append(Transformation, read_transformation)

    pull_transformation_cmd(
        typer_context,
        source_dir=str(init_project),
        external_id=read_transformation.external_id,
        env="dev",
        dry_run=False,
    )

    after_loaded = load_transformation()

    assert after_loaded.name == "New transformation name"


def test_dump_datamodel(
    local_tmp_path: Path,
    cognite_client_approval: ApprovalCogniteClient,
    cdf_tool_config: CDFToolConfig,
    typer_context: typer.Context,
) -> None:
    # Create a datamodel and append it to the approval client
    space = dm.Space("my_space", is_global=False, last_updated_time=0, created_time=0)
    container = dm.Container(
        space="my_space",
        external_id="my_container",
        name=None,
        description=None,
        properties={"prop1": dm.ContainerProperty(type=dm.Text()), "prop2": dm.ContainerProperty(type=dm.Float64())},
        is_global=False,
        last_updated_time=0,
        created_time=0,
        used_for="node",
        constraints=None,
        indexes=None,
    )
    parent_view = dm.View(
        space="my_space",
        external_id="parent_view",
        version="1",
        properties={
            "prop2": dm.MappedProperty(
                container=container.as_id(),
                container_property_identifier="prop2",
                type=dm.Float64(),
                nullable=True,
                auto_increment=False,
            )
        },
        last_updated_time=0,
        created_time=0,
        description=None,
        name=None,
        filter=None,
        implements=None,
        writable=True,
        used_for="node",
        is_global=False,
    )

    view = dm.View(
        space="my_space",
        external_id="my_view",
        version="1",
        properties={
            "prop1": dm.MappedProperty(
                container=container.as_id(),
                container_property_identifier="prop1",
                type=dm.Text(),
                nullable=True,
                auto_increment=False,
            ),
            "prop2": dm.MappedProperty(
                container=container.as_id(),
                container_property_identifier="prop2",
                type=dm.Float64(),
                nullable=True,
                auto_increment=False,
            ),
        },
        last_updated_time=0,
        created_time=0,
        description=None,
        name=None,
        filter=None,
        implements=[parent_view.as_id()],
        writable=True,
        used_for="node",
        is_global=False,
    )
    data_model = dm.DataModel(
        space="my_space",
        external_id="my_data_model",
        version="1",
        views=[view, parent_view],
        created_time=0,
        last_updated_time=0,
        description=None,
        name=None,
        is_global=False,
    )
    cognite_client_approval.append(dm.Space, space)
    cognite_client_approval.append(dm.Container, container)
    cognite_client_approval.append(dm.View, view)
    cognite_client_approval.append(dm.DataModel, data_model)

    dump_datamodel_cmd(
        typer_context,
        space="my_space",
        external_id="my_data_model",
        version="1",
        clean=True,
        output_dir=str(local_tmp_path),
    )

    assert len(list(local_tmp_path.glob("**/*.datamodel.yaml"))) == 1
    assert len(list(local_tmp_path.glob("**/*.container.yaml"))) == 1
    assert len(list(local_tmp_path.glob("**/*.space.yaml"))) == 1
    view_files = list(local_tmp_path.glob("**/*.view.yaml"))
    assert len(view_files) == 2
    loaded_views = [dm.ViewApply.load(f.read_text()) for f in view_files]
    child_loaded = next(v for v in loaded_views if v.external_id == "my_view")
    assert child_loaded.implements[0] == parent_view.as_id()
    # The parent property should have been removed from the child view.
    assert len(child_loaded.properties) == 1


def test_build_custom_project(
    local_tmp_path: Path,
    typer_context: typer.Context,
) -> None:
    expected_resources = {"timeseries", "data_models", "data_sets"}
    build(
        typer_context,
        source_dir=str(CUSTOM_PROJECT),
        build_dir=str(local_tmp_path),
        build_env="dev",
        no_clean=False,
    )

    actual_resources = {path.name for path in local_tmp_path.iterdir() if path.is_dir()}

    missing_resources = expected_resources - actual_resources
    assert not missing_resources, f"Missing resources: {missing_resources}"

    extra_resources = actual_resources - expected_resources
    assert not extra_resources, f"Extra resources: {extra_resources}"


def test_build_project_selecting_parent_path(
    local_tmp_path,
    typer_context,
) -> None:
    expected_resources = {"auth", "data_models", "files", "transformations"}
    build(
        typer_context,
        source_dir=str(PYTEST_PROJECT),
        build_dir=str(local_tmp_path),
        build_env="dev",
        no_clean=False,
    )

    actual_resources = {path.name for path in local_tmp_path.iterdir() if path.is_dir()}

    missing_resources = expected_resources - actual_resources
    assert not missing_resources, f"Missing resources: {missing_resources}"

    extra_resources = actual_resources - expected_resources
    assert not extra_resources, f"Extra resources: {extra_resources}"
