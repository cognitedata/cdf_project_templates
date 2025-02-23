from __future__ import annotations

import dataclasses
import re
import tempfile
import uuid
from collections import UserList
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Union

import questionary
import yaml
from cognite.client.data_classes._base import T_CogniteResourceList, T_WritableCogniteResource, T_WriteClass
from questionary import Choice
from rich import print
from rich.markdown import Markdown
from rich.panel import Panel

from cognite_toolkit._cdf_tk.builders import create_builder
from cognite_toolkit._cdf_tk.client import ToolkitClient
from cognite_toolkit._cdf_tk.constants import BUILD_ENVIRONMENT_FILE, ENV_VAR_PATTERN
from cognite_toolkit._cdf_tk.data_classes import (
    BuildEnvironment,
    BuildVariable,
    BuildVariables,
    BuiltFullResourceList,
    BuiltModuleList,
    BuiltResourceFull,
    DeployResults,
    ModuleDirectories,
    ResourceDeployResult,
    YAMLComments,
)
from cognite_toolkit._cdf_tk.exceptions import ToolkitError, ToolkitMissingResourceError, ToolkitValueError
from cognite_toolkit._cdf_tk.loaders import (
    ExtractionPipelineConfigLoader,
    FunctionLoader,
    GraphQLLoader,
    HostedExtractorDestinationLoader,
    HostedExtractorSourceLoader,
    ResourceLoader,
    StreamlitLoader,
)
from cognite_toolkit._cdf_tk.loaders._base_loaders import T_ID, T_WritableCogniteResourceList
from cognite_toolkit._cdf_tk.tk_warnings import LowSeverityWarning, MediumSeverityWarning
from cognite_toolkit._cdf_tk.utils import (
    YAMLComment,
    YAMLWithComments,
    read_yaml_content,
    read_yaml_file,
    safe_read,
)
from cognite_toolkit._cdf_tk.utils.auth import EnvironmentVariables
from cognite_toolkit._cdf_tk.utils.file import safe_rmtree, yaml_safe_dump
from cognite_toolkit._cdf_tk.utils.modules import (
    is_module_path,
    module_directory_from_path,
    parse_user_selected_modules,
)

from ._base import ToolkitCommand
from .build import BuildCommand
from .clean import CleanCommand

_VARIABLE_PATTERN = re.compile(r"\{\{(.+?)\}\}")
# The encoding and newline characters to use when writing files
# These are hardcoded to ensure that running the pull command on different platforms
# will produce the same output. The motivation is when having local sources in
# version control, the diff will be easier to read.
ENCODING = "utf-8"
NEWLINE = "\n"


@dataclass
class Variable:
    placeholder: str | None = None
    name: str | None = None
    source_value: str | None = None


@dataclass
class ResourceProperty:
    """This represents a single property in a CDF resource file.

    Args:
        key_path: The path to the property in the resource file.
        build_value: The value of the property in the local resource file build file.
        cdf_value: The value of the property in the CDF resource.
        variables: A list of variables that are used in the property value.
    """

    key_path: tuple[str | int, ...]
    build_value: float | int | str | bool | None = None
    cdf_value: float | int | str | bool | None = None
    variables: list[Variable] = field(default_factory=list)

    @property
    def value(self) -> float | int | str | bool | None:
        if self.has_variables:
            return self.variables[0].source_value
        return self.cdf_value or self.build_value

    @property
    def has_variables(self) -> bool:
        return bool(self.variables)

    @property
    def is_changed(self) -> bool:
        return (
            self.build_value != self.cdf_value
            and self.build_value is not None
            and self.cdf_value is not None
            and not self.has_variables
        )

    @property
    def is_added(self) -> bool:
        return self.build_value is None and self.cdf_value is not None

    @property
    def is_cannot_change(self) -> bool:
        return (
            self.build_value != self.cdf_value
            and not self.has_variables
            and self.build_value is not None
            and self.cdf_value is not None
        )

    def __str__(self) -> str:
        key_str = ".".join(map(str, self.key_path))
        if self.is_added:
            return f"ADDED: '{key_str}: {self.cdf_value}'"
        elif self.is_changed:
            return f"CHANGED: '{key_str}: {self.build_value} -> {self.cdf_value}'"
        elif self.is_cannot_change:
            return f"CANNOT CHANGE (contains variables): '{key_str}: {self.build_value} -> {self.cdf_value}'"
        else:
            return f"UNCHANGED: '{key_str}: {self.build_value}'"


