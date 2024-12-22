import re
import shutil
import tempfile
import typing
from abc import abstractmethod
from collections import UserDict, defaultdict
from collections.abc import ItemsView, KeysView, ValuesView
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, TypeVar, overload

import yaml
from rich import print

from cognite_toolkit._cdf_tk.constants import ENV_VAR_PATTERN
from cognite_toolkit._cdf_tk.exceptions import (
    ToolkitYAMLFormatError,
)
from cognite_toolkit._cdf_tk.tk_warnings import MediumSeverityWarning


@overload
def load_yaml_inject_variables(
    filepath: Path | str, variables: dict[str, str | None], required_return_type: Literal["list"], validate: bool = True
) -> list[dict[str, Any]]: ...


@overload
def load_yaml_inject_variables(
    filepath: Path | str, variables: dict[str, str | None], required_return_type: Literal["dict"], validate: bool = True
) -> dict[str, Any]: ...


@overload
def load_yaml_inject_variables(
    filepath: Path | str,
    variables: dict[str, str | None],
    required_return_type: Literal["any"] = "any",
    validate: bool = True,
) -> dict[str, Any] | list[dict[str, Any]]: ...


def load_yaml_inject_variables(
    filepath: Path | str,
    variables: dict[str, str | None],
    required_return_type: Literal["any", "list", "dict"] = "any",
    validate: bool = True,
) -> dict[str, Any] | list[dict[str, Any]]:
    if isinstance(filepath, str):
        content = filepath
    else:
        content = filepath.read_text()
    for key, value in variables.items():
        if value is None:
            continue
        content = content.replace(f"${{{key}}}", value)
    if validate:
        for match in ENV_VAR_PATTERN.finditer(content):
            environment_variable = match.group(1)
            suffix = f" It is expected in {filepath.name}." if isinstance(filepath, Path) else ""
            MediumSeverityWarning(
                f"Variable {environment_variable} is not set in the environment.{suffix}"
            ).print_warning()

    if yaml.__with_libyaml__:
        # CSafeLoader is faster than yaml.safe_load
        result = yaml.CSafeLoader(content).get_data()
    else:
        result = yaml.safe_load(content)
    if required_return_type == "any":
        return result
    elif required_return_type == "list":
        if isinstance(result, list):
            return result
        raise ValueError(f"Expected a list, but got {type(result)}")
    elif required_return_type == "dict":
        if isinstance(result, dict):
            return result
        raise ValueError(f"Expected a dict, but got {type(result)}")
    else:
        raise ValueError(f"Unknown required_return_type {required_return_type}")


@overload
def read_yaml_file(filepath: Path, expected_output: Literal["dict"] = "dict") -> dict[str, Any]: ...


@overload
def read_yaml_file(filepath: Path, expected_output: Literal["list"]) -> list[dict[str, Any]]: ...


def read_yaml_file(
    filepath: Path, expected_output: Literal["list", "dict"] = "dict"
) -> dict[str, Any] | list[dict[str, Any]]:
    """Read a YAML file and return a dictionary

    filepath: path to the YAML file
    """
    try:
        config_data = read_yaml_content(filepath.read_text())
    except yaml.YAMLError as e:
        print(f"  [bold red]ERROR:[/] reading {filepath}: {e}")
        return {}

    if expected_output == "list" and isinstance(config_data, dict):
        ToolkitYAMLFormatError(f"{filepath} did not contain `list` as expected")
    elif expected_output == "dict" and isinstance(config_data, list):
        ToolkitYAMLFormatError(f"{filepath} did not contain `dict` as expected")
    return config_data


def read_yaml_content(content: str) -> dict[str, Any] | list[dict[str, Any]]:
    """Read a YAML string and return a dictionary

    content: string containing the YAML content
    """
    if yaml.__with_libyaml__:
        # CSafeLoader is faster than yaml.safe_load
        config_data = yaml.CSafeLoader(content).get_data()
    else:
        config_data = yaml.safe_load(content)
    return config_data


# Spaces are allowed, but we replace them as well
_ILLEGAL_CHARACTERS = re.compile(r"[<>:\"/\\|?*\s]")


def to_directory_compatible(text: str) -> str:
    """Convert a string to be compatible with directory names on all platforms"""
    cleaned = _ILLEGAL_CHARACTERS.sub("_", text)
    # Replace multiple underscores with a single one
    return re.sub(r"_+", "_", cleaned)


@contextmanager
def tmp_build_directory() -> typing.Generator[Path, None, None]:
    build_dir = Path(tempfile.mkdtemp(prefix="build.", suffix=".tmp", dir=Path.cwd()))
    try:
        yield build_dir
    finally:
        shutil.rmtree(build_dir)


def safe_read(file: Path | str) -> str:
    """Falls back on explicit using utf-8 if the default .read_text()"""
    if isinstance(file, str):
        return file
    try:
        return file.read_text()
    except UnicodeDecodeError:
        # On Windows, we may have issues as the encoding is not always utf-8
        try:
            return file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raise


def safe_write(file: Path, content: str) -> None:
    """Falls back on explicit using utf-8 if the default .write_text()"""
    try:
        file.write_text(content)
    except UnicodeEncodeError:
        # On Windows, we may have issues as the encoding is not always utf-8
        file.write_text(content, encoding="utf-8")


