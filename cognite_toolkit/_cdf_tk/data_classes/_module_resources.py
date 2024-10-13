from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any, ClassVar

import yaml

from cognite_toolkit import _version
from cognite_toolkit._cdf_tk.cdf_toml import CDFToml
from cognite_toolkit._cdf_tk.constants import DEFAULT_ENV
from cognite_toolkit._cdf_tk.loaders import ResourceTypes
from cognite_toolkit._cdf_tk.loaders._base_loaders import T_ID
from cognite_toolkit._cdf_tk.utils import (
    safe_write,
    tmp_build_directory,
)

from ._base import ConfigCore
from ._build_variables import BuildVariables
from ._built_modules import BuiltModule, BuiltModuleList
from ._built_resources import BuiltFullResourceList
from ._config_yaml import BuildConfigYAML
from ._module_directories import ModuleDirectories


@dataclass
class ModulesInfo:
    version: str
    modules: BuiltModuleList

    @classmethod
    def load(cls, data: dict[str, Any]) -> ModulesInfo:
        return cls(
            version=data["version"],
            modules=BuiltModuleList([BuiltModule.load(module_data) for module_data in data["modules"]]),
        )

    def dump(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "modules": [module.dump() for module in self.modules],
        }


@dataclass
class BuildInfo(ConfigCore):
    filename: ClassVar[str] = "build_info.{build_env}.yaml"
    top_warning: ClassVar[str] = "# DO NOT MODIFY THIS FILE MANUALLY. IT IS AUTO-GENERATED BY THE COGNITE TOOLKIT."
    modules: ModulesInfo

    @classmethod
    def load(cls, data: dict[str, Any], build_env: str, filepath: Path) -> BuildInfo:
        return cls(filepath, ModulesInfo.load(data["modules"]))

    @classmethod
    def rebuild(
        cls, organization_dir: Path, build_env: str | None, needs_rebuild: set[Path] | None = None
    ) -> BuildInfo:
        # To avoid circular imports
        # Ideally, this class should be in a separate module
        from cognite_toolkit._cdf_tk.commands.build import BuildCommand

        with tmp_build_directory() as build_dir:
            cdf_toml = CDFToml.load()
            if build_env is None:
                config = BuildConfigYAML.load_default(organization_dir)
            else:
                config = BuildConfigYAML.load_from_directory(organization_dir, build_env)
            config.set_environment_variables()
            # Todo Remove once the new modules in `_cdf_tk/prototypes/_packages` are finished.
            config.variables.pop("_cdf_tk", None)
            if needs_rebuild is None:
                # Use path syntax to select all modules in the source directory
                config.environment.selected = [Path("")]
            else:
                # Use path syntax to select only the modules that need to be rebuilt
                config.environment.selected = list(needs_rebuild)
            build = BuildCommand(silent=True, skip_tracking=True).build_config(
                build_dir=build_dir,
                organization_dir=organization_dir,
                config=config,
                packages=cdf_toml.modules.packages,
                clean=True,
                verbose=False,
                progress_bar=True,
            )

        new_build = cls(
            filepath=organization_dir / cls.get_filename(build_env or DEFAULT_ENV),
            modules=ModulesInfo(version=_version.__version__, modules=build),
        )
        if needs_rebuild is not None and (existing := cls._get_existing(organization_dir, build_env or DEFAULT_ENV)):
            # Merge the existing modules with the new modules
            new_modules_by_path = {module.location.path: module for module in new_build.modules.modules}
            existing_modules_by_path = {module.location.path: module for module in existing.modules.modules}
            all_module_paths = set(new_modules_by_path) | set(existing_modules_by_path)

            module_list = BuiltModuleList(
                [
                    new_modules_by_path[path] if path in new_modules_by_path else existing_modules_by_path[path]
                    for path in all_module_paths
                ]
            )
            new_build.modules.modules = module_list

        new_build.dump_to_file()
        return new_build

    @classmethod
    def _get_existing(cls, organization_dir: Path, build_env: str) -> BuildInfo | None:
        try:
            existing = cls.load_from_directory(organization_dir, build_env)
        except FileNotFoundError:
            return None
        if existing.modules.version != _version.__version__:
            return None
        return existing

    def dump(self) -> dict[str, Any]:
        return {
            "modules": self.modules.dump(),
        }

    def dump_to_file(self) -> None:
        dumped = self.dump()
        # Avoid dumping pointer references: https://stackoverflow.com/questions/51272814/python-yaml-dumping-pointer-references
        yaml.Dumper.ignore_aliases = lambda *args: True  # type: ignore[method-assign]
        content = yaml.safe_dump(dumped, sort_keys=False)
        content = f"{self.top_warning}\n{content}"
        safe_write(self.filepath, content)

    def compare_modules(
        self,
        current_modules: ModuleDirectories,
        current_variables: BuildVariables,
        resource_dirs: set[str] | None = None,
    ) -> set[Path]:
        current_module_by_path = {module.relative_path: module for module in current_modules}
        cached_module_by_path = {module.location.path: module for module in self.modules.modules}
        needs_rebuild = set()
        for path, current_module in current_module_by_path.items():
            if resource_dirs is not None and all(
                resource_dir not in current_module.resource_directories for resource_dir in resource_dirs
            ):
                # The module does not contain any of the specified resources, so it does not need to be rebuilt.
                continue

            if path not in cached_module_by_path:
                needs_rebuild.add(path)
                continue
            cached_module = cached_module_by_path[path]
            if current_module.hash != cached_module.location.hash:
                needs_rebuild.add(path)
            current_module_variables = current_variables.get_module_variables(current_module)
            if set(current_module_variables) != set(cached_module.build_variables):
                needs_rebuild.add(path)
        return needs_rebuild