class ResourceYAMLDifference(YAMLWithComments[tuple[Union[str, int], ...], ResourceProperty]):
    """This represents a YAML file that contains resources and their properties.

    It is used to compare a local resource file with a CDF resource.
    """

    def __init__(
        self,
        items: dict[tuple[str | int, ...], ResourceProperty],
        comments: dict[tuple[str, ...], YAMLComment] | None = None,
    ) -> None:
        super().__init__(items or {})
        self._comments = comments or {}

    def _get_comment(self, key: tuple[str, ...]) -> YAMLComment | None:
        return self._comments.get(key)

    @classmethod
    def load(cls, build_content: str, source_content: str) -> ResourceYAMLDifference:
        comments = cls._extract_comments(build_content)
        build = read_yaml_content(build_content)
        build_flatten = cls._flatten(build)
        items: dict[tuple[str | int, ...], ResourceProperty] = {}
        for key, value in build_flatten.items():
            items[key] = ResourceProperty(
                key_path=key,
                build_value=value,
            )

        source_content, variable_by_placeholder = cls._replace_variables(source_content)
        source = read_yaml_content(source_content)
        source_items = cls._flatten(source)
        for key, value in source_items.items():
            for placeholder, variable in variable_by_placeholder.items():
                if placeholder in str(value):
                    items[key].variables.append(
                        Variable(
                            placeholder=placeholder,
                            name=variable_by_placeholder[placeholder],
                            source_value=str(value),
                        )
                    )
        return cls(items, comments)

    @classmethod
    def _flatten(
        cls, raw: dict[str, Any] | list[dict[str, Any]]
    ) -> dict[tuple[str | int, ...], str | int | float | bool | None]:
        if isinstance(raw, dict):
            return cls._flatten_dict(raw)
        elif isinstance(raw, list):
            raise NotImplementedError()
        else:
            raise ValueError(f"Expected a dictionary or list, got {type(raw)}")

    @classmethod
    def _flatten_dict(
        cls, raw: dict[str, Any], key_path: tuple[str | int, ...] = ()
    ) -> dict[tuple[str | int, ...], str | int | float | bool | None]:
        items: dict[tuple[str | int, ...], str | int | float | bool | None] = {}
        for key, value in raw.items():
            if key == "scopes":
                # Hack to handle that scopes is a list variable
                items[(*key_path, key)] = value
            elif isinstance(value, dict):
                items.update(cls._flatten_dict(value, (*key_path, key)))
            elif isinstance(value, list):
                for i, item in enumerate(value):
                    if isinstance(item, dict):
                        items.update(cls._flatten_dict(item, (*key_path, key, i)))
                    else:
                        items[(*key_path, key, i)] = item
            else:
                items[(*key_path, key)] = value
        return items

    @classmethod
    def _replace_variables(cls, content: str) -> tuple[str, dict[str, str]]:
        variable_by_placeholder: dict[str, str] = {}
        seen: set[str] = set()
        for match in _VARIABLE_PATTERN.finditer(content):
            variable = match.group(1)
            if variable in seen:
                continue
            placeholder = f"VARIABLE_{uuid.uuid4().hex[:8]}"
            content = content.replace(f"{{{{{variable}}}}}", placeholder)
            variable_by_placeholder[placeholder] = variable
            seen.add(variable)
        return content, variable_by_placeholder

    def update_cdf_resource(self, cdf_resource: dict[str, Any]) -> None:
        for key, value in self._flatten_dict(cdf_resource).items():
            if key in self:
                self[key].cdf_value = value
            else:
                self[key] = ResourceProperty(key_path=key, cdf_value=value)

    def dump(self) -> dict[Any, Any]:
        dumped: dict[Any, Any] = {}
        for key, prop in self.items():
            current = dumped
            for part, next_part in zip(key[:-1], key[1:]):
                if isinstance(part, int) and isinstance(current, list) and len(current) < part + 1:
                    current.append({})
                    current = current[part]
                elif isinstance(part, int) and isinstance(current, list) and part < len(current):
                    current = current[part]
                elif isinstance(part, str) and isinstance(next_part, str):
                    current = current.setdefault(part, {})
                elif isinstance(part, str) and isinstance(next_part, int):
                    current = current.setdefault(part, [])
                else:
                    raise ValueError(f"Expected a string or int, got {type(part)}")
            if isinstance(key[-1], int) and isinstance(current, list):
                current.append(prop.value)
            elif isinstance(key[-1], str) and isinstance(current, dict):
                current[key[-1]] = prop.value
            else:
                raise ValueError(f"Expected a string or int, got {type(key[-1])}")
        return dumped

    def dump_yaml_with_comments(self, indent_size: int = 2) -> str:
        """Dump a config dictionary to a yaml string"""
        dumped_with_comments = self._dump_yaml_with_comments(indent_size, False)
        for key, prop in self.items():
            for variable in prop.variables:
                if variable.placeholder:
                    dumped_with_comments = dumped_with_comments.replace(
                        variable.placeholder, f"{{{{{variable.name}}}}}"
                    )
        return dumped_with_comments

    def display(self, title: str | None = None) -> None:
        added = [prop for prop in self.values() if prop.is_added]
        changed = [prop for prop in self.values() if prop.is_changed]
        cannot_change = [prop for prop in self.values() if prop.is_cannot_change]
        unchanged = [
            prop for prop in self.values() if not prop.is_added and not prop.is_changed and not prop.is_cannot_change
        ]

        content: list[str] = []
        if added:
            content.append("\n**Added properties**(Either set in CDF UI or default values set by CDF):")
            content.extend([f" - {prop}" for prop in added])
        if changed:
            content.append("\n**Changed properties:**")
            content.extend([f" - {prop}" for prop in changed])
        if cannot_change:
            content.append("\n**Cannot change properties**")
            content.extend([f" - {prop}" for prop in cannot_change])
        if unchanged:
            content.append(f"\n**{len(unchanged)} properties unchanged**")

        print(Panel.fit(Markdown("\n".join(content), justify="left"), title=title or "Resource differences"))


