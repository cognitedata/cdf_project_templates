from __future__ import annotations

from abc import abstractmethod
from pathlib import Path
from typing import Any

from rich import print
from rich.panel import Panel

from .constants import MODULES, ROOT_MODULES, URL
from .exceptions import ToolkitFileNotFoundError, ToolkitNotADirectoryError
from .loaders import LOADER_BY_FOLDER_NAME
from .utils import find_directory_with_subdirectories


class Hint:
    _indent = " " * 5
    _lead_text = "[bold blue]HINT[/bold blue] "

    @classmethod
    @abstractmethod
    def _short(cls) -> str: ...

    @classmethod
    @abstractmethod
    def long(cls, *args: Any, **kwargs: Any) -> list[str]: ...

    @classmethod
    def short(cls) -> str:
        return f"{cls._lead_text}{cls._short()}"

    @classmethod
    def _to_hint(cls, lines: list[str]) -> str:
        return cls._lead_text + f"\n{cls._indent}".join(lines)

    @classmethod
    def _link(cls, url: str, text: str | None = None) -> str:
        return f"[blue][link={url}]{text or url}[/link][/blue]"


class ModuleDefinition(Hint):
    @classmethod
    def _short(cls) -> str:
        return f"Available resource directories are {sorted(LOADER_BY_FOLDER_NAME)}. {cls._link(URL.configs)} to learn more."

    @classmethod
    def long(cls, missing_modules: set[str | Path] | None = None, organization_dir: Path | None = None) -> str:  # type: ignore[override]
        lines = [
            "A module is a directory with one or more resource directories in it.",
            f"Available resource directories are {sorted(LOADER_BY_FOLDER_NAME)}",
            f"{cls._link(URL.configs)} to learn more",
        ]
        if missing_modules and organization_dir:
            found_directory, subdirectories = find_directory_with_subdirectories(
                next((m for m in missing_modules if isinstance(m, str)), None), organization_dir
            )
            if found_directory:
                lines += [
                    f"For example, the directory {found_directory.as_posix()!r} is not a module, as none of its",
                    f"subdirectories are resource directories. The subdirectories found are: {subdirectories}",
                ]
        return cls._to_hint(lines)


def verify_module_directory(organization_dir: Path, build_env_name: str) -> None:
    from .data_classes import BuildConfigYAML

    config_file = BuildConfigYAML.get_filename(build_env_name)

    if organization_dir != Path.cwd():
        panel = Panel(
            f"Toolkit expects the following structure:\n"
            f"{organization_dir!s}/\n"
            f"  ┣ {MODULES}/\n"
            f"  ┗ {config_file}\n",
            expand=False,
        )
    else:
        panel = Panel(
            f"Toolkit expects the following structure:\n" f"  {MODULES}/\n" f"  {config_file}\n",
            expand=False,
        )
    if not organization_dir.is_dir():
        print(panel)
        raise ToolkitNotADirectoryError(f"{organization_dir.as_posix()!r} is not a directory.")

    root_modules = [
        module_dir for root_module in ROOT_MODULES if (module_dir := organization_dir / root_module).exists()
    ]
    config_path = organization_dir / config_file
    if root_modules and config_path.is_file():
        return
    if root_modules or config_path.is_file():
        print(panel)
        if not root_modules:
            raise ToolkitNotADirectoryError(f"Could not find the {(organization_dir/ MODULES).as_posix()!r} directory.")
        raise ToolkitFileNotFoundError(f"Could not find the {config_path.as_posix()!r} file.")

    raise ValueError()
