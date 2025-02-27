from __future__ import annotations

import sys
from collections.abc import Iterable, Mapping
from graphlib import CycleError
from pathlib import Path

from yaml import YAMLError

if sys.version_info >= (3, 11):
    from tomllib import TOMLDecodeError
else:
    from tomli import TOMLDecodeError


class ToolkitError(Exception):
    def __repr__(self) -> str:
        # Repr is what is called by rich when the exception is printed.
        return str(self)


class ToolkitNotSupported(ToolkitError): ...


class ToolkitInvalidSettingsError(ToolkitError):
    pass


class ToolkitMigrationError(ToolkitError):
    pass


class ToolkitVersionError(ToolkitError):
    pass


class ToolkitModuleVersionError(ToolkitError):
    pass


class ToolkitEnvError(ToolkitError):
    pass


class ToolkitMissingResourceError(ToolkitError):
    pass


class ToolkitInvalidFunctionError(ToolkitError): ...


class ToolkitCleanResourceError(ToolkitError):
    pass


class ToolkitDeployResourceError(ToolkitError):
    pass


class ToolkitMissingModuleError(ToolkitError):
    pass


class ToolkitMissingModulesError(ToolkitError):
    pass


class ToolkitDuplicatedResourceError(ToolkitError):
    pass


class ToolkitDuplicatedModuleError(ToolkitError):
    def __init__(self, message: str, duplicated: dict[str, list[Path]]) -> None:
        super().__init__(message)
        self.duplicated = duplicated

    def __str__(self) -> str:
        lines = [super().__str__()]
        for module_name, paths in self.duplicated.items():
            locations = "\n        ".join(sorted(path.as_posix() for path in paths))
            lines.append(f"    {module_name} exists in:\n        {locations}")
        lines.append(
            "    You can use the path syntax to disambiguate between modules with the same name. For example "
            "'cognite_modules/core/cdf_apm_base' instead of 'cdf_apm_base'."
        )
        return "\n".join(lines)

    def __repr__(self) -> str:
        # Repr is what is called by rich when the exception is printed.
        return str(self)


class ToolkitNotADirectoryError(NotADirectoryError, ToolkitError):
    pass


class ToolkitIsADirectoryError(IsADirectoryError, ToolkitError):
    pass


class ToolkitFileNotFoundError(FileNotFoundError, ToolkitError):
    pass


class ToolkitFileExistsError(FileExistsError, ToolkitError):
    pass


class ToolkitValidationError(ToolkitError):
    pass


class ToolkitIdentifierMissingError(ToolkitValidationError):
    def __init__(self, missing: str | Iterable[str], file: Path) -> None:
        super().__init__(f"Missing or incomplete resource identifier in file {file.as_posix()!r}:")
        self.missing: str | Iterable[str] = missing
        self.file = file

    def __str__(self) -> str:
        lines = [super().__str__()]
        if isinstance(self.missing, str):
            self.missing = [self.missing]

        for missing in self.missing:
            lines.append(f"    {missing!r}")
        return "\n".join(lines)

    def __repr__(self) -> str:
        # Repr is what is called by rich when the exception is printed.
        return str(self)


class ToolkitCycleError(CycleError, ToolkitValidationError):
    def __str__(self) -> str:
        return self.args[0]


class ToolkitYAMLFormatError(YAMLError, ToolkitValidationError):
    pass


class ToolkitTOMLFormatError(TOMLDecodeError, ToolkitValidationError): ...


class ToolkitInvalidParameterNameError(ToolkitValidationError):
    def __init__(self, message: str, identifier: str, correct_by_wrong_parameter: Mapping[str, str | None]) -> None:
        super().__init__(message)
        self.identifier = identifier
        self.parameter = correct_by_wrong_parameter

    def __str__(self) -> str:
        parameters = []
        for wrong, correct in self.parameter.items():
            if correct is not None:
                parameters.append(f"{wrong!r} should be {correct!r}")
            else:
                parameters.append(f"{wrong!r} is invalid")
        parameter_str = "    \n".join(parameters)
        message = super().__str__()
        return f"{message}\nIn {self.identifier!r} the following parameters are invalid: {parameter_str}"

    def __repr__(self) -> str:
        # Repr is what is called by rich when the exception is printed.
        return str(self)


class ToolkitValueError(ValueError, ToolkitError):
    pass


class ToolkitMissingValueError(ToolkitValueError):
    pass


class ToolkitKeyError(KeyError, ToolkitError): ...


class ToolkitTypeError(TypeError, ToolkitError): ...


class ToolkitRequiredValueError(ToolkitError, ValueError):
    pass


class ToolkitResourceMissingError(ToolkitError):
    def __init__(self, message: str, resource: str) -> None:
        super().__init__(message)
        self.resource = resource

    def __str__(self) -> str:
        return f"{super().__str__()}\nResource {self.resource!r} is missing"


class ToolkitWrongResourceError(RuntimeError):
    """Special exception used by a loader to signal that the resource is not the expected type."""

    ...


class UploadFileError(ToolkitError):
    pass


class ResourceRetrievalError(ToolkitError): ...


class ResourceCreationError(ToolkitError):
    pass


class ResourceDeleteError(ToolkitError): ...


class ResourceUpdateError(ToolkitError):
    pass


class AmbiguousResourceFileError(ToolkitError):
    pass


class AuthenticationError(ToolkitError):
    pass


class AuthorizationError(ToolkitError):
    pass


class GraphQLParseError(ToolkitError): ...


class CDFAPIError(ToolkitError, RuntimeError):
    """Error raised when the CDF API returns an error."""

    ...
