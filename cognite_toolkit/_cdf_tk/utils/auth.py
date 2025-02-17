import os
from collections.abc import Iterable, Mapping
from dataclasses import Field, dataclass, field, fields
from typing import Any, Literal, TypeAlias, get_args

import questionary
import typer
from cognite.client.credentials import (
    CredentialProvider,
    OAuthClientCredentials,
    OAuthDeviceCode,
    OAuthInteractive,
    Token,
)
from questionary import Choice
from rich import print

from cognite_toolkit._cdf_tk.client import ToolkitClient, ToolkitClientConfig
from cognite_toolkit._cdf_tk.constants import TOOLKIT_CLIENT_ENTRA_ID
from cognite_toolkit._cdf_tk.exceptions import AuthenticationError, ToolkitKeyError, ToolkitMissingValueError
from cognite_toolkit._cdf_tk.utils import humanize_collection
from cognite_toolkit._version import __version__

Provider: TypeAlias = Literal["entra_id", "auth0", "other"]
LoginFlow: TypeAlias = Literal["client_credentials", "token", "device_code", "interactive"]
VALID_PROVIDERS = get_args(Provider)
VALID_LOGIN_FLOWS = get_args(LoginFlow)

CLIENT_NAME = f"CDF-Toolkit:{__version__}"
PROVIDER_DESCRIPTION = {
    "entra_id": "Use Microsoft Entra ID to authenticate",
    "auth0": "Use Auth0 to authenticate",
    # "cdf": "Use Cognite IDP to authenticate",
    "other": "Use other IDP to authenticate",
}
LOGIN_FLOW_DESCRIPTION = {
    "client_credentials": "Setup a service principal with client credentials",
    "interactive": "Login using the browser with your user credentials",
    "device_code": "Login using the browser with your user credentials using device code flow",
    "token": "Use a Token directly to authenticate",
}


@dataclass
class EnvOptions(Mapping):
    display_name: str
    default_example: str = ""
    example: dict[Provider, str] = field(default_factory=dict)
    is_secret: bool = False
    required: frozenset[tuple[Provider | None, LoginFlow]] = frozenset()
    optional: frozenset[tuple[Provider | None, LoginFlow]] = frozenset()

    def __getitem__(self, key: str) -> str | bool:
        return self.__dict__[key]

    def __iter__(self) -> Iterable[str]:  # type: ignore[override]
        return iter(self.__dict__.keys())

    def __len__(self) -> int:
        return len(self.__dict__)


ALL_CASES = [(None, flow) for flow in VALID_LOGIN_FLOWS]


def all_providers(
    flow: LoginFlow, exclude: Provider | Iterable[Provider] | None = None
) -> frozenset[tuple[Provider | None, LoginFlow]]:
    if isinstance(exclude, str):
        exclude = {exclude}
    elif exclude is not None:
        exclude = set(exclude)
    return frozenset((prov, flow) for prov in VALID_PROVIDERS if exclude is None or prov not in exclude)


