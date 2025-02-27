import shutil
import tempfile
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock

import pytest
import requests
import yaml
from cognite.client.data_classes import (
    FileMetadata,
    Transformation,
    TransformationSchedule,
)
from cognite.client.data_classes.data_modeling import Edge, Node
from cognite.client.data_classes.hosted_extractors import Destination
from pytest import MonkeyPatch
from pytest_regressions.data_regression import DataRegressionFixture

from cognite_toolkit._cdf_tk._parameters import ParameterSet, read_parameters_from_dict
from cognite_toolkit._cdf_tk.cdf_toml import CDFToml
from cognite_toolkit._cdf_tk.client.data_classes.graphql_data_models import GraphQLDataModel
from cognite_toolkit._cdf_tk.client.data_classes.streamlit_ import Streamlit
from cognite_toolkit._cdf_tk.commands import BuildCommand, DeployCommand, ModulesCommand
from cognite_toolkit._cdf_tk.data_classes import (
    BuildConfigYAML,
    BuildEnvironment,
)
from cognite_toolkit._cdf_tk.loaders import (
    LOADER_BY_FOLDER_NAME,
    LOADER_LIST,
    RESOURCE_LOADER_LIST,
    DatapointsLoader,
    FileMetadataLoader,
    GroupResourceScopedLoader,
    HostedExtractorSourceLoader,
    Loader,
    LocationFilterLoader,
    ResourceLoader,
    ResourceTypes,
    ViewLoader,
    get_loader,
)
from cognite_toolkit._cdf_tk.utils import tmp_build_directory
from cognite_toolkit._cdf_tk.utils.auth import EnvironmentVariables
from cognite_toolkit._cdf_tk.validation import validate_resource_yaml
from tests.constants import REPO_ROOT
from tests.data import LOAD_DATA, PROJECT_FOR_TEST
from tests.test_unit.approval_client import ApprovalToolkitClient
from tests.test_unit.test_cdf_tk.constants import BUILD_DIR, SNAPSHOTS_DIR_ALL
from tests.test_unit.utils import FakeCogniteResourceGenerator

SNAPSHOTS_DIR = SNAPSHOTS_DIR_ALL / "load_data_snapshots"


@pytest.mark.parametrize(
    "loader_cls",
    [
        FileMetadataLoader,
        DatapointsLoader,
    ],
)
def test_loader_class(
    loader_cls: type[ResourceLoader],
    toolkit_client_approval: ApprovalToolkitClient,
    env_vars_with_client: EnvironmentVariables,
    data_regression: DataRegressionFixture,
):
    cmd = DeployCommand(print_warning=False)
    loader = loader_cls.create_loader(env_vars_with_client.get_client(), LOAD_DATA)
    cmd.deploy_resources(loader, env_vars_with_client, BuildEnvironment(), dry_run=False)

    dump = toolkit_client_approval.dump()
    data_regression.check(dump, fullpath=SNAPSHOTS_DIR / f"{loader.folder_name}.yaml")


class TestDeployResources:
    def test_deploy_resource_order(
        self, toolkit_client_approval: ApprovalToolkitClient, env_vars_with_client: EnvironmentVariables
    ):
        build_env_name = "dev"
        cdf_toml = CDFToml.load(PROJECT_FOR_TEST)
        config = BuildConfigYAML.load_from_directory(PROJECT_FOR_TEST, build_env_name)
        config.environment.selected = ["another_module"]
        build_cmd = BuildCommand()
        build_cmd.build_config(
            BUILD_DIR, PROJECT_FOR_TEST, config=config, packages=cdf_toml.modules.packages, clean=True, verbose=False
        )
        expected_order = ["MyView", "MyOtherView"]

        cmd = DeployCommand(print_warning=False)
        cmd.deploy_resources(
            ViewLoader.create_loader(env_vars_with_client.get_client(), BUILD_DIR),
            env_vars_with_client,
            BuildEnvironment(),
            dry_run=False,
        )

        views = toolkit_client_approval.dump(sort=False)["View"]

        actual_order = [view["externalId"] for view in views]

        assert actual_order == expected_order