@dataclass
class Line:
    line_no: int
    build_value: str | None = None
    source_value: str | None = None
    cdf_value: str | None = None
    variables: list[str] | None = None

    @property
    def value(self) -> str:
        if self.variables:
            if self.source_value is None:
                raise ValueError("Source value should be set if there are variables")
            return self.source_value
        value = self.cdf_value or self.build_value
        if value is None:
            raise ValueError("CDF value or build value should be set")
        return value

    @property
    def is_changed(self) -> bool:
        return (
            self.build_value != self.cdf_value
            and self.build_value is not None
            and self.cdf_value is not None
            and self.variables is None
        )

    @property
    def is_added(self) -> bool:
        return self.build_value is None and self.cdf_value is not None

    @property
    def is_cannot_change(self) -> bool:
        return (
            self.build_value != self.cdf_value
            and self.variables is not None
            and self.build_value is not None
            and self.cdf_value is not None
        )


class TextFileDifference(UserList):
    def __init__(self, lines: list[Line] | None) -> None:
        super().__init__(lines or [])

    @classmethod
    def load(cls, build_content: str, source_content: str) -> TextFileDifference:
        lines = []
        # Build and source content should have the same number of lines
        for no, (build, source) in enumerate(zip(build_content.splitlines(), source_content.splitlines())):
            variables = [v.group(1) for v in _VARIABLE_PATTERN.finditer(source)] or None
            lines.append(
                Line(
                    line_no=no + 1,
                    build_value=build,
                    source_value=source,
                    variables=variables,
                )
            )
        return cls(lines)

    def update_cdf_content(self, cdf_content: str) -> None:
        for i, line in enumerate(cdf_content.splitlines()):
            if i < len(self):
                self[i].cdf_value = line
            else:
                self.append(Line(cdf_value=line, line_no=i + 1))

    def dump(self) -> str:
        return "\n".join(line.value for line in self) + "\n"

    def display(self, title: str | None = None) -> None:
        added = [line for line in self if line.is_added]
        changed = [line for line in self if line.is_changed]
        cannot_change = [line for line in self if line.is_cannot_change]
        unchanged_count = len(self) - len(added) - len(changed) - len(cannot_change)

        content: list[str] = []
        if added:
            content.append("\n**Added lines**")
            if len(added) == 1:
                content.append(f" - Line {added[0].line_no}: '{added[0].cdf_value}'")
            else:
                content.append(f" - Line {added[0].line_no} - {added[-1].line_no}: {len(added)} lines")
        if changed:
            content.append("\n**Changed lines**")
            if len(changed) == 1:
                content.append(f" - Line {changed[0].line_no}: '{changed[0].source_value}' -> '{changed[0].cdf_value}'")
            else:
                content.append(f" - Line {changed[0].line_no} - {changed[-1].line_no}: {len(changed)} lines")
        if cannot_change:
            content.append("\n**Cannot change lines**")
            if len(cannot_change) == 1:
                content.append(
                    f" - Line {cannot_change[0].line_no}: '{cannot_change[0].source_value}' -> '{cannot_change[0].cdf_value}'"
                )
            else:
                content.append(
                    f" - Line {cannot_change[0].line_no} - {cannot_change[-1].line_no}: {len(cannot_change)} lines"
                )
        if unchanged_count != 0:
            content.append(f"\n**{unchanged_count} lines unchanged**")

        print(Panel.fit(Markdown("\n".join(content), justify="left"), title=title or "File differences"))