@dataclass
class EnvironmentVariables:
    CDF_CLUSTER: str = field(metadata=EnvOptions("CDF cluster", "westeurope-1"))
    CDF_PROJECT: str = field(metadata=EnvOptions("CDF project", "publicdata"))
    PROVIDER: Provider = field(default="entra_id", metadata=EnvOptions("Provider", "entra_id"))
    LOGIN_FLOW: LoginFlow = field(default="client_credentials", metadata=EnvOptions("Login flow", "client_credentials"))
    CDF_URL: str | None = field(
        default=None,
        metadata=EnvOptions(
            "CDF URL", default_example="https://{CDF_CLUSTER}.cognitedata.com", optional=frozenset(ALL_CASES)
        ),
    )
    CDF_TOKEN: str | None = field(
        default=None, metadata=EnvOptions("OAuth2 token", required=frozenset([(None, "token")]))
    )
    IDP_CLIENT_ID: str | None = field(
        default=None,
        metadata=EnvOptions(
            display_name="client id",
            required=frozenset(
                [(None, "client_credentials"), (None, "interactive"), *all_providers("device_code", exclude="entra_id")]
            ),
        ),
    )
    IDP_CLIENT_SECRET: str | None = field(
        default=None,
        metadata=EnvOptions(
            display_name="client secret", is_secret=True, required=frozenset({(None, "client_credentials")})
        ),
    )
    IDP_TOKEN_URL: str | None = field(
        default=None,
        metadata=EnvOptions(
            display_name="token URL",
            example={
                "entra_id": "https://login.microsoftonline.com/{IDP_TENANT_ID}/oauth2/v2.0/token",
                "auth0": "https://<my_auth_url>/oauth/token",
            },
            required=all_providers(flow="client_credentials", exclude="entra_id"),
            optional=frozenset([("entra_id", "client_credentials")]),
        ),
    )
    IDP_TENANT_ID: str | None = field(
        default=None,
        metadata=EnvOptions(
            display_name="Tenant id for MS Entra",
            example={"entra_id": "00000000-0000-0000-0000-000000000000 or mytenant.onmicrosoft.com"},
            required=frozenset(
                [("entra_id", "device_code"), ("entra_id", "client_credentials"), ("entra_id", "interactive")]
            ),
        ),
    )
    IDP_AUDIENCE: str | None = field(
        default=None,
        metadata=EnvOptions(
            display_name="IDP audience",
            example={
                "entra_id": "https://{CDF_CLUSTER}.cognitedata.com",
                "auth0": "https: //{CDF_PROJECT}.fusion.cognite.com/{CDF_PROJECT}",
                "other": "https://{CDF_CLUSTER}.cognitedata.com",
            },
            required=all_providers(flow="client_credentials", exclude={"entra_id", "auth0"}),
            optional=frozenset([("entra_id", "client_credentials"), ("auth0", "client_credentials")]),
        ),
    )

    IDP_SCOPES: str | None = field(
        default=None,
        metadata=EnvOptions(
            display_name="IDP scopes",
            example={
                "entra_id": "https://{CDF_CLUSTER}.cognitedata.com/.default",
                "auth0": "IDENTITY,user_impersonation",
            },
            optional=frozenset([*all_providers("client_credentials"), (None, "interactive")]),
        ),
    )
    IDP_AUTHORITY_URL: str | None = field(
        default=None,
        metadata=EnvOptions(
            display_name="IDP authority URL",
            example={"entra_id": "https://login.microsoftonline.com/{IDP_TENANT_ID}"},
            required=all_providers("interactive", exclude="entra_id"),
            optional=frozenset([("entra_id", "interactive"), ("auth0", "device_code")]),
        ),
    )
    IDP_DISCOVERY_URL: str | None = field(
        default=None,
        metadata=EnvOptions(
            display_name="IDP OIDC discovery URL (root URL excl. /.well-known/...)",
            default_example="https://<auth0-tenant>.auth0.com/oauth",
            required=all_providers("device_code", exclude="entra_id"),
        ),
    )
    CDF_CLIENT_TIMEOUT: int = field(
        default=30,
        metadata=EnvOptions(display_name="CDF client timeout", default_example="30", optional=frozenset(ALL_CASES)),
    )
    CDF_CLIENT_MAX_WORKERS: int = field(
        default=5,
        metadata=EnvOptions(display_name="CDF client max workers", default_example="5", optional=frozenset(ALL_CASES)),
    )
    _client: ToolkitClient | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        self.LOGIN_FLOW = self.LOGIN_FLOW.lower()  # type: ignore[assignment]
        if self.LOGIN_FLOW not in VALID_LOGIN_FLOWS:
            raise AuthenticationError(f"Invalid login flow: {self.LOGIN_FLOW}. Valid options are {VALID_LOGIN_FLOWS}")
        if self.PROVIDER not in VALID_PROVIDERS:
            raise AuthenticationError(f"Invalid provider: {self.PROVIDER}. Valid options are {VALID_PROVIDERS}")

    # All derived properties
    @property
    def idp_tenant_id(self) -> str:
        if self.IDP_TENANT_ID:
            return self.IDP_TENANT_ID
        if self.PROVIDER == "entra_id" and self.IDP_TOKEN_URL:
            return self.IDP_TOKEN_URL.removeprefix("https://login.microsoftonline.com/").removesuffix(
                "/oauth2/v2.0/token"
            )
        raise ToolkitMissingValueError("IDP_TENANT_ID is missing", "IDP_TENANT_ID")

    @property
    def idp_token_url(self) -> str:
        if self.PROVIDER == "cdf":
            return "https://auth.cognite.com/oauth2/token"
        if self.IDP_TOKEN_URL:
            return self.IDP_TOKEN_URL
        if self.PROVIDER == "entra_id" and self.IDP_TENANT_ID:
            return f"https://login.microsoftonline.com/{self.IDP_TENANT_ID}/oauth2/v2.0/token"
        alternative = ""
        if self.PROVIDER == "entra_id":
            alternative = " or provide IDP_TENANT_ID"
        raise ToolkitMissingValueError(
            f"IDP_TOKEN_URL is missing. Please provide it{alternative} in the environment variables.",
            "IDP_TOKEN_URL",
        )

    @property
    def cdf_url(self) -> str:
        return self.CDF_URL or f"https://{self.CDF_CLUSTER}.cognitedata.com"

    @property
    def idp_audience(self) -> str:
        if self.IDP_AUDIENCE:
            return self.IDP_AUDIENCE
        if self.PROVIDER == "auth0":
            return f"https://{self.CDF_PROJECT}.fusion.cognite.com/{self.CDF_PROJECT}"
        else:
            return f"https://{self.CDF_CLUSTER}.cognitedata.com"

    @property
    def idp_scopes(self) -> list[str]:
        if self.IDP_SCOPES:
            return self.IDP_SCOPES.split(",")
        if self.PROVIDER == "auth0":
            return ["IDENTITY", "user_impersonation"]
        return [f"https://{self.CDF_CLUSTER}.cognitedata.com/.default"]

    @property
    def idp_authority_url(self) -> str:
        if self.IDP_AUTHORITY_URL:
            return self.IDP_AUTHORITY_URL
        if self.PROVIDER == "entra_id" and self.idp_tenant_id:
            return f"https://login.microsoftonline.com/{self.idp_tenant_id}"
        alternative = ""
        if self.PROVIDER == "entra_id":
            alternative = " or provide IDP_TENANT_ID"
        raise ToolkitMissingValueError(
            f"IDP_AUTHORITY_URL is missing. Please provide it{alternative} in the environment variables.",
            "IDP_AUTHORITY_URL",
        )

    @classmethod
    def _fields(cls, inst: "EnvironmentVariables | None" = None) -> tuple[Field, ...]:
        return tuple(f for f in fields(inst or cls) if not f.name.startswith("_"))

    @classmethod
    def create_from_environment(cls) -> "EnvironmentVariables":
        if missing := [key for key in ["CDF_CLUSTER", "CDF_PROJECT"] if key not in os.environ]:
            raise ToolkitMissingValueError(f"Missing environment variables: {humanize_collection(missing)}")
        args: dict[str, Any] = {
            field_.name: field_.type(os.environ[field_.name]) if field_.type is int else os.environ[field_.name]  # type: ignore[operator]
            for field_ in cls._fields()
            if field_.name in os.environ
        }
        return cls(**args)

    def get_credentials(self) -> CredentialProvider:
        method_by_flow = {
            "client_credentials": self._get_oauth_client_credentials,
            "interactive": self._get_oauth_interactive,
            "device_code": self._get_oauth_device_code,
            "token": self._get_token,
        }
        if self.LOGIN_FLOW not in method_by_flow:
            # Should already be checked in __post_init__
            raise AuthenticationError(f"Login flow {self.LOGIN_FLOW} is not supported.")

        if missing_vars := self.get_missing_vars():
            raise ToolkitMissingValueError(
                f"The login flow '{self.LOGIN_FLOW}' requires the following environment variables: {humanize_collection(missing_vars)}.",
            )
        return method_by_flow[self.LOGIN_FLOW]()

    def _get_oauth_client_credentials(self) -> OAuthClientCredentials:
        if self.PROVIDER == "cdf":
            return OAuthClientCredentials(
                client_id=self.IDP_CLIENT_ID,  # type: ignore[arg-type]
                client_secret=self.IDP_CLIENT_SECRET,  # type: ignore[arg-type]
                token_url=self.idp_token_url,
                scopes=None,  # type: ignore[arg-type]
            )
        return OAuthClientCredentials(
            client_id=self.IDP_CLIENT_ID,  # type: ignore[arg-type]
            client_secret=self.IDP_CLIENT_SECRET,  # type: ignore[arg-type]
            token_url=self.idp_token_url,
            audience=self.idp_audience,
            scopes=self.idp_scopes,
        )

    def _get_oauth_interactive(self) -> OAuthInteractive:
        return OAuthInteractive(
            client_id=self.IDP_CLIENT_ID,  # type: ignore[arg-type]
            authority_url=self.idp_authority_url,
            scopes=self.idp_scopes,
        )

    def _get_oauth_device_code(self) -> OAuthDeviceCode:
        if self.PROVIDER == "entra_id":
            # TODO: If the user has submitted the wrong scopes, we may get a valid token that gives 401 on the CDF API.
            # The user will then have to wait until the token has expired to retry with the correct scopes.
            # If we add clear_cache=True to the OAuthDeviceCode, the token cache will be cleared.
            # We could add a cli option to auth verify, e.g. --clear-token-cache, that will clear the cache.
            return OAuthDeviceCode.default_for_azure_ad(
                tenant_id=self.IDP_TENANT_ID,  # type: ignore[arg-type]
                client_id=TOOLKIT_CLIENT_ENTRA_ID,
                cdf_cluster=self.CDF_CLUSTER,
                clear_cache=False,
            )
        return OAuthDeviceCode(
            authority_url=self.IDP_AUTHORITY_URL,
            cdf_cluster=self.CDF_CLUSTER,
            oauth_discovery_url=self.IDP_DISCOVERY_URL,
            client_id=self.IDP_CLIENT_ID,  # type: ignore[arg-type]
            audience=self.idp_audience,
        )

    def _get_token(self) -> Token:
        if not self.CDF_TOKEN:
            raise ToolkitKeyError("CDF_TOKEN must be set in the environment", "CDF_TOKEN")
        return Token(self.CDF_TOKEN)

    def get_config(self, is_strict_validation: bool) -> ToolkitClientConfig:
        return ToolkitClientConfig(
            client_name=CLIENT_NAME,
            project=self.CDF_PROJECT,
            credentials=self.get_credentials(),
            base_url=self.cdf_url,
            is_strict_validation=is_strict_validation,
            timeout=self.CDF_CLIENT_TIMEOUT,
            max_workers=self.CDF_CLIENT_MAX_WORKERS,
        )

    def get_client(self, is_strict_validation: bool = True) -> ToolkitClient:
        if self._client is None:
            self._client = ToolkitClient(config=self.get_config(is_strict_validation))
        return self._client

    def dump(self, include_os: bool = True) -> dict[str, str | None]:
        variables: dict[str, Any] = {}
        if include_os:
            variables.update(os.environ)
        for field_ in self._fields(self):
            value = self._get_value(field_)
            if isinstance(value, list):
                value = ",".join(value)
            if value is not None:
                if field_.type is int:
                    variables[field_.name] = value
                else:
                    variables[field_.name] = str(value)
        return variables

    def as_string(self) -> str:
        env_lines: list[str] = [f"CDF_URL={self.cdf_url}"]
        body = "\n".join(env_lines)
        return f"CDF Project {self.CDF_PROJECT!r} in cluster {self.CDF_CLUSTER!r}:\n{body}"

    def get_missing_vars(self) -> set[str]:
        provider, flow = self.PROVIDER, self.LOGIN_FLOW
        missing: set[str] = set()
        for field_ in self._fields(self):
            required = field_.metadata["required"]
            value = getattr(self, field_.name)
            if value is None and required and ((provider, flow) in required or (None, flow) in required):
                missing.add(field_.name)

        # Special cases, if IDP_TENANT_ID is missing.
        if (provider, flow) == ("entra_id", "client_credentials") and "IDP_TENANT_ID" in missing and self.IDP_TOKEN_URL:
            missing -= {"IDP_TENANT_ID"}
        if (provider, flow) == ("entra_id", "interactive") and "IDP_TENANT_ID" in missing and self.IDP_AUTHORITY_URL:
            missing -= {"IDP_TENANT_ID"}
        return missing

    def get_required_with_value(self, lookup_default: bool = False) -> list[tuple[Field, Any]]:
        provider, flow = self.PROVIDER, self.LOGIN_FLOW
        values: list[tuple[Field, Any]] = []
        for field_ in self._fields(self):
            required = field_.metadata["required"]
            if required and ((provider, flow) in required or (None, flow) in required):
                if field_.name == "IDP_TOKEN_URL" and provider == "entra_id":
                    continue
                value = self._get_value(field_, lookup_default)
                values.append((field_, value))
        return values

    def _get_value(self, field_: Field, lookup_default: bool = True) -> Any:
        if lookup_default and (default_name := field_.name.casefold()):
            try:
                if hasattr(self, default_name):
                    return getattr(self, default_name)
            except ToolkitMissingValueError:
                ...
        return getattr(self, field_.name)

    def get_optional_with_value(self) -> list[tuple[Field, Any]]:
        provider, flow = self.PROVIDER, self.LOGIN_FLOW
        values: list[tuple[Field, Any]] = []
        for field_ in self._fields(self):
            optional = field_.metadata["optional"]
            if optional and ((provider, flow) in optional or (None, flow) in optional):
                value = self._get_value(field_)
                values.append((field_, value))
        return values

    def create_dotenv_file(self) -> str:
        lines = [
            "# .env file generated by cognite-toolkit",
            f"CDF_CLUSTER={self.CDF_CLUSTER}",
            f"CDF_PROJECT={self.CDF_PROJECT}",
        ]
        if self.LOGIN_FLOW != "token":
            lines += [
                f"PROVIDER={self.PROVIDER}",
            ]
        lines += [
            f"LOGIN_FLOW={self.LOGIN_FLOW}",
        ]
        lines.append("")
        lines.append("# Required variables")
        for field_, value in self.get_required_with_value(lookup_default=True):
            if value is not None:
                lines.append(f"{field_.name}={value}")
        lines.append("")
        lines.append("# Optional variables (derived from the required variables)")
        for field_, value in self.get_optional_with_value():
            if value is None:
                continue
            if isinstance(value, list):
                value = ",".join(value)
            lines.append(f"{field_.name}={value}")
        return "\n".join(lines) + "\n"


