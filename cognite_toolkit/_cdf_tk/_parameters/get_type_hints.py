from __future__ import annotations

import abc
import importlib
import inspect
import re
import typing
from collections import Counter
from typing import Any, get_type_hints

from cognite.client.data_classes import TransformationScheduleWrite
from cognite.client.data_classes.capabilities import UnknownAcl


class _TypeHints:
    """
    This class is used to get type hints from the init function of a CogniteObject.

    After Python 3.10, type hints are treated as strings, so we need to evaluate them to get the actual type.
    """

    _error_msg: typing.ClassVar[str] = "Please extend this function to support generating fake data for this type"

    @classmethod
    def get_concrete_classes(cls, resource_cls: type) -> list[type]:
        """Returns all the concrete classes that are subclasses of the given class.
        (including the class itself if it is concrete)"""
        concrete_classes = []
        to_check = [resource_cls]
        while to_check:
            cls_ = to_check.pop()
            to_check.extend(cls_.__subclasses__())
            is_base_class = inspect.isclass(cls_) and any(base is abc.ABC for base in cls_.__bases__)
            # UnknownAcl is a special case, it is concrete class, but cannot be instantiated easily
            if not is_base_class and cls_ is not UnknownAcl:
                concrete_classes.append(cls_)
            if cls_ is TransformationScheduleWrite:
                # TransformationScheduleWrite is wrongly marked as ABC, but it is a concrete class
                # Fixed after 7.43.1
                concrete_classes.append(cls_)
        return concrete_classes

    @classmethod
    def get_type_hints_by_name(cls, resource_cls: type | list[type]) -> dict[str, Any]:
        """
        Get type hints from the init function of a CogniteObject.

        Args:
            signature: The signature of the init function.
            resource_cls: The resource class to get type hints from.
        """
        if isinstance(resource_cls, list):
            return {name: hint for cls_ in resource_cls for name, hint in cls.get_type_hints_by_name(cls_).items()}
        if not hasattr(resource_cls, "__init__"):
            return {}
        try:
            type_hint_by_name = get_type_hints(resource_cls.__init__, localns=cls._type_checking())  # type: ignore[misc]
        except (TypeError, NameError):
            # Python 3.10 Type hints cannot be evaluated with get_type_hints,
            # ref https://stackoverflow.com/questions/66006087/how-to-use-typing-get-type-hints-with-pep585-in-python3-8
            resource_module_vars = vars(importlib.import_module(resource_cls.__module__))
            resource_module_vars.update(cls._type_checking())
            signature = inspect.signature(resource_cls.__init__)  # type: ignore[misc]
            type_hint_by_name = cls._get_type_hints_3_10(resource_module_vars, signature, dict(vars(resource_cls)))
        return type_hint_by_name

    @classmethod
    def _type_checking(cls) -> dict[str, type]:
        """
        When calling the get_type_hints function, it imports the module with the function TYPE_CHECKING is set to False.

        This function takes all the special types used in data classes and returns them as a dictionary so it
        can be used in the local namespaces.
        """
        import numpy as np
        import numpy.typing as npt
        from cognite.client import CogniteClient
        from cognite.client.data_classes.data_modeling import ContainerId, ViewId

        return {
            "CogniteClient": CogniteClient,
            "NumpyDatetime64NSArray": npt.NDArray[np.datetime64],
            "NumpyUInt32Array": npt.NDArray[np.uint32],
            "NumpyInt64Array": npt.NDArray[np.int64],
            "NumpyFloat64Array": npt.NDArray[np.float64],
            "NumpyObjArray": npt.NDArray[np.object_],
            # These are imported locally in the HasData filter classes
            # and are thus not in the module or class namespace
            "ViewId": ViewId,
            "ContainerId": ContainerId,
        }

    @classmethod
    def _get_type_hints_3_10(
        cls, resource_module_vars: dict[str, Any], signature310: inspect.Signature, local_vars: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            name: cls._create_type_hint_3_10(parameter.annotation, resource_module_vars, local_vars)
            for name, parameter in signature310.parameters.items()
            if name != "self"
        }

    @classmethod
    def _create_type_hint_3_10(
        cls, annotation: str, resource_module_vars: dict[str, Any], local_vars: dict[str, Any]
    ) -> Any:
        if annotation.endswith(" | None"):
            annotation = annotation[:-7]
        annotation = annotation.replace("SequenceNotStr", "Sequence")
        try:
            return eval(annotation, resource_module_vars, local_vars)
        except (TypeError, NameError):
            # Python 3.10 Type Hint
            return cls._type_hint_3_10_to_8(annotation, resource_module_vars, local_vars)

    @classmethod
    @typing.no_type_check
    def _type_hint_3_10_to_8(
        cls, annotation: str, resource_module_vars: dict[str, Any], local_vars: dict[str, Any]
    ) -> Any:
        if cls._is_vertical_union(annotation):
            alternatives = [
                cls._create_type_hint_3_10(a.strip(), resource_module_vars, local_vars) for a in annotation.split("|")
            ]
            return typing.Union[tuple(alternatives)]
        elif annotation.startswith("dict[") and annotation.endswith("]"):
            if Counter(annotation)[","] > 1:
                # Regex pattern to split on the first comma not inside square brackets
                pattern = r",(?!(?:[^\[]*\[[^\]]*\])*[^\]]*\])"
                key, rest = re.split(pattern, annotation[5:-1], maxsplit=1)
                key_hint = cls._create_type_hint_3_10(key.strip(), resource_module_vars, local_vars)
                value_hint = cls._create_type_hint_3_10(rest.strip(), resource_module_vars, local_vars)
                return dict[key_hint, value_hint]  # type: ignore[misc, valid-type]
            key, value = annotation[5:-1].split(",")
            return dict[  # type: ignore[misc]
                cls._create_type_hint_3_10(key.strip(), resource_module_vars, local_vars),
                cls._create_type_hint_3_10(value.strip(), resource_module_vars, local_vars),
            ]
        elif annotation.startswith("Mapping[") and annotation.endswith("]"):
            if Counter(annotation)[","] > 1:
                key, rest = annotation[8:-1].split(",", 1)
                return typing.Mapping[  # type: ignore[misc]
                    key.strip(), cls._create_type_hint_3_10(rest.strip(), resource_module_vars, local_vars)
                ]
            key, value = annotation[8:-1].split(",")
            return typing.Mapping[  # type: ignore[misc]
                cls._create_type_hint_3_10(key.strip(), resource_module_vars, local_vars),
                cls._create_type_hint_3_10(value.strip(), resource_module_vars, local_vars),
            ]
        elif annotation.startswith("Optional[") and annotation.endswith("]"):
            return typing.Optional[cls._create_type_hint_3_10(annotation[9:-1], resource_module_vars, local_vars)]
        elif annotation.startswith("list[") and annotation.endswith("]"):
            return list[cls._create_type_hint_3_10(annotation[5:-1], resource_module_vars, local_vars)]  # type: ignore[misc]
        elif annotation.startswith("tuple[") and annotation.endswith("]"):
            return tuple[cls._create_type_hint_3_10(annotation[6:-1], resource_module_vars, local_vars)]  # type: ignore[misc]
        elif annotation.startswith("typing.Sequence[") and annotation.endswith("]"):
            # This is used in the Sequence data class file to avoid name collision
            return typing.Sequence[cls._create_type_hint_3_10(annotation[16:-1], resource_module_vars, local_vars)]  # type: ignore[misc]
        elif annotation.startswith("Sequence[") and annotation.endswith("]"):
            return typing.Sequence[cls._create_type_hint_3_10(annotation[9:-1], resource_module_vars, local_vars)]  # type: ignore[misc]
        elif annotation.startswith("Collection[") and annotation.endswith("]"):
            return typing.Collection[cls._create_type_hint_3_10(annotation[11:-1], resource_module_vars, local_vars)]  # type: ignore[misc]
        elif annotation.startswith("Literal[") and annotation.endswith("]"):
            return typing.Literal[cls._create_type_hint_3_10(annotation[8:-1], resource_module_vars, local_vars)]  # type: ignore[misc]
        raise NotImplementedError(f"Unsupported conversion of type hint {annotation!r}. {cls._error_msg}")

    @classmethod
    def _is_vertical_union(cls, annotation: str) -> bool:
        if "|" not in annotation:
            return False
        parts = [p.strip() for p in annotation.split("|")]
        for part in parts:
            counts = Counter(part)
            if counts["["] != counts["]"]:
                return False
        return True