class PullCommand(ToolkitCommand):
    def __init__(self, print_warning: bool = True, skip_tracking: bool = False, silent: bool = False) -> None:
        super().__init__(print_warning, skip_tracking, silent)
        self._clean_command = CleanCommand(print_warning, skip_tracking=True)

    def pull_module(
        self,
        module_name_or_path: str | Path | None,
        organization_dir: Path,
        env: str,
        dry_run: bool,
        verbose: bool,
        env_vars: EnvironmentVariables,
    ) -> None:
        client = env_vars.get_client()
        if not module_name_or_path:
            modules = ModuleDirectories.load(organization_dir, None)
            if not modules:
                raise ToolkitValueError(
                    "No module argument provided and no modules found in the organization directory."
                )

            selected = questionary.select(
                "Select a module to pull",
                choices=[Choice(title=module.name, value=module.name) for module in modules],
            ).ask()
        else:
            selected = parse_user_selected_modules([module_name_or_path])[0]
        build_module: str | Path
        if isinstance(selected, str):
            build_module = selected
        elif isinstance(selected, Path):
            try:
                # If the selected path is a sub-path of a module, we
                # need to build the entire module.
                build_module = module_directory_from_path(selected)
            except ValueError:
                # Remove this if-statement and set the build_module to selected
                # to support pulling more than one module.
                if is_module_path(selected):
                    build_module = selected
                else:
                    raise ToolkitValueError(
                        "Select module or a sub-path of a module. Multiple modules are not supported."
                    )
        else:
            raise ValueError("Expected a string or Path")
        build_cmd = BuildCommand(silent=True, skip_tracking=True)
        build_dir = Path(tempfile.mkdtemp())
        try:
            built_modules = build_cmd.execute(
                verbose=verbose,
                organization_dir=organization_dir,
                build_dir=build_dir,
                selected=[build_module],
                build_env_name=env,
                no_clean=False,
                client=client,
                on_error="raise",
                accept_invalid_files=True,
            )
        except ToolkitError as e:
            raise ToolkitError(f"Failed to build module {module_name_or_path}.") from e
        else:
            self._pull_build_dir(build_dir, selected, built_modules, dry_run, env, client, env_vars)
        finally:
            try:
                safe_rmtree(build_dir)
            except Exception as e:
                raise ToolkitError(f"Failed to clean up temporary build directory {build_dir}.") from e

    def _pull_build_dir(
        self,
        build_dir: Path,
        selected: Path | str,
        built_modules: BuiltModuleList,
        dry_run: bool,
        build_env_name: str,
        client: ToolkitClient,
        env_vars: EnvironmentVariables,
    ) -> None:
        build_environment_file_path = build_dir / BUILD_ENVIRONMENT_FILE
        built = BuildEnvironment.load(read_yaml_file(build_environment_file_path), build_env_name, "pull")
        selected_loaders = self._clean_command.get_selected_loaders(
            build_dir, read_resource_folders=built.read_resource_folders, include=None
        )

        if len(selected_loaders) == 0:
            if isinstance(selected, Path):
                self.warn(LowSeverityWarning(f"No valid resource recognized at {selected.as_posix()}"))
            else:
                self.warn(LowSeverityWarning(f"No valid resources recognized in {selected}"))
            return

        results = DeployResults([], action="pull", dry_run=dry_run)
        for loader_cls in selected_loaders:
            if not issubclass(loader_cls, ResourceLoader):
                continue
            loader = loader_cls.create_loader(client, build_dir)
            resources: BuiltFullResourceList[T_ID] = built_modules.get_resources(  # type: ignore[valid-type]
                None,
                loader.folder_name,  # type: ignore[arg-type]
                loader.kind,
                selected,
                is_supported_file=loader.is_supported_file,
            )
            if not resources:
                continue
            if loader in {HostedExtractorSourceLoader, HostedExtractorDestinationLoader}:
                self.warn(
                    LowSeverityWarning(f"Skipping {loader.display_name} as it is not supported by the pull command.")
                )
                continue
            if loader in {GraphQLLoader, FunctionLoader, StreamlitLoader}:
                self.warn(
                    LowSeverityWarning(
                        f"Skipping {loader.display_name} as it is not supported by the pull command due to"
                        "the external file(s)."
                    )
                )
                continue
            result = self._pull_resources(loader, resources, dry_run, env_vars.dump(include_os=True))
            results[loader.display_name] = result

        table = results.counts_table(exclude_columns={"Total"})
        print(table)

    def _pull_resources(
        self,
        loader: ResourceLoader[
            T_ID, T_WriteClass, T_WritableCogniteResource, T_CogniteResourceList, T_WritableCogniteResourceList
        ],
        resources: BuiltFullResourceList[T_ID],
        dry_run: bool,
        environment_variables: dict[str, str | None],
        accept_invalid_files: bool = True,
    ) -> ResourceDeployResult:
        cdf_resources = loader.retrieve(resources.identifiers)  # type: ignore[arg-type]
        cdf_resource_by_id: dict[T_ID, T_WritableCogniteResource] = {loader.get_id(r): r for r in cdf_resources}

        resources_by_file = resources.by_file()
        file_results = ResourceDeployResult(loader.display_name)
        environment_variables = environment_variables or {}
        for source_file, resources in resources_by_file.items():
            local_resource_by_id = self._get_local_resource_dict_by_id(
                resources, loader, environment_variables, accept_invalid_files
            )
            has_changes, to_write = self._get_to_write(local_resource_by_id, cdf_resource_by_id, file_results, loader)

            if has_changes and not dry_run:
                new_content, extra_files = self._to_write_content(  # type: ignore[arg-type]
                    safe_read(source_file), to_write, resources, environment_variables, loader
                )
                with source_file.open("w", encoding=ENCODING, newline=NEWLINE) as f:
                    f.write(new_content)
                for filepath, content in extra_files.items():
                    with filepath.open("w", encoding=ENCODING, newline=NEWLINE) as f:
                        f.write(content)

        return file_results

    def _get_to_write(
        self,
        local_resource_by_id: dict[T_ID, dict[str, Any]],
        cdf_resource_by_id: dict[T_ID, T_WritableCogniteResource],
        file_results: ResourceDeployResult,
        loader: ResourceLoader[
            T_ID, T_WriteClass, T_WritableCogniteResource, T_CogniteResourceList, T_WritableCogniteResourceList
        ],
    ) -> tuple[bool, dict[T_ID, dict[str, Any]]]:
        to_write: dict[T_ID, dict[str, Any]] = {}
        has_changes = False
        for item_id, local_dict in local_resource_by_id.items():
            cdf_resource = cdf_resource_by_id.get(item_id)
            if cdf_resource is None:
                file_results.unchanged += 1
                to_write[item_id] = local_dict
                self.warn(
                    MediumSeverityWarning(
                        f"No {loader.display_name} with id {item_id} found in CDF. Have you deployed it?"
                    )
                )
                continue
            cdf_dumped = loader.dump_resource(cdf_resource, local_dict)

            if cdf_dumped == local_dict:
                file_results.unchanged += 1
                to_write[item_id] = local_dict
            else:
                file_results.changed += 1
                to_write[item_id] = cdf_dumped
                has_changes = True
        return has_changes, to_write

    @staticmethod
    def _get_local_resource_dict_by_id(
        resources: BuiltFullResourceList[T_ID],
        loader: ResourceLoader[
            T_ID, T_WriteClass, T_WritableCogniteResource, T_CogniteResourceList, T_WritableCogniteResourceList
        ],
        environment_variables: dict[str, str | None],
        allow_invalid_files: bool = False,
    ) -> dict[T_ID, dict[str, Any]]:
        unique_destinations = {r.destination for r in resources if r.destination}
        local_resource_by_id: dict[T_ID, dict[str, Any]] = {}
        local_resource_ids = set(resources.identifiers)
        for destination in unique_destinations:
            try:
                resource_list = loader.load_resource_file(destination, environment_variables)
            except ToolkitError as e:
                if allow_invalid_files:
                    # todo: naively load the file and ignore errors
                    pass
                else:
                    raise e
            for resource_dict in resource_list:
                identifier = loader.get_id(resource_dict)
                if identifier in local_resource_ids:
                    local_resource_by_id[identifier] = resource_dict
        return local_resource_by_id

    @staticmethod
    def _select_resource_ids(
        all_: bool, id_: T_ID, loader: ResourceLoader, local_resources: BuiltFullResourceList, organization_dir: Path
    ) -> BuiltFullResourceList[T_ID]:
        if all_:
            return local_resources
        if id_ is None:
            return questionary.select(
                f"Select a {loader.display_name} to pull",
                choices=[Choice(title=f"{r.identifier!r} - ({r.module_name})", value=r) for r in local_resources],
            ).ask()
        if id_ not in local_resources.identifiers:
            raise ToolkitMissingResourceError(
                f"No {loader.display_name} with external id {id_} found in the current configuration in {organization_dir}."
            )
        return BuiltFullResourceList([r for r in local_resources if r.identifier == id_])

    def _to_write_content(
        self,
        source: str,
        to_write: dict[T_ID, dict[str, Any]],
        resources: BuiltFullResourceList[T_ID],
        environment_variables: dict[str, str | None],
        loader: ResourceLoader[
            T_ID, T_WriteClass, T_WritableCogniteResource, T_CogniteResourceList, T_WritableCogniteResourceList
        ],
    ) -> tuple[str, dict[Path, str]]:
        # 1. Replace all variables with placeholders
        # 2. Load source and keep the comments
        # 3. Update the to_write dict with the placeholders
        # 4. Dump the yaml with the placeholders
        # 5. Replace the placeholders with the variables
        # 6. Add the comments back

        # All resources are assumed to be in the same file, and thus the same build variables.
        variables = resources[0].build_variables
        if environment_variables:
            variables_with_environment_list: list[BuildVariable] = []
            for variable in variables:
                if isinstance(variable.value, str) and ENV_VAR_PATTERN.match(variable.value):
                    for key, value in environment_variables.items():
                        if key in variable.value and isinstance(value, str):
                            # Running through all environment variables, in case multiple are used in the same variable.
                            # Note that variable are immutable, so we are not modifying the original variable.
                            variable = dataclasses.replace(variable, value=variable.value.replace(f"${{{key}}}", value))
                    variables_with_environment_list.append(variable)
                elif isinstance(variable.value, tuple):
                    new_value: list[str | int | float | bool] = []
                    for var_item in variable.value:
                        if isinstance(var_item, str) and ENV_VAR_PATTERN.match(var_item):
                            for key, value in environment_variables.items():
                                if key in var_item and isinstance(value, str):
                                    var_item = var_item.replace(f"${{{key}}}", value)
                        new_value.append(var_item)
                    variables_with_environment_list.append(dataclasses.replace(variable, value=tuple(new_value)))  # type: ignore[arg-type]
                else:
                    variables_with_environment_list.append(variable)
            variables = BuildVariables(variables_with_environment_list)

        content, value_by_placeholder = variables.replace(source, use_placeholder=True)
        comments = YAMLComments.load(source)
        # If there is a variable in the identifier, we need to replace it with the value
        # such that we can look it up in the to_write dict.
        if isinstance(loader, ExtractionPipelineConfigLoader):
            # The safe read in ExtractionPipelineConfigLoader stringifies the config dict,
            # but we need to load it as a dict so we can write it back to the file maintaining
            # the order or the keys.
            loaded = read_yaml_content(variables.replace(source))
            loaded_with_placeholder = read_yaml_content(content)
        else:
            loaded = read_yaml_content(loader.safe_read(variables.replace(source)))
            loaded_with_placeholder = read_yaml_content(loader.safe_read(content))

        built_by_identifier = {r.identifier: r for r in resources}
        updated: dict[str, Any] | list[dict[str, Any]]
        extra_files: dict[Path, str] = {}
        replacer = ResourceReplacer(value_by_placeholder, loader)
        if isinstance(loaded, dict) and isinstance(loaded_with_placeholder, dict):
            item_id = loader.get_id(loaded)
            updated = self._update(
                item_id,
                loaded,
                loaded_with_placeholder,
                to_write,
                built_by_identifier,
                replacer,
                extra_files,
            )
        elif isinstance(loaded, list) and isinstance(loaded_with_placeholder, list):
            updated = []
            for i, item in enumerate(loaded):
                item_id = loader.get_id(item)
                updated.append(
                    self._update(
                        item_id,
                        item,
                        loaded_with_placeholder[i],
                        to_write,
                        built_by_identifier,
                        replacer,
                        extra_files,
                    )
                )
        else:
            raise ValueError("Loaded and loaded_with_ids should be of the same type")

        dumped = yaml_safe_dump(updated)
        for placeholder, variable in value_by_placeholder.items():
            dumped = dumped.replace(placeholder, f"{{{{ {variable.key} }}}}")
        file_content = comments.dump(dumped)
        return file_content, extra_files

    @classmethod
    def _update(
        cls,
        item_id: T_ID,
        loaded: dict[str, Any],
        loaded_with_placeholder: dict[str, Any],
        to_write: dict[T_ID, dict[str, Any]],
        built_by_identifier: dict[T_ID, BuiltResourceFull[T_ID]],
        replacer: ResourceReplacer,
        extra_files: dict[Path, str],
    ) -> dict[str, Any]:
        if item_id not in to_write:
            raise ToolkitMissingResourceError(f"Resource {item_id} not found in to_write.")
        item_write = to_write[item_id]
        if item_id not in built_by_identifier:
            raise ToolkitMissingResourceError(f"Resource {item_id} not found in resources.")
        built = built_by_identifier[item_id]
        if built.extra_sources:
            builder = create_builder(built.resource_dir, None)
            for extra in built.extra_sources:
                extra_content, extra_placeholders = built.build_variables.replace(
                    safe_read(extra.path), extra.path.suffix, use_placeholder=True
                )
                key, _ = builder.load_extra_field(extra_content)
                if key in item_write:
                    new_extra = item_write.pop(key)
                    for placeholder, variable in extra_placeholders.items():
                        if placeholder in extra_content:
                            new_extra = new_extra.replace(variable.value, f"{{{{ {variable.key} }}}}")
                    extra_files[extra.path] = new_extra
        return replacer.replace(loaded, loaded_with_placeholder, item_write)