def prompt_user_environment_variables(current: EnvironmentVariables | None = None) -> EnvironmentVariables:
    provider = questionary.select(
        "Choose the provider (Who authenticates you?)",
        choices=[
            Choice(title=f"{provider}: {description}", value=provider)
            for provider, description in PROVIDER_DESCRIPTION.items()
        ],
        default=current.PROVIDER if current else "entra_id",
    ).ask()
    exclude = set()
    if provider == "cdf":
        exclude = set(VALID_LOGIN_FLOWS) - {"client_credentials"}
    choices = [
        Choice(title=f"{flow}: {description}", value=flow)
        for flow, description in LOGIN_FLOW_DESCRIPTION.items()
        if flow not in exclude
    ]
    if len(choices) == 1:
        print(f"Only one login flow available: {choices[0].title}")
        login_flow = choices[0].value
    else:
        login_flow = questionary.select(
            "Choose the login flow (How do you going to authenticate?)",
            choices=choices,
            default=current.LOGIN_FLOW if current else "client_credentials",
        ).ask()

    cdf_cluster = questionary.text("Enter the CDF cluster", default=current.CDF_CLUSTER if current else "").ask()
    cdf_project = questionary.text("Enter the CDF project", default=current.CDF_PROJECT if current else "").ask()
    args: dict[str, Any] = (
        current.dump(include_os=False)
        if current and _is_unchanged(current, provider, login_flow, cdf_project, cdf_cluster)  # type: ignore[arg-type]
        else {}
    )
    args.update(
        {"LOGIN_FLOW": login_flow, "CDF_CLUSTER": cdf_cluster, "CDF_PROJECT": cdf_project, "PROVIDER": provider}
    )
    env_vars = EnvironmentVariables(**args)
    idp_tenant_id = env_vars.IDP_TENANT_ID or "IDP_TENANT_ID"
    for field_, value in env_vars.get_required_with_value():
        user_value = get_user_value(field_, value, provider, cdf_cluster, cdf_project, idp_tenant_id)
        setattr(env_vars, field_.name, user_value)
        if field_.name == "IDP_TENANT_ID":
            idp_tenant_id = user_value

    optional_values = env_vars.get_optional_with_value()
    for field_, value in optional_values:
        print(f"  {field_.name}={value}")
    if questionary.confirm("Do you want to change any of these variables?", default=False).ask():
        for field_, value in optional_values:
            user_value = get_user_value(field_, value, provider, cdf_cluster, cdf_project, idp_tenant_id)
            setattr(env_vars, field_.name, user_value)
    return env_vars


