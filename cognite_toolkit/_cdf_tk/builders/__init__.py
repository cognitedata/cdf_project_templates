from pathlib import Path

from ._base import Builder, DefaultBuilder, get_loader
from ._datamodels import DataModelBuilder
from ._file import FileBuilder
from ._function import FunctionBuilder
from ._raw import RawBuilder
from ._streamlit import StreamlitBuilder
from ._transformation import TransformationBuilder


def create_builder(
    resource_folder: str,
    build_dir: Path | None,
) -> Builder:
    if builder_cls := _BUILDER_BY_RESOURCE_FOLDER.get(resource_folder):
        return builder_cls(build_dir)  # type: ignore[abstract]

    return DefaultBuilder(build_dir, resource_folder)


_BUILDER_BY_RESOURCE_FOLDER = {_builder._resource_folder: _builder for _builder in Builder.__subclasses__()}

__all__ = [
    "Builder",
    "DataModelBuilder",
    "DefaultBuilder",
    "FileBuilder",
    "FunctionBuilder",
    "IdentifierBuilder",
    "RawBuilder",
    "StreamlitBuilder",
    "TransformationBuilder",
    "create_builder",
    "get_loader",
]