class ModuleResources:
    """This class is used to retrieve resource information from the build info.

    It is responsible for ensuring that the build info is up-to-date with the
    latest changes in the source directory.
    """

    def __init__(self, organization_dir: Path, build_env: str | None) -> None:
        self._organization_dir = organization_dir
        self._build_env = build_env
        self._build_info: BuildInfo
        try:
            self._build_info = BuildInfo.load_from_directory(organization_dir, build_env)
            self._has_rebuilt = False
        except (FileNotFoundError, KeyError):
            # FileNotFound = Not run before.
            # KeyError = Version mismatch/Changed format
            self._build_info = BuildInfo.rebuild(organization_dir, build_env)
            self._has_rebuilt = True

    @cached_property
    def _current_modules(self) -> ModuleDirectories:
        return ModuleDirectories.load(self._organization_dir, {Path("")})

    @cached_property
    def _current_variables(self) -> BuildVariables:
        config_yaml = BuildConfigYAML.load_from_directory(self._organization_dir, self._build_env)
        return BuildVariables.load_raw(
            config_yaml.variables, self._current_modules.available_paths, self._current_modules.selected.available_paths
        )

    def list_resources(
        self, id_type: type[T_ID], resource_dir: ResourceTypes, kind: str
    ) -> BuiltFullResourceList[T_ID]:
        if not self._has_rebuilt:
            if needs_rebuild := self._build_info.compare_modules(
                self._current_modules, self._current_variables, {resource_dir}
            ):
                self._build_info = BuildInfo.rebuild(self._organization_dir, self._build_env, needs_rebuild)
        return self._build_info.modules.modules.get_resources(id_type, resource_dir, kind)

    def list(self) -> BuiltModuleList:
        # Check if the build info is up to date
        if not self._has_rebuilt:
            if needs_rebuild := self._build_info.compare_modules(self._current_modules, self._current_variables):
                self._build_info = BuildInfo.rebuild(self._organization_dir, self._build_env, needs_rebuild)
            self._has_rebuilt = True
        return self._build_info.modules.modules
