from __future__ import annotations

import sys
from collections.abc import Iterable, MutableMapping, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, overload

from ._module_directories import ModuleDirectories, ModuleLocation
from ._module_toml import ModuleToml
from cognite_toolkit._cdf_tk.exceptions import ToolkitFileNotFoundError

if sys.version_info >= (3, 11):
    import toml
else:
    import tomli as toml


@dataclass
class Package:
    """A package represents a bundle of modules.
    Args:
        name: the unique identifier of the package.
        title: The display name of the package.
        description: A description of the package.
        modules: The modules that are part of the package.
    """

    name: str
    title: str
    description: str | None = None
    modules: list[ModuleLocation] = field(default_factory=list)

    @classmethod
    def load(cls, name: str, package_definition: dict) -> Package:
        return cls(
            name=name,
            title=package_definition["title"],
            description=package_definition.get("description"),
        )


class Packages(dict, MutableMapping[str, Package]):
    def __init__(self, packages: Iterable[Package] | Mapping[str, Package] | None = None) -> None:
        if packages is None:
            super().__init__()
        elif isinstance(packages, Mapping):
            super().__init__(packages)
        else:
            super().__init__({p.name: p for p in packages})

    @classmethod
    def load(
        cls,
        root_module_dir: Path,  # todo: relative to org dir
    ) -> Packages:
        """Loads the packages in the source directory.

        Args:
            root_module_dir: The module directories to load the packages from.
        """

        package_definition_path = root_module_dir / "package.toml"
        if not package_definition_path.exists():
            raise ToolkitFileNotFoundError(f"Package manifest toml not found at {package_definition_path}")
        package_definitions = toml.loads(package_definition_path.read_text())["packages"]

        collected: dict[str, Package] = {
            package_name: Package.load(package_name, package_definition)
            for package_name, package_definition in package_definitions.items()
            if isinstance(package_definition, dict)
        }

        module_directories = ModuleDirectories.load(root_module_dir)
        for module in module_directories:
            if module.definition is None:
                continue
            for tag in module.definition.tags:
                if tag in collected:
                    collected[tag].modules.append(module)
        return cls(collected)
