from __future__ import annotations

import abc
import collections
import inspect
import re
import sys
import types
import typing
from collections.abc import Hashable, Iterable, MutableSet
from dataclasses import dataclass
from functools import total_ordering
from pathlib import Path
from typing import Any, ClassVar, Generic, TypeVar, get_origin

from cognite.client.data_classes._base import CogniteObject
from cognite.client.utils._text import to_camel_case, to_snake_case

from ._get_type_hints import _TypeHints
from .warning import (
    DataSetMissingWarning,
    SnakeCaseWarning,
    TemplateVariableWarning,
    WarningList,
)


def validate_case_raw(
    raw: dict[str, Any] | list[dict[str, Any]],
    resource_cls: type[CogniteObject],
    filepath: Path,
    identifier_key: str = "externalId",
) -> WarningList:
    """Checks whether camel casing the raw data would match a parameter in the resource class.

    Args:
        raw: The raw data to check.
        resource_cls: The resource class to check against init method
        filepath: The filepath of the raw data. This is used to pass to the warnings for easy
            grouping of warnings.
        identifier_key: The key to use as identifier. Defaults to "externalId". This is used to pass to the warnings
            for easy grouping of warnings.

    Returns:
        A list of CaseWarning objects.

    """
    return _validate_case_raw(raw, resource_cls, filepath, identifier_key)


def _validate_case_raw(
    raw: dict[str, Any] | list[dict[str, Any]],
    resource_cls: type[CogniteObject],
    filepath: Path,
    identifier_key: str = "externalId",
    identifier_value: str = "",
) -> WarningList:
    warning_list: WarningList = WarningList()
    if isinstance(raw, list):
        for item in raw:
            warning_list.extend(_validate_case_raw(item, resource_cls, filepath, identifier_key))
        return warning_list
    elif not isinstance(raw, dict):
        return warning_list

    signature = inspect.signature(resource_cls.__init__)

    is_base_class = inspect.isclass(resource_cls) and any(base is abc.ABC for base in resource_cls.__bases__)
    if is_base_class:
        # If it is a base class, it cannot be instantiated, so it can be any of the
        # subclasses' parameters.
        expected = {
            to_camel_case(parameter)
            for sub in resource_cls.__subclasses__()
            for parameter in inspect.signature(sub.__init__).parameters.keys()
        } - {"self"}
    else:
        expected = set(map(to_camel_case, signature.parameters.keys())) - {"self"}

    actual = set(raw.keys())
    actual_camel_case = set(map(to_camel_case, actual))
    snake_cased = actual - actual_camel_case

    if not identifier_value:
        identifier_value = raw.get(
            identifier_key, raw.get(to_snake_case(identifier_key), f"No identifier {identifier_key}")
        )

    for key in snake_cased:
        if (camel_key := to_camel_case(key)) in expected:
            warning_list.append(SnakeCaseWarning(filepath, identifier_value, identifier_key, str(key), str(camel_key)))

    try:
        type_hints_by_name = _TypeHints.get_type_hints_by_name(resource_cls)
    except Exception:
        # If we cannot get type hints, we cannot check if the type is correct.
        return warning_list

    for key, value in raw.items():
        if not isinstance(value, dict):
            continue
        if (parameter := signature.parameters.get(to_snake_case(key))) and (
            type_hint := type_hints_by_name.get(parameter.name)
        ):
            if inspect.isclass(type_hint) and issubclass(type_hint, CogniteObject):
                warning_list.extend(_validate_case_raw(value, type_hint, filepath, identifier_key, identifier_value))
                continue

            container_type = get_origin(type_hint)
            if sys.version_info >= (3, 10):
                # UnionType was introduced in Python 3.10
                if container_type is types.UnionType:
                    args = typing.get_args(type_hint)
                    type_hint = next((arg for arg in args if arg is not type(None)), None)

            mappings = [dict, collections.abc.MutableMapping, collections.abc.Mapping]
            is_mapping = container_type in mappings or (
                isinstance(type_hint, types.GenericAlias) and len(typing.get_args(type_hint)) == 2
            )
            if not is_mapping:
                continue
            args = typing.get_args(type_hint)
            if not args:
                continue
            container_key, container_value = args
            if inspect.isclass(container_value) and issubclass(container_value, CogniteObject):
                for sub_key, sub_value in value.items():
                    warning_list.extend(
                        _validate_case_raw(sub_value, container_value, filepath, identifier_key, identifier_value)
                    )

    return warning_list