class TestFormatConsistency:
    @pytest.mark.parametrize("Loader", RESOURCE_LOADER_LIST)
    def test_fake_resource_generator(
        self, Loader: type[ResourceLoader], env_vars_with_client: EnvironmentVariables, monkeypatch: MonkeyPatch
    ):
        fakegenerator = FakeCogniteResourceGenerator(seed=1337)

        loader = Loader.create_loader(env_vars_with_client.get_client())
        instance = fakegenerator.create_instance(loader.resource_write_cls)

        assert isinstance(instance, loader.resource_write_cls)

    @pytest.mark.parametrize("Loader", RESOURCE_LOADER_LIST)
    def test_loader_takes_dict(
        self,
        Loader: type[ResourceLoader],
        env_vars_with_client: EnvironmentVariables,
        monkeypatch: MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        loader = Loader.create_loader(env_vars_with_client.get_client(), tmp_path)

        if loader.resource_cls in [Transformation, FileMetadata, GraphQLDataModel, Streamlit]:
            pytest.skip("Skipped loaders that require secondary files")
        elif loader.resource_cls in [Edge, Node, Destination]:
            pytest.skip(f"Skipping {loader.resource_cls} because it has special properties")
        elif Loader in [GroupResourceScopedLoader]:
            pytest.skip(f"Skipping {loader.resource_cls} because it requires scoped capabilities")
        elif Loader in [LocationFilterLoader]:
            pytest.skip(f"Skipping {loader.resource_cls} because it requires special handling")

        instance = FakeCogniteResourceGenerator(seed=1337).create_instance(loader.resource_write_cls)

        # special case
        if isinstance(instance, TransformationSchedule):
            del instance.id  # Client validation does not allow id and externalid to be set simultaneously

        file = MagicMock(spec=Path)
        file.read_text.return_value = yaml.dump(instance.dump())
        file.suffix = ".yaml"
        file.name = "dict.yaml"
        file.parent.name = loader.folder_name

        loaded = loader.load_resource_file(filepath=file, environment_variables=env_vars_with_client.dump())
        assert isinstance(loaded, list)
        assert len(loaded) == 1

    @pytest.mark.parametrize("Loader", RESOURCE_LOADER_LIST)
    def test_loader_takes_list(
        self,
        Loader: type[ResourceLoader],
        env_vars_with_client: EnvironmentVariables,
        monkeypatch: MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        loader = Loader.create_loader(env_vars_with_client.get_client(), tmp_path)

        if loader.resource_cls in [Transformation, FileMetadata, GraphQLDataModel, Streamlit]:
            pytest.skip("Skipped loaders that require secondary files")
        elif loader.resource_cls in [Edge, Node, Destination]:
            pytest.skip(f"Skipping {loader.resource_cls} because it has special properties")
        elif Loader in [GroupResourceScopedLoader]:
            pytest.skip(f"Skipping {loader.resource_cls} because it requires scoped capabilities")
        elif Loader in [LocationFilterLoader]:
            # TODO: https://cognitedata.atlassian.net/browse/CDF-22363
            pytest.skip(
                f"Skipping {loader.resource_cls} because FakeCogniteResourceGenerator doesn't generate cls properties correctly"
            )

        instances = FakeCogniteResourceGenerator(seed=1337).create_instances(loader.list_write_cls)

        # special case
        if isinstance(loader.resource_cls, TransformationSchedule):
            for instance in instances:
                del instance.id  # Client validation does not allow id and externalid to be set simultaneously

        file = MagicMock(spec=Path)
        file.read_text.return_value = yaml.dump(instances.dump())
        file.suffix = ".yaml"
        file.name = "dict.yaml"
        file.parent.name = loader.folder_name

        loaded = loader.load_resource_file(filepath=file, environment_variables=env_vars_with_client.dump())
        assert isinstance(loaded, list)

    @staticmethod
    def check_url(url) -> bool:
        try:
            response = requests.get(url, allow_redirects=True)
            return response.status_code >= 200 and response.status_code <= 300
        except requests.exceptions.RequestException:
            return False

    @pytest.mark.parametrize(
        "Loader", [loader for loader in LOADER_LIST if loader.folder_name != "robotics"]
    )  # Robotics does not have a public doc_url
    def test_loader_has_doc_url(
        self, Loader: type[Loader], env_vars_with_client: EnvironmentVariables, monkeypatch: MonkeyPatch
    ):
        loader = Loader.create_loader(env_vars_with_client.get_client())
        assert loader.doc_url() != loader._doc_base_url, f"{Loader.folder_name} is missing doc_url deep link"
        assert self.check_url(loader.doc_url()), f"{Loader.folder_name} doc_url is not accessible"


def test_resource_types_is_up_to_date() -> None:
    expected = set(LOADER_BY_FOLDER_NAME.keys())
    actual = set(ResourceTypes.__args__)

    missing = expected - actual
    extra = actual - expected
    assert not missing, f"Missing {missing=}"
    assert not extra, f"Extra {extra=}"


@contextmanager
def tmp_org_directory() -> Iterator[Path]:
    org_dir = Path(tempfile.mkdtemp(prefix="orgdir.", suffix=".tmp", dir=Path.cwd()))
    try:
        yield org_dir
    finally:
        shutil.rmtree(org_dir)


def cognite_module_files_with_loader() -> Iterable[ParameterSet]:
    with tmp_org_directory() as organization_dir, tmp_build_directory() as build_dir:
        ModulesCommand().init(organization_dir, select_all=True, clean=True)
        cdf_toml = CDFToml.load(REPO_ROOT)
        config = BuildConfigYAML.load_from_directory(organization_dir, "dev")
        config.set_environment_variables()
        # Use path syntax to select all modules in the source directory
        config.environment.selected = [Path()]

        built_modules = BuildCommand().build_config(
            build_dir=build_dir,
            organization_dir=organization_dir,
            config=config,
            packages=cdf_toml.modules.packages,
            clean=True,
            verbose=False,
        )
        for module in built_modules:
            for resource_folder, resources in module.resources.items():
                for resource in resources:
                    try:
                        loader = get_loader(resource_folder, resource.kind)
                    except ValueError:
                        # Cannot find loader for resource kind
                        continue
                    filepath = cast(Path, resource.destination)
                    if issubclass(loader, ResourceLoader):
                        raw = yaml.CSafeLoader(filepath.read_text()).get_data()

                        if isinstance(raw, dict):
                            yield pytest.param(loader, raw, id=f"{module.name} - {filepath.stem} - dict")
                        elif isinstance(raw, list):
                            for no, item in enumerate(raw):
                                yield pytest.param(loader, item, id=f"{module.name} - {filepath.stem} - list {no}")


class TestResourceLoaders:
    # The HostedExtractorSourceLoader does not support parameter spec.
    @pytest.mark.parametrize(
        "loader_cls",
        [loader_cls for loader_cls in RESOURCE_LOADER_LIST if loader_cls is not HostedExtractorSourceLoader],
    )
    def test_get_write_cls_spec(self, loader_cls: type[ResourceLoader]) -> None:
        resource = FakeCogniteResourceGenerator(seed=1337, max_list_dict_items=1).create_instance(
            loader_cls.resource_write_cls
        )
        resource_dump = resource.dump(camel_case=True)
        # These are handled by the toolkit
        resource_dump.pop("dataSetId", None)
        resource_dump.pop("targetDataSetId", None)
        resource_dump.pop("fileId", None)
        resource_dump.pop("assetIds", None)
        resource_dump.pop("assetId", None)
        resource_dump.pop("parentId", None)
        dumped = read_parameters_from_dict(resource_dump)
        spec = loader_cls.get_write_cls_parameter_spec()

        for param in list(dumped):
            # Required for Location Filter
            if "dataSetIds" in param.path:
                dumped.discard(param)

        extra = dumped - spec

        # The spec is calculated based on the resource class __init__ method.
        # There can be deviations in the output from the dump. If that is the case,
        # the 'get_write_cls_parameter_spec' must be updated in the loader. See, for example, the DataModelLoader.
        assert sorted(extra) == []

    @pytest.mark.parametrize("loader_cls, content", list(cognite_module_files_with_loader()))
    def test_write_cls_spec_against_cognite_modules(self, loader_cls: type[ResourceLoader], content: dict) -> None:
        spec = loader_cls.get_write_cls_parameter_spec()

        warnings = validate_resource_yaml(content, spec, Path("test.yaml"))

        assert sorted(warnings) == []

    @pytest.mark.parametrize("loader_cls", RESOURCE_LOADER_LIST)
    def test_empty_required_capabilities_when_no_items(
        self, loader_cls: type[ResourceLoader], env_vars_with_client: EnvironmentVariables
    ):
        actual = loader_cls.get_required_capability(loader_cls.list_write_cls([]), read_only=False)

        assert actual == []

    def test_unique_kind_by_folder(self):
        kind = defaultdict(list)
        for loader_cls in RESOURCE_LOADER_LIST:
            kind[loader_cls.folder_name].append(loader_cls.kind)

        duplicated = {folder: Counter(kinds) for folder, kinds in kind.items() if len(set(kinds)) != len(kinds)}
        # we have two types Group loaders, one for scoped and one for all
        # this is intended and thus not an issue.
        duplicated.pop("auth")

        assert not duplicated, f"Duplicated kind by folder: {duplicated!s}"
