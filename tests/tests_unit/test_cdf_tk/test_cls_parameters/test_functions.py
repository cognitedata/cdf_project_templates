import pytest
from cognite.client.data_classes.data_modeling import ContainerApply, SpaceApply

from cognite_toolkit._cdf_tk.load import RESOURCE_LOADER_LIST, ResourceLoader
from cognite_toolkit._cdf_tk.load._cls_parameters import (
    ParameterSpec,
    ParameterSpecSet,
    read_parameter_from_init_type_hints,
)


class TestReadParameterFromTypeHints:
    @pytest.mark.parametrize(
        "cls_, expected_parameters",
        [
            (
                SpaceApply,
                ParameterSpecSet(
                    {
                        ParameterSpec(("space",), "str", True, False),
                        ParameterSpec(("description",), "str", False, True),
                        ParameterSpec(("name",), "str", False, True),
                    }
                ),
            ),
            (
                ContainerApply,
                ParameterSpecSet(
                    {
                        ParameterSpec(("space",), "str", True, False),
                        ParameterSpec(("external_id",), "str", True, False),
                        ParameterSpec(("properties",), "dict", True, False),
                        ParameterSpec(("properties", "type"), "dict", True, False),
                        ParameterSpec(("properties", "nullable"), "bool", False, False),
                        ParameterSpec(("properties", "auto_increment"), "bool", False, False),
                        ParameterSpec(("properties", "name"), "str", False, True),
                        ParameterSpec(("properties", "default_value"), "str", False, True),
                        ParameterSpec(("properties", "description"), "str", False, True),
                        ParameterSpec(("properties", "type", "collation"), "str", False, False),
                        ParameterSpec(("properties", "type", "container"), "dict", False, True),
                        ParameterSpec(("properties", "type", "container", "space"), "str", True, False),
                        ParameterSpec(("properties", "type", "container", "external_id"), "str", True, False),
                        ParameterSpec(("properties", "type", "is_list"), "bool", False, False),
                        ParameterSpec(("properties", "type", "unit"), "dict", False, True),
                        ParameterSpec(("properties", "type", "unit", "external_id"), "str", True, False),
                        ParameterSpec(("properties", "type", "unit", "source_unit"), "str", False, True),
                        ParameterSpec(("description",), "str", False, True),
                        ParameterSpec(("name",), "str", False, True),
                        ParameterSpec(("used_for",), "str", False, True),
                        ParameterSpec(("constraints",), "dict", False, True),
                        ParameterSpec(
                            (
                                "constraints",
                                "require",
                            ),
                            "dict",
                            True,
                            False,
                        ),
                        ParameterSpec(("constraints", "require", "space"), "str", True, False),
                        ParameterSpec(("constraints", "require", "external_id"), "str", True, False),
                        ParameterSpec(("constraints", "properties"), "list", True, False),
                        ParameterSpec(("constraints", "properties", 0), "str", True, False),
                        ParameterSpec(("indexes",), "dict", False, True),
                        ParameterSpec(("indexes", "properties"), "list", True, False),
                        ParameterSpec(("indexes", "properties", 0), "str", True, False),
                        ParameterSpec(("indexes", "cursorable"), "bool", False, False),
                    }
                ),
            ),
        ],
    )
    def test_read_as_expected(self, cls_: type, expected_parameters: ParameterSpecSet) -> None:
        actual_parameters = read_parameter_from_init_type_hints(cls_)

        assert sorted(actual_parameters) == sorted(expected_parameters)

    @pytest.mark.parametrize("loader_cls", RESOURCE_LOADER_LIST)
    def test_compatible_with_loaders(self, loader_cls: type[ResourceLoader]) -> None:
        parameter_set = read_parameter_from_init_type_hints(loader_cls.resource_write_cls)

        assert isinstance(parameter_set, ParameterSpecSet)
        assert len(parameter_set) > 0