def validate_modules_variables(config: dict[str, Any], filepath: Path, path: str = "") -> WarningList:
    """Checks whether the config file has any issues.

    Currently, this checks for:
        * Non-replaced template variables, such as <change_me>.

    Args:
        config: The config to check.
        filepath: The filepath of the config.yaml.
        path: The path in the config.yaml. This is used recursively by this function.
    """
    warning_list: WarningList = WarningList()
    pattern = re.compile(r"<.*?>")
    for key, value in config.items():
        if isinstance(value, str) and pattern.match(value):
            warning_list.append(TemplateVariableWarning(filepath, value, key, path))
        elif isinstance(value, dict):
            if path:
                path += "."
            warning_list.extend(validate_modules_variables(value, filepath, f"{path}{key}"))
    return warning_list


def validate_data_set_is_set(
    raw: dict[str, Any] | list[dict[str, Any]],
    resource_cls: type[CogniteObject],
    filepath: Path,
    identifier_key: str = "externalId",
) -> WarningList:
    warning_list: WarningList = WarningList()
    signature = inspect.signature(resource_cls.__init__)
    if "data_set_id" not in set(signature.parameters.keys()):
        return warning_list

    if isinstance(raw, list):
        for item in raw:
            warning_list.extend(validate_data_set_is_set(item, resource_cls, filepath, identifier_key))
        return warning_list

    if "dataSetExternalId" in raw or "dataSetId" in raw:
        return warning_list

    value = raw.get(identifier_key, raw.get(to_snake_case(identifier_key), f"No identifier {identifier_key}"))
    warning_list.append(DataSetMissingWarning(filepath, value, identifier_key, resource_cls.__name__))
    return warning_list


# These are internal classes that are used by the validate parameter functions.
@total_ordering
@dataclass(frozen=True)
class Parameter:
    path: tuple[str | int, ...]
    type: str

    def __lt__(self, other: Parameter) -> bool:
        if not isinstance(other, Parameter):
            return NotImplemented
        return self.path < other.path

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Parameter):
            return NotImplemented
        return self.path == other.path and self.type == other.type


@dataclass(frozen=True)
class ParameterSpec(Parameter):
    is_required: bool
    _is_nullable: bool | None = None

    @property
    def is_nullable(self) -> bool:
        return self._is_nullable or not self.is_required


@dataclass(frozen=True)
class ParameterValue(Parameter):
    value: str | int | float | bool | list | dict


T_Parameter = TypeVar("T_Parameter", bound=Parameter)


class ParameterSet(Hashable, MutableSet, Generic[T_Parameter]):
    def __init__(self, iterable: Iterable[T_Parameter] = ()) -> None:
        self.data: set[T_Parameter] = set(iterable)

    def __hash__(self) -> int:
        return hash(self.data)

    def __contains__(self, value: object) -> bool:
        return value in self.data

    def __iter__(self) -> typing.Iterator[T_Parameter]:
        return iter(self.data)

    def __len__(self) -> int:
        return len(self.data)

    def __repr__(self) -> str:
        return repr(self.data)

    def add(self, item: T_Parameter) -> None:
        self.data.add(item)

    def discard(self, item: T_Parameter) -> None:
        self.data.discard(item)

    def update(self, other: ParameterSet[T_Parameter]) -> None:
        self.data.update(other.data)


