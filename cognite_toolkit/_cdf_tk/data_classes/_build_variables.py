from __future__ import annotations

import re
from collections.abc import Collection, Iterator, Sequence
from dataclasses import dataclass
from functools import cached_property
from typing import Any, SupportsIndex, overload

from ._module_directories import ModuleLocation


@dataclass(frozen=True)
class Variable:
    """This is an internal representation of a  build variable in a config.[env].file

    Args:
        key: The name of the variable.
        value: The value of the variable.
        is_selected: Whether the variable is selected by the user through Environment.selected
        location: The location for the variable which is used to determine the module(s) it belongs to

    """

    key: str
    value: str | int | float | bool | list[str | int | float | bool] | dict[str, str | int | float | bool]
    is_selected: bool
    location: tuple[str, ...]


class BuildVariables(tuple, Sequence[Variable]):
    """This is an internal representation of the build variables in a config.[env].file

    The motivation for this class is to provide helper functions for the user to interact with the build variables.
    """

    # Subclassing tuple to make the class immutable. ModuleDirectories is expected to be initialized and
    # then used as a read-only object.
    def __new__(cls, collection: Collection[Variable]) -> BuildVariables:
        # Need to override __new__ to as we are subclassing a tuple:
        #   https://stackoverflow.com/questions/1565374/subclassing-tuple-with-multiple-init-arguments
        return super().__new__(cls, tuple(collection))

    def __init__(self, collection: Collection[Variable]) -> None: ...

    @cached_property
    def selected(self) -> BuildVariables:
        return BuildVariables([variable for variable in self if variable.is_selected])

    @classmethod
    def load(
        cls,
        raw_variable: dict[str, Any],
        available_modules: set[tuple[str, ...]],
        selected_modules: set[tuple[str, ...]],
    ) -> BuildVariables:
        """Loads the variables from the user input."""
        variables = []
        to_check: list[tuple[tuple[str, ...], dict[str, Any]]] = [(tuple(), raw_variable)]
        while to_check:
            path, subdict = to_check.pop()
            for key, value in subdict.items():
                subpath = (*path, key)
                if subpath in available_modules and isinstance(value, dict):
                    to_check.append((subpath, value))
                # elif isinstance(value, dict):
                #     # Remove this check to support variables with dictionary values.
                #     continue
                else:
                    variables.append(Variable(key, value, path in selected_modules, path))

        return cls(variables)

    def get_module_variables(self, module: ModuleLocation) -> BuildVariables:
        """Gets the variables for a specific module."""
        return BuildVariables([variable for variable in self if variable.location in module.variable_selected])

    def replace(self, content: str, file_suffix: str = ".yaml") -> str:
        for variable in self:
            replace = variable.value
            _core_patter = rf"{{{{\s*{variable.key}\s*}}}}"
            if file_suffix in {".yaml", ".yml", ".json"}:
                # Preserve data types
                if isinstance(replace, str) and (replace.isdigit() or replace.endswith(":")):
                    replace = f'"{replace}"'
                elif replace is None:
                    replace = "null"
                content = re.sub(rf"'{_core_patter}'|{_core_patter}|" + rf'"{_core_patter}"', str(replace), content)
            else:
                content = re.sub(_core_patter, str(replace), content)

        return content

    # Implemented to get correct type hints
    def __iter__(self) -> Iterator[Variable]:
        return super().__iter__()

    @overload
    def __getitem__(self, index: SupportsIndex) -> Variable: ...

    @overload
    def __getitem__(self, index: slice) -> BuildVariables: ...

    def __getitem__(self, index: SupportsIndex | slice, /) -> Variable | BuildVariables:
        if isinstance(index, slice):
            return BuildVariables(super().__getitem__(index))
        return super().__getitem__(index)
