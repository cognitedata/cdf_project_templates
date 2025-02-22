from collections.abc import Hashable, Iterator
from typing import Any, Literal, overload
from urllib.parse import urlparse

from cognite.client.credentials import OAuthClientCredentials
from cognite.client.data_classes import (
    ClientCredentials,
    OidcCredentials,
)
from cognite.client.data_classes.data_modeling import Edge, Node, ViewId
from cognite.client.data_classes.filters import SpaceFilter
from cognite.client.exceptions import CogniteAPIError
from rich.console import Console

from cognite_toolkit._cdf_tk.client import ToolkitClient
from cognite_toolkit._cdf_tk.constants import ENV_VAR_PATTERN
from cognite_toolkit._cdf_tk.exceptions import (
    ToolkitRequiredValueError,
    ToolkitTypeError,
)
from cognite_toolkit._cdf_tk.feature_flags import Flags
from cognite_toolkit._cdf_tk.tk_warnings import (
    HighSeverityWarning,
    MediumSeverityWarning,
)
from cognite_toolkit._cdf_tk.utils import humanize_collection


def try_find_error(credentials: OidcCredentials | ClientCredentials | None) -> str | None:
    if credentials is None:
        return None
    missing: list[str] = []
    if client_id := ENV_VAR_PATTERN.match(credentials.client_id):
        missing.append(client_id.group(1))
    if client_secret := ENV_VAR_PATTERN.match(credentials.client_secret):
        missing.append(client_secret.group(1))
    if missing:
        plural = "s are" if len(missing) > 1 else " is"
        return f"The environment variable{plural} not set: {humanize_collection(missing)}."
    if isinstance(credentials, ClientCredentials):
        return None
    try:
        result = urlparse(credentials.token_uri)
        if not all([result.scheme, result.netloc]):
            raise ValueError
    except ValueError:
        return f"The tokenUri {credentials.token_uri!r} is not a valid URI."
    return None


@overload
def iterate_instances(
    client: ToolkitClient,
    instance_type: Literal["node"] = "node",
    space: str | None = None,
    source: ViewId | None = None,
    console: Console | None = None,
) -> Iterator[Node]: ...


@overload
def iterate_instances(
    client: ToolkitClient,
    instance_type: Literal["edge"],
    space: str | None = None,
    source: ViewId | None = None,
    console: Console | None = None,
) -> Iterator[Edge]: ...


def iterate_instances(
    client: ToolkitClient,
    instance_type: Literal["node", "edge"] = "node",
    space: str | None = None,
    source: ViewId | None = None,
    console: Console | None = None,
) -> Iterator[Node] | Iterator[Edge]:
    """Toolkit specific implementation of the client.data_modeling.instances(...) method to account for 408.

    In addition, we enforce sort based on the argument below (provided by Alex B.).
    """
    body: dict[str, Any] = {"limit": 1_000, "cursor": None, "instanceType": instance_type}
    # Without a sort, the sort is implicitly by the internal id, as cursoring needs a stable sort.
    # By making the sort be on external_id, Postgres should pick the index that's on (project_id, space, external_id)
    # WHERE deleted_at IS NULL. In other words, avoiding soft deleted instances.
    body["sort"] = [
        {
            "property": [instance_type, "externalId"],
            "direction": "ascending",
        }
    ]
    url = f"/api/{client._API_VERSION}/projects/{client.config.project}/models/instances/list"
    if space:
        body["filter"] = SpaceFilter(space=space, instance_type=instance_type).dump()
    if source:
        body["sources"] = [{"source": source.dump(include_type=True, camel_case=True)}]
    while True:
        try:
            response = client.post(url=url, json=body)
        except CogniteAPIError as e:
            if e.code == 408 and body["limit"] > 1:
                MediumSeverityWarning(
                    f"Timeout with limit {body['limit']}, retrying with {body['limit'] // 2}."
                ).print_warning(include_timestamp=True, console=console)
                body["limit"] = body["limit"] // 2
                continue
            raise e
        response_body = response.json()
        if instance_type == "node":
            yield from (Node.load(node) for node in response_body["items"])
        else:
            yield from (Edge.load(edge) for edge in response_body["items"])
        next_cursor = response_body.get("nextCursor")
        if next_cursor is None:
            break
        body["cursor"] = next_cursor


def read_auth(
    identifier: Hashable,
    resource: dict[str, Any],
    client: ToolkitClient,
    resource_name: str,
    console: Console | None = None,
) -> ClientCredentials:
    auth = resource.get("authentication")
    if auth is None:
        if (client.config.is_strict_validation and Flags.STRICT_VALIDATION.is_enabled()) or not isinstance(
            client.config.credentials, OAuthClientCredentials
        ):
            raise ToolkitRequiredValueError(f"Authentication is missing for {resource_name} {identifier!r}.")
        else:
            HighSeverityWarning(
                f"Authentication is missing for {resource_name} {identifier!r}. Falling back to the Toolkit credentials"
            ).print_warning(console=console)
        credentials = ClientCredentials(client.config.credentials.client_id, client.config.credentials.client_secret)
    elif not isinstance(auth, dict):
        raise ToolkitTypeError(f"Authentication must be a dictionary for {resource_name} {identifier!r}")
    elif "clientId" not in auth or "clientSecret" not in auth:
        raise ToolkitRequiredValueError(
            f"Authentication must contain clientId and clientSecret for {resource_name} {identifier!r}"
        )
    else:
        credentials = ClientCredentials(auth["clientId"], auth["clientSecret"])
    return credentials
