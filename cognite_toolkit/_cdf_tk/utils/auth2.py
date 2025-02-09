from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Literal, TypeAlias, get_args

from cognite_toolkit._cdf_tk.exceptions import AuthenticationError, ToolkitMissingValueError
from cognite_toolkit._version import __version__

LoginFlow: TypeAlias = Literal["client_credentials", "token", "device_code", "interactive"]
Provider: TypeAlias = Literal["entra_id", "cdf", "other"]
VALID_LOGIN_FLOWS = get_args(LoginFlow)

CLIENT_NAME = f"CDF-Toolkit:{__version__}"
LOGIN_FLOW_DESCRIPTION = {
    "client_credentials": "Setup a service principal with client credentials",
    "interactive": "Login using the browser with your user credentials",
    "device_code": "Login using the browser with your user credentials using device code flow",
    "token": "Use a Token directly to authenticate",
}
PROVIDER_DESCRIPTION = {
    "entra_id": "Use Microsoft Entra ID to authenticate",
    "cdf": "Use Cognite IDP to authenticate",
    "other": "Use other IDP to authenticate",
}


@dataclass
class EnvOptions(Mapping):
    display_name: str
    example: str
    is_secret: bool = False

    def __getitem__(self, key: str) -> str | bool:
        return self.__dict__[key]

    def __iter__(self) -> Iterable[str]:  # type: ignore[override]
        return iter(self.__dict__.keys())

    def __len__(self) -> int:
        return len(self.__dict__)


@dataclass
class EnvironmentVariables:
    CDF_CLUSTER: str = field(metadata=EnvOptions("CDF cluster", "westeurope-1"))
    CDF_PROJECT: str = field(metadata=EnvOptions("CDF project", "publicdata"))
    CDF_URL: str | None = field(default=None, metadata=EnvOptions("CDF URL", "https://CDF_CLUSTER.cognitedata.com"))
    LOGIN_FLOW: LoginFlow = field(default="client_credentials", metadata=EnvOptions("Login flow", "client_credentials"))
    PROVIDER: Provider = field(default="entra_id", metadata=EnvOptions("Provider", "entra_id"))
    CDF_TOKEN: str | None = field(default=None, metadata=EnvOptions("OAuth2 token", example=""))
    IDP_CLIENT_ID: str | None = field(
        default=None, metadata=EnvOptions(display_name="client id", example="XXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX")
    )
    IDP_CLIENT_SECRET: str | None = field(
        default=None, metadata=EnvOptions(display_name="client secret", example="***")
    )
    IDP_TOKEN_URL: str | None = field(
        default=None,
        metadata=EnvOptions(
            display_name="token URL", example="https://login.microsoftonline.com/{IDP_TENANT_ID}/oauth2/v2.0/token"
        ),
    )
    IDP_TENANT_ID: str | None = field(
        default=None, metadata=EnvOptions(display_name="Tenant id for MS Entra", example="mytenant.onmicrosoft.com")
    )
    IDP_AUDIENCE: str | None = field(
        default=None, metadata=EnvOptions(display_name="IDP audience", example="https://{CDF_CLUSTER}.cognitedata.com")
    )
    IDP_SCOPES: str | None = field(
        default=None,
        metadata=EnvOptions(display_name="IDP scopes", example="https://{CDF_CLUSTER}.cognitedata.com/.default"),
    )
    IDP_AUTHORITY_URL: str | None = field(
        default=None,
        metadata=EnvOptions(
            display_name="IDP authority URL", example="https://login.microsoftonline.com/{IDP_TENANT_ID}"
        ),
    )
    IDP_DISCOVERY_URL: str | None = field(
        default=None,
        metadata=EnvOptions(
            display_name="IDP OIDC discovery URL (root URL excl. /.well-known/...)",
            example="https://<auth0-tenant>.auth0.com/oauth",
        ),
    )
    CDF_CLIENT_TIMEOUT: int = field(default=30, metadata=EnvOptions(display_name="CDF client timeout", example="30"))
    CDF_CLIENT_MAX_WORKERS: int = field(
        default=5, metadata=EnvOptions(display_name="CDF client max workers", example="5")
    )

    def __post_init__(self) -> None:
        if self.LOGIN_FLOW not in VALID_LOGIN_FLOWS:
            raise AuthenticationError(f"Invalid login flow: {self.LOGIN_FLOW}. Valid options are {VALID_LOGIN_FLOWS}")

    # All derived properties
    @property
    def idp_token_url(self) -> str:
        if self.IDP_TOKEN_URL:
            return self.IDP_TOKEN_URL
        if self.PROVIDER == "entra_id" and self.IDP_TENANT_ID:
            return f"https://login.microsoftonline.com/{self.IDP_TENANT_ID}/oauth2/v2.0/token"
        alternative = ""
        if self.PROVIDER == "entra_id":
            alternative = " or provide IDP_TENANT_ID"
        raise ToolkitMissingValueError(
            f"IDP_TOKEN_URL is missing. Please provide it{alternative} in the environment variables."
        )

    @property
    def cdf_url(self) -> str:
        return self.CDF_URL or f"https://{self.CDF_CLUSTER}.cognitedata.com"

    @property
    def idp_audience(self) -> str:
        return self.IDP_AUDIENCE or f"https://{self.CDF_CLUSTER}.cognitedata.com"

    @property
    def idp_scopes(self) -> list[str]:
        if self.IDP_SCOPES:
            return self.IDP_SCOPES.split(",")
        return [f"https://{self.CDF_CLUSTER}.cognitedata.com/.default"]

    @property
    def idp_authority_url(self) -> str:
        if self.IDP_AUTHORITY_URL:
            return self.IDP_AUTHORITY_URL
        if self.PROVIDER == "entra_id" and self.IDP_TENANT_ID:
            return f"https://login.microsoftonline.com/{self.IDP_TENANT_ID}"
        alternative = ""
        if self.PROVIDER == "entra_id":
            alternative = " or provide IDP_TENANT_ID"
        raise ToolkitMissingValueError(
            f"IDP_AUTHORITY_URL is missing. Please provide it{alternative} in the environment variables."
        )