def quote_int_value_by_key_in_yaml(content: str, key: str) -> str:
    """Quote a value in a yaml string"""
    # This pattern will match the key if it is not already quoted
    pattern = rf"^(\s*-?\s*)?{key}:\s*(?!.*['\":])([\d_]+)$"
    replacement = rf'\1{key}: "\2"'

    return re.sub(pattern, replacement, content, flags=re.MULTILINE)


def stringify_value_by_key_in_yaml(content: str, key: str) -> str:
    """Quote a value in a yaml string"""
    pattern = rf"^{key}:\s*$"
    replacement = rf"{key}: |"
    return re.sub(pattern, replacement, content, flags=re.MULTILINE)


@dataclass(frozen=True)
class YAMLComment:
    """This represents a comment in a YAML file. It can be either above or after a variable."""

    above: list[str] = field(default_factory=list)
    after: list[str] = field(default_factory=list)

    @property
    def comment(self) -> str:
        return "\n".join(self.above) + "\n" + "\n".join(self.after)


T_Key = TypeVar("T_Key")
T_Value = TypeVar("T_Value")


class YAMLWithComments(UserDict[T_Key, T_Value]):
    @staticmethod
    def _extract_comments(raw_file: str, key_prefix: tuple[str, ...] = tuple()) -> dict[tuple[str, ...], YAMLComment]:
        """Extract comments from a raw file and return a dictionary with the comments."""
        comments: dict[tuple[str, ...], YAMLComment] = defaultdict(YAMLComment)
        position: Literal["above", "after"]
        init_value: object = object()
        variable: str | None | object = init_value
        last_comments: list[str] = []
        last_variable: str | None = None
        last_leading_spaces = 0
        parent_variables: list[str] = []
        indent: int | None = None
        for line in raw_file.splitlines():
            if ":" in line:
                # Is variable definition
                leading_spaces = len(line) - len(line.lstrip())
                variable = str(line.split(":", maxsplit=1)[0].strip())
                if leading_spaces > last_leading_spaces and last_variable:
                    parent_variables.append(last_variable)
                    if indent is None:
                        # Automatically indent based on the first variable
                        indent = leading_spaces
                elif leading_spaces < last_leading_spaces and parent_variables:
                    parent_variables = parent_variables[: -((last_leading_spaces - leading_spaces) // (indent or 2))]

                if last_comments:
                    comments[(*key_prefix, *parent_variables, variable)].above.extend(last_comments)
                    last_comments.clear()

                last_variable = variable
                last_leading_spaces = leading_spaces

            if "#" in line:
                # Potentially has comment.
                before, comment = str(line).rsplit("#", maxsplit=1)
                position = "after" if ":" in before else "above"
                if position == "after" and (before.count('"') % 2 == 1 or before.count("'") % 2 == 1):
                    # The comment is inside a string
                    continue
                # This is a new comment.
                if (position == "after" or variable is None) and variable is not init_value:
                    key = (*key_prefix, *parent_variables, *((variable and [variable]) or []))  # type: ignore[misc]
                    if position == "after":
                        comments[key].after.append(comment.strip())
                    else:
                        comments[key].above.append(comment.strip())
                else:
                    last_comments.append(comment.strip())

        return dict(comments)

    def _dump_yaml_with_comments(self, indent_size: int = 2, newline_after_indent_reduction: bool = False) -> str:
        """Dump a config dictionary to a yaml string"""
        config = self.dump()
        dumped = yaml.dump(config, sort_keys=False, indent=indent_size)
        out_lines = []
        if comments := self._get_comment(tuple()):
            for comment in comments.above:
                out_lines.append(f"# {comment}")
        last_indent = 0
        last_variable: str | None = None
        path: tuple[str, ...] = tuple()
        for line in dumped.splitlines():
            indent = len(line) - len(line.lstrip())
            if last_indent < indent:
                if last_variable is None:
                    raise ValueError("Unexpected state of last_variable being None")
                path = (*path, last_variable)
            elif last_indent > indent:
                if newline_after_indent_reduction:
                    # Adding some extra space between modules
                    out_lines.append("")
                indent_reduction_steps = (last_indent - indent) // indent_size
                path = path[:-indent_reduction_steps]

            variable = line.split(":", maxsplit=1)[0].strip()
            if comments := self._get_comment((*path, variable)):
                for line_comment in comments.above:
                    out_lines.append(f"{' ' * indent}# {line_comment}")
                if after := comments.after:
                    line = f"{line} # {after[0]}"

            out_lines.append(line)
            last_indent = indent
            last_variable = variable
        out_lines.append("")
        return "\n".join(out_lines)

    @abstractmethod
    def dump(self) -> dict[str, Any]: ...

    @abstractmethod
    def _get_comment(self, key: tuple[str, ...]) -> YAMLComment | None: ...

    # This is to get better type hints in the IDE
    def items(self) -> ItemsView[T_Key, T_Value]:
        return super().items()

    def keys(self) -> KeysView[T_Key]:
        return super().keys()

    def values(self) -> ValuesView[T_Value]:
        return super().values()


def remove_trailing_newline(content: str) -> str:
    """Remove the trailing newline character from a string"""
    while content.endswith("\n"):
        content = content[:-1]
    return content
