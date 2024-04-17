from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from cognite_toolkit import _version
from cognite_toolkit._cdf_tk.exceptions import ToolkitConfigError, ToolkitFileNotFound, ToolkitVersionError
from cognite_toolkit._cdf_tk.templates import BUILD_ENVIRONMENT_FILE
from cognite_toolkit._cdf_tk.utils import read_yaml_file


@dataclass
class ConfigCore(ABC):
    """Base class for the two build config files (global.yaml and [env].config.yaml)"""

    filepath: Path

    @classmethod
    @abstractmethod
    def _file_name(cls, build_env: str) -> str:
        raise NotImplementedError

    @classmethod
    def load_from_directory(cls: type[T_BuildConfig], source_path: Path, build_env: str) -> T_BuildConfig:
        file_name = cls._file_name(build_env)
        filepath = source_path / file_name
        filepath = filepath if filepath.is_file() else Path.cwd() / file_name
        if not filepath.is_file():
            raise ToolkitFileNotFound(f"{filepath.name!r} does not exist")

        return cls.load(read_yaml_file(filepath), build_env, filepath)

    @classmethod
    @abstractmethod
    def load(cls: type[T_BuildConfig], data: dict[str, Any], build_env: str, filepath: Path) -> T_BuildConfig:
        raise NotImplementedError


T_BuildConfig = TypeVar("T_BuildConfig", bound=ConfigCore)


def _load_version_variable(data: dict[str, Any], file_name: str) -> str:
    try:
        cdf_tk_version: str = data["cdf_toolkit_version"]
    except KeyError:
        err_msg = f"System variables are missing required field 'cdf_toolkit_version' in {file_name!s}. {{}}"
        if file_name == BUILD_ENVIRONMENT_FILE:
            raise ToolkitConfigError(
                err_msg.format("Rerun `cdf-tk build` to build the templates again and create it correctly.")
            )
        raise ToolkitConfigError(
            err_msg.format("Run `cdf-tk init --upgrade` to initialize the templates again to create a correct file.")
        )

    if cdf_tk_version != _version.__version__:
        raise ToolkitVersionError(
            "The version of the templates ({cdf_tk_version}) does not match the version of the installed package "
            f"({_version.__version__}). Please either run `cdf-tk init --upgrade` to upgrade the templates OR "
            f"run `pip install cognite-toolkit=={cdf_tk_version}` to downgrade cdf-tk."
        )
    return cdf_tk_version