def get_user_value(
    field_: Field, value: Any, provider: Provider, cdf_cluster: str, cdf_project: str, idp_tenant_id: str
) -> Any:
    is_secret = field_.metadata["is_secret"]
    display_name = field_.metadata["display_name"]
    if value:
        default = value
    else:
        default_example = field_.metadata["default_example"]
        default = (
            field_.metadata["example"]
            .get(provider, default_example)
            .format(CDF_CLUSTER=cdf_cluster, CDF_PROJECT=cdf_project, IDP_TENANT_ID=idp_tenant_id)
        )

    if isinstance(value, list):
        default = ",".join(value)
    elif value is not None and not isinstance(value, str):
        default = str(value)
    if is_secret:
        user_value = questionary.password(f"Enter the {display_name}:", default=default).ask()
    else:
        user_value = questionary.text(f"Enter the {display_name}:", default=default).ask()
    if user_value is None:
        raise typer.Exit(0)
    if field_.type is int:
        try:
            user_value = int(user_value)
        except ValueError:
            print(f"Invalid value: {user_value}. Please enter an integer.")
            return get_user_value(field_, value, provider, cdf_cluster, cdf_project, idp_tenant_id)
    return user_value


def _is_unchanged(
    current: EnvironmentVariables, provider: Provider, login_flow: LoginFlow, cdf_project: str, cdf_cluster: str
) -> bool:
    return (
        current.PROVIDER == provider
        and current.LOGIN_FLOW == login_flow
        and current.CDF_PROJECT == cdf_project
        and current.CDF_CLUSTER == cdf_cluster
    )


if __name__ == "__main__":
    # For easy testing
    envs = prompt_user_environment_variables()
    print(envs)