class ParameterSpecSet(ParameterSet[ParameterSpec]):
    def __init__(self, iterable: Iterable[ParameterSpec] = ()) -> None:
        super().__init__(iterable)
        self.is_complete = True

    @property
    def required(self) -> ParameterSet[ParameterSpec]:
        return ParameterSet[ParameterSpec](parameter for parameter in self if parameter.is_required)

    def update(self, other: ParameterSet[ParameterSpec]) -> None:
        if isinstance(other, ParameterSpecSet):
            self.is_complete &= other.is_complete
        super().update(other)


class _TypeHint:
    _BASE_TYPES: ClassVar[set[str]] = {t.__name__ for t in (str, int, float, bool)}
    _CONTAINER_TYPES: ClassVar[set[str]] = {t.__name__ for t in (list, dict)}

    def __init__(self, raw: Any) -> None:
        self.hint = raw
        self._container_type = get_origin(raw)
        self.args = typing.get_args(raw)
        self._inner_container = None
        if self._container_type:
            self._inner_container = typing.get_origin(self._container_type)
            self._inner_args = typing.get_args(self._inner_container)

    def __str__(self) -> str:
        if self._container_type and self._container_type not in [types.UnionType, typing.Union]:
            value = self._container_type.__name__
        else:
            value = self.arg.__name__
        if value in self._CONTAINER_TYPES or value in self._BASE_TYPES:
            return value
        elif value == "Literal":
            return "str"
        return "dict"

    @property
    def arg(self) -> Any:
        if (self._container_type in [typing.Union, types.UnionType]) and self.args:
            if (self._inner_container in [typing.Union, types.UnionType]) and self._inner_args:
                return self._inner_args[0]
            else:
                return self.args[0]
        return self.hint

    @property
    def is_base_type(self) -> bool:
        if self._container_type:
            if self._container_type is types.UnionType and self.args:
                return self.args[0].__name__ in self._BASE_TYPES
            return False
        return self.hint.__name__ in self._BASE_TYPES

    @property
    def is_nullable(self) -> bool:
        return any(arg is None or arg is types.NoneType for arg in self.args)

    @property
    def is_class(self) -> bool:
        return inspect.isclass(self.arg)

    @property
    def is_dict_type(self) -> bool:
        return self._container_type is dict

    @property
    def is_list_type(self) -> bool:
        return self._container_type is list

    def __repr__(self) -> str:
        return repr(self.arg)


def read_parameter_from_init_type_hints(cls_: type, path: tuple[str, ...] | None = None) -> ParameterSpecSet:
    path = tuple() if path is None else path
    parameter_set = ParameterSpecSet()
    if not hasattr(cls_, "__init__"):
        return parameter_set  # type: ignore[misc]

    classes = _TypeHints.get_concrete_classes(cls_)
    type_hints_by_name = _TypeHints.get_type_hints_by_name(classes)
    parameters = {k: v for cls in classes for k, v in inspect.signature(cls.__init__).parameters.items()}  # type: ignore[misc]
    for name, parameter in parameters.items():
        if name == "self":
            continue
        if name not in type_hints_by_name:
            # This is a parameter that is not in the type hints.
            parameter_set.is_complete = False
            continue
        hint = _TypeHint(type_hints_by_name[name])
        is_required = parameter.default is inspect.Parameter.empty
        is_nullable = hint.is_nullable
        parameter_set.add(ParameterSpec((*path, name), str(hint), is_required, is_nullable))
        if hint.is_base_type:
            continue
        elif hint.is_dict_type:
            key, value = hint.args
            dict_set = read_parameter_from_init_type_hints(value, (*path, name))
            parameter_set.update(dict_set)
        if hint.is_list_type:
            raise NotImplementedError()
        elif hint.is_class:
            cls_set = read_parameter_from_init_type_hints(hint.arg, (*path, name))
            parameter_set.update(cls_set)

    return parameter_set
