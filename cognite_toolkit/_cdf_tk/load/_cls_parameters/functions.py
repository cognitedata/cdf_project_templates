from __future__ import annotations

import inspect

from .data_classes import ParameterSpec, ParameterSpecSet
from .get_type_hints import _TypeHints
from .type_hint import TypeHint


def read_parameter_from_init_type_hints(cls_: type) -> ParameterSpecSet:
    return _read_parameter_from_init_type_hints(cls_, tuple(), set())


def _read_parameter_from_init_type_hints(cls_: type, path: tuple[str | int, ...], seen: set[str]) -> ParameterSpecSet:
    parameter_set = ParameterSpecSet()
    if not hasattr(cls_, "__init__"):
        return parameter_set  # type: ignore[misc]

    classes = _TypeHints.get_concrete_classes(cls_)
    seen.add(cls_.__name__)
    seen.update(cls_.__name__ for cls_ in classes)
    type_hints_by_name = _TypeHints.get_type_hints_by_name(classes)
    parameters = {k: v for cls in classes for k, v in inspect.signature(cls.__init__).parameters.items()}  # type: ignore[misc]

    for name, parameter in parameters.items():
        if name == "self" or parameter.kind in [parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD]:
            continue
        try:
            hint = TypeHint(type_hints_by_name[name])
        except KeyError:
            # Missing type hint
            parameter_set.is_complete = False
            continue
        is_required = parameter.default is inspect.Parameter.empty
        is_nullable = hint.is_nullable
        parameter_set.add(ParameterSpec((*path, name), hint.frozen_types, is_required, is_nullable))
        if hint.is_base_type:
            continue
        # We iterate as we might have union types
        for sub_hint in hint.sub_hints:
            if sub_hint.is_dict_type:
                key, value = sub_hint.container_args
                dict_set = _read_parameter_from_init_type_hints(value, (*path, name), seen.copy())
                parameter_set.update(dict_set)
            if sub_hint.is_list_type:
                item = sub_hint.container_args[0]
                item_hint = TypeHint(item)
                if item_hint.is_base_type:
                    parameter_set.add(ParameterSpec((*path, name, 0), item_hint.frozen_types, is_required, is_nullable))
                elif item.__name__ in seen:
                    parameter_set.add(ParameterSpec((*path, name, 0), frozenset({"dict"}), is_required, is_nullable))
                else:
                    list_set = _read_parameter_from_init_type_hints(sub_hint.args[0], (*path, name, 0), seen.copy())
                    parameter_set.update(list_set)
            elif sub_hint.is_class:
                arg = sub_hint.args[0]
                if arg.__name__ in seen:
                    parameter_set.add(ParameterSpec((*path, name), frozenset({"dict"}), is_required, is_nullable))
                else:
                    cls_set = _read_parameter_from_init_type_hints(arg, (*path, name), seen.copy())
                    parameter_set.update(cls_set)

    return parameter_set
