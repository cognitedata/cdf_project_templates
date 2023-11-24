from pathlib import Path
from typing import Callable
from unittest.mock import MagicMock

import pytest
from cognite.client import CogniteClient

from cognite_toolkit.cdf_tk.load import (
    DatapointsLoader,
    FileLoader,
    Loader,
    drop_load_resources,
    load_datamodel_graphql,
)
from cognite_toolkit.cdf_tk.utils import CDFToolConfig

THIS_FOLDER = Path(__file__).resolve().parent

DATA_FOLDER = THIS_FOLDER / "load_data"
SNAPSHOTS_DIR = THIS_FOLDER / "load_data_snapshots"


@pytest.mark.parametrize(
    "load_function, directory, extra_args",
    [
        (
            load_datamodel_graphql,
            DATA_FOLDER / "datamodel_graphql",
            dict(space_name="test_space", model_name="test_model"),
        ),
    ],
)
def test_loader_function(
    load_function: Callable, directory: Path, extra_args: dict, cognite_client_approval: CogniteClient, data_regression
):
    cdf_tool = MagicMock(spec=CDFToolConfig)
    cdf_tool.verify_client.return_value = cognite_client_approval
    cdf_tool.data_set_id = 999

    load_function(ToolGlobals=cdf_tool, directory=directory, **extra_args)

    dump = cognite_client_approval.dump()
    data_regression.check(dump, fullpath=SNAPSHOTS_DIR / f"{directory.name}.yaml")


@pytest.mark.parametrize(
    "loader_cls, directory",
    [
        (FileLoader, DATA_FOLDER / "files"),
        (DatapointsLoader, DATA_FOLDER / "timeseries_datapoints"),
    ],
)
def test_loader_class(
    loader_cls: type[Loader], directory: Path, cognite_client_approval: CogniteClient, data_regression
):
    cdf_tool = MagicMock(spec=CDFToolConfig)
    cdf_tool.verify_client.return_value = cognite_client_approval
    cdf_tool.verify_capabilities.return_value = cognite_client_approval
    cdf_tool.data_set_id = 999

    drop_load_resources(loader_cls.create_loader(cdf_tool), directory, cdf_tool, drop=False, load=True, dry_run=False)

    dump = cognite_client_approval.dump()
    data_regression.check(dump, fullpath=SNAPSHOTS_DIR / f"{directory.name}.yaml")
