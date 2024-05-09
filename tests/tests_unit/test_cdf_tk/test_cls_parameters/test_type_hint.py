from __future__ import annotations

import sys
from collections.abc import Iterable
from typing import Any, Literal, Union

import pytest
from _pytest.mark import ParameterSet

from cognite_toolkit._cdf_tk._cls_parameters import TypeHint


def type_hint_test_cases() -> Iterable[ParameterSet]:
    yield pytest.param(str, ["str"], True, False, True, False, False, id="str")
    yield pytest.param(Literal["a", "b"], ["str"], True, False, False, False, False, id="Literal")
    yield pytest.param(dict[str, int], ["dict"], False, False, False, True, False, id="dict")
    yield pytest.param(Union[str, int], ["str", "int"], True, False, False, False, False, id="Union")
    if sys.version_info >= (3, 10):
        yield pytest.param(str | None, ["str"], True, True, False, False, False, id="str | None")
        yield pytest.param(
            str | int | bool, ["str", "int", "bool"], True, False, False, False, False, id="str | int | bool"
        )
        yield pytest.param(list[str] | None, ["list"], False, True, False, False, True, id="list | None")
        yield pytest.param(
            list[str] | dict[str, int] | None, ["list", "dict"], False, True, False, True, True, id="list | dict | None"
        )


class TestTypeHint:
    @pytest.mark.parametrize(
        "raw, types, is_base_type, is_nullable, is_class, is_dict_type, is_list_type",
        list(type_hint_test_cases()),
    )
    def test_type_hint(
        self,
        raw: Any,
        types: list[str],
        is_base_type: bool,
        is_nullable: bool,
        is_class: bool,
        is_dict_type: bool,
        is_list_type: bool,
    ):
        hint = TypeHint(raw)
        assert hint.types == types
        assert hint.is_base_type == is_base_type
        assert hint.is_nullable == is_nullable
        assert hint.is_class == is_class
        assert hint.is_dict_type == is_dict_type
        assert hint.is_list_type == is_list_type
