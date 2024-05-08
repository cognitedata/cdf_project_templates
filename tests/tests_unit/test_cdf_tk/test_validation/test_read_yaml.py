from pathlib import Path

import pytest
import yaml
from cognite.client.data_classes import TimeSeries
from cognite.client.data_classes.data_modeling import SpaceApply, ViewApply

from cognite_toolkit._cdf_tk.validation import validate_case_raw, validate_data_set_is_set
from cognite_toolkit._cdf_tk.validation.read_yaml import ParameterSet, ParameterSpec, read_parameter_from_type_hints
from cognite_toolkit._cdf_tk.validation.warning import DataSetMissingWarning, SnakeCaseWarning
from tests.tests_unit.data import LOAD_DATA


def test_validate_raw() -> None:
    raw_file = LOAD_DATA / "timeseries" / "wrong_case.yaml"

    warnings = validate_case_raw(yaml.safe_load(raw_file.read_text()), TimeSeries, raw_file)

    assert len(warnings) == 2
    assert sorted(warnings) == sorted(
        [
            SnakeCaseWarning(raw_file, "wrong_case", "externalId", "is_string", "isString"),
            SnakeCaseWarning(raw_file, "wrong_case", "externalId", "is_step", "isStep"),
        ]
    )


def test_validate_raw_nested() -> None:
    raw_file = LOAD_DATA / "datamodels" / "snake_cased_view_property.yaml"
    warnings = validate_case_raw(yaml.safe_load(raw_file.read_text()), ViewApply, raw_file)

    assert len(warnings) == 1
    assert warnings == [
        SnakeCaseWarning(
            raw_file, "WorkItem", "externalId", "container_property_identifier", "containerPropertyIdentifier"
        )
    ]


def test_validate_data_set_is_set():
    warnings = validate_data_set_is_set(
        {"externalId": "myTimeSeries", "name": "My Time Series"}, TimeSeries, Path("timeseries.yaml")
    )

    assert sorted(warnings) == sorted(
        [DataSetMissingWarning(Path("timeseries.yaml"), "myTimeSeries", "externalId", "TimeSeries")]
    )


class TestParameterSet:
    @pytest.mark.parametrize(
        "cls_, expected_parameters",
        [
            (
                SpaceApply,
                ParameterSet[ParameterSpec](
                    {
                        ParameterSpec(("space",), str, True),
                        ParameterSpec(("description",), str, False),
                        ParameterSpec(("name",), str, False),
                    }
                ),
            ),
        ],
    )
    def test_read_parameter_from_type_hints(self, cls_: type, expected_parameters: ParameterSet[ParameterSpec]) -> None:
        actual_parameters = read_parameter_from_type_hints(cls_)

        assert actual_parameters == expected_parameters