class ResourceReplacer:
    """Replaces values in a local resource directory with the updated values from CDF.

    The local resource dict order is maintained. In addition, placeholders are used for variables.
    """

    def __init__(self, value_by_placeholder: dict[str, BuildVariable], loader: ResourceLoader) -> None:
        self._value_by_placeholder = value_by_placeholder
        self._loader = loader

    def replace(
        self,
        current: dict[str, Any],
        placeholder: dict[str, Any],
        to_write: dict[str, Any],
    ) -> dict[str, Any]:
        return self._replace_dict(current, placeholder, to_write, tuple())

    def _replace_dict(
        self,
        current: dict[str, Any],
        placeholder: dict[str, Any],
        to_write: dict[str, Any],
        json_path: tuple[str | int, ...],
    ) -> dict[str, Any]:
        # Modified first to maintain original order
        # Then added, and skip removed
        updated: dict[str, Any] = {}
        variable_keys: set[str] = set()
        for modified_key, current_value in current.items():
            if modified_key not in to_write:
                # Removed item by skipping
                continue
            cdf_value = to_write[modified_key]

            if modified_key in placeholder:
                placeholder_value = placeholder[modified_key]
            elif variable_key := next(
                (
                    key
                    for key, variable in self._value_by_placeholder.items()
                    if key in placeholder and variable.value == modified_key
                ),
                None,
            ):
                # The key is a variable
                variable_keys.add(modified_key)
                modified_key = variable_key
                placeholder_value = placeholder[variable_key]
            else:
                # Bug in the code if this is reached, using a fallback.
                placeholder_value = current_value

            if isinstance(current_value, dict) and isinstance(cdf_value, dict):
                updated[modified_key] = self._replace_dict(
                    current_value, placeholder_value, cdf_value, (*json_path, modified_key)
                )
            elif isinstance(current_value, list) and isinstance(cdf_value, list):
                if isinstance(placeholder_value, str) and current_value == cdf_value:
                    # A list variable is used, and the list is unchanged.
                    updated[modified_key] = placeholder_value
                elif isinstance(placeholder_value, list):
                    updated[modified_key] = self._replace_list(
                        current_value, placeholder_value, cdf_value, (*json_path, modified_key)
                    )
                else:
                    # A list variable is used, but the list is changed. Since the value is represented as a single
                    # string, we cannot update it.
                    if variable := self._value_by_placeholder.get(placeholder_value):
                        raise ToolkitValueError(
                            f"Pull is not supported for list variable: {variable.key}: {variable.value_variable}"
                        )
                    raise ToolkitValueError("Pull is not supported for list variable.")
            else:
                updated[modified_key] = self._replace_value(
                    current_value, placeholder_value, cdf_value, (*json_path, modified_key)
                )

        for new_key in to_write:
            if (new_key not in current) and new_key not in variable_keys:
                # Note there cannot be variables in new items
                updated[new_key] = to_write[new_key]
        return updated

    def _replace_list(
        self,
        current: list[Any],
        placeholder: list[Any],
        to_write: list[Any],
        json_path: tuple[str | int, ...],
    ) -> list[Any]:
        compare_indices, added_indices = self._loader.diff_list(current, to_write, json_path)
        updated: list[Any] = []
        for no, current_item in enumerate(current):
            if no not in compare_indices:
                # Removed item
                continue
            current_value = current_item
            placeholder_value = placeholder[no]
            cdf_value = to_write[compare_indices[no]]
            updated.append(self._replace_value(current_value, placeholder_value, cdf_value, (*json_path, no)))
        for added_index in added_indices:
            # Note there cannot be variables in new items
            updated.append(to_write[added_index])
        return updated

    def _replace_value(
        self,
        current: Any,
        placeholder_value: Any,
        to_write: Any,
        json_path: tuple[str | int, ...],
    ) -> Any:
        if isinstance(current, dict) and isinstance(to_write, dict):
            return self._replace_dict(current, placeholder_value, to_write, json_path)
        elif isinstance(current, list) and isinstance(to_write, list):
            return self._replace_list(current, placeholder_value, to_write, json_path)
        elif type(current) is type(to_write):
            if to_write == current:
                return placeholder_value
            if not isinstance(to_write, str):
                # Variable substitution is only supported for strings
                return to_write
            for placeholder, variable in self._value_by_placeholder.items():
                if placeholder in placeholder_value:
                    # We use the placeholder and not the {{ variable }} in the value to ensure
                    # that the result is valid yaml.
                    to_write = to_write.replace(variable.value, placeholder)  # type: ignore[arg-type]
                    # Iterate through all variables in case multiple are used in the same value.
            return to_write
        elif isinstance(current, dict) and isinstance(to_write, str):
            # This is a special case for the ExtractionPipelineConfigLoader where the config dict is typically a
            # dict locally, but returned as a string from the server.
            try:
                to_write = read_yaml_content(to_write)
            except yaml.YAMLError:
                ...
            else:
                return self._replace_dict(current, placeholder_value, to_write, json_path)

        raise ToolkitValueError(
            f"CDF value and local value should be of the same type in {'.'.join(map(str, json_path))}, "
            f"got {type(current)} != {type(to_write)}"
        )
