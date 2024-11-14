# Copyright 2023 Cognite AS
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from __future__ import annotations

import time
from collections import defaultdict
from time import sleep

import questionary
from cognite.client.data_classes.capabilities import (
    Capability,
    FunctionsAcl,
    GroupsAcl,
    ProjectsAcl,
)
from cognite.client.data_classes.iam import Group, GroupList, GroupWrite, TokenInspection
from cognite.client.exceptions import CogniteAPIError
from rich import print
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from cognite_toolkit._cdf_tk import loaders
from cognite_toolkit._cdf_tk.client import ToolkitClient
from cognite_toolkit._cdf_tk.constants import HINT_LEAD_TEXT, TOOLKIT_SERVICE_PRINCIPAL_GROUP_NAME
from cognite_toolkit._cdf_tk.exceptions import (
    AuthenticationError,
    AuthorizationError,
    ResourceCreationError,
    ResourceDeleteError,
)
from cognite_toolkit._cdf_tk.tk_warnings import (
    HighSeverityWarning,
    LowSeverityWarning,
    MediumSeverityWarning,
    MissingCapabilityWarning,
)
from cognite_toolkit._cdf_tk.utils import AuthReader, AuthVariables, CDFToolConfig, humanize_collection

from ._base import ToolkitCommand


class AuthCommand(ToolkitCommand):
    def init(self, no_verify: bool = False, dry_run: bool = False) -> None:
        auth_vars = AuthVariables.from_env()

        prompt_user = True
        if auth_vars.is_complete:
            print("Auth variables are already set.")
            prompt_user = questionary.confirm("Do you want to reconfigure the auth variables?", default=False).ask()

        if prompt_user:
            reader = AuthReader(auth_vars, False)

            auth_vars = reader.from_user()
            if reader.messages:
                for message in reader.messages:
                    self.warn(MediumSeverityWarning(message))

        ToolGlobals = CDFToolConfig(skip_initialization=True)
        ToolGlobals.initialize_from_auth_variables(auth_vars, clear_cache=prompt_user)
        try:
            ToolGlobals.toolkit_client.iam.token.inspect()
        except CogniteAPIError as e:
            raise AuthenticationError(f"Unable to verify the credentials.\n{e}")

        print("[green]The credentials are valid.[/green]")
        if not no_verify:
            print(
                Panel(
                    "Running verification, 'cdf auth verify'...",
                    title="",
                    expand=False,
                )
            )
            self.verify(ToolGlobals, dry_run)

    def verify(
        self,
        ToolGlobals: CDFToolConfig,
        dry_run: bool,
        no_prompt: bool = False,
    ) -> None:
        is_interactive = not no_prompt
        if ToolGlobals.project is None:
            raise AuthorizationError("CDF_PROJECT is not set.")
        cdf_project = ToolGlobals.project
        token_inspection = self.check_has_any_access(ToolGlobals)

        self.check_has_project_access(token_inspection, cdf_project)

        print(f"[italic]Focusing on current project {cdf_project} only from here on.[/]")

        self.check_has_group_access(ToolGlobals)

        self.check_identity_provider(ToolGlobals, cdf_project)

        try:
            user_groups = ToolGlobals.toolkit_client.iam.groups.list()
        except CogniteAPIError as e:
            raise AuthorizationError(f"Unable to retrieve CDF groups.\n{e}")

        if not user_groups:
            raise AuthorizationError("The current user is not member of any groups in the CDF project.")

        loader_capabilities, loaders_by_capability_tuple = self._get_capabilities_by_loader(ToolGlobals)
        toolkit_group = self._create_toolkit_group(loader_capabilities)

        print(
            Panel(
                "The Cognite Toolkit expects the following:\n"
                " - The principal used with the Toolkit [yellow]should[/yellow] be connected to "
                "only ONE CDF Group.\n"
                f" - This group [red]must[/red] be named {toolkit_group.name!r}.\n"
                f" - The group {toolkit_group.name!r} [red]must[/red] have capabilities to "
                f"all resources the Toolkit is managing\n"
                " - All the capabilities [yellow]should[/yellow] be scoped to all resources.",
                title="Toolkit Access Group",
                expand=False,
            )
        )
        if is_interactive:
            Prompt.ask("Press enter key to continue...")

        all_groups = ToolGlobals.toolkit_client.iam.groups.list(all=True)

        is_user_in_toolkit_group = any(group.name == toolkit_group.name for group in user_groups)
        is_toolkit_group_existing = any(group.name == toolkit_group.name for group in all_groups)

        print(f"Checking current client is member of the {toolkit_group.name!r} group...")
        has_added_capabilities = False
        cdf_toolkit_group: Group | None
        if is_user_in_toolkit_group:
            print(f"  [bold green]OK[/] - The current client is member of the {toolkit_group.name!r} group.")
            cdf_toolkit_group = next(group for group in user_groups if group.name == toolkit_group.name)
            missing_capabilities = self._check_missing_capabilities(
                ToolGlobals, cdf_toolkit_group, toolkit_group, loaders_by_capability_tuple, is_interactive
            )
            if (
                is_interactive
                and missing_capabilities
                and questionary.confirm("Do you want to update the group with the missing capabilities?").ask()
            ):
                has_added_capabilities = self._update_missing_capabilities(
                    ToolGlobals, cdf_toolkit_group, missing_capabilities, dry_run
                )
        elif is_toolkit_group_existing:  # and not is_user_in_toolkit_group
            self.warn(MediumSeverityWarning(f"The current client is not member of the {toolkit_group.name!r} group."))
            print(f"Checking if the group {toolkit_group.name!r} has the required capabilities...")
            # Update the group with the missing capabilities
            cdf_toolkit_group = next(group for group in all_groups if group.name == toolkit_group.name)
            missing_capabilities = self._check_missing_capabilities(
                ToolGlobals, cdf_toolkit_group, toolkit_group, loaders_by_capability_tuple, is_interactive
            )
            if (
                is_interactive
                and missing_capabilities
                and questionary.confirm("Do you want to update the group with the missing capabilities?").ask()
            ):
                self._update_missing_capabilities(ToolGlobals, cdf_toolkit_group, missing_capabilities, dry_run)
        else:
            print(f"Group {toolkit_group.name!r} does not exist in the CDF project.")
            cdf_toolkit_group = self._create_toolkit_group_in_cdf(
                ToolGlobals, toolkit_group, all_groups, is_interactive, dry_run
            )
        if cdf_toolkit_group is None:
            return None

        if not is_user_in_toolkit_group:
            print(
                Panel(
                    f"To use the Toolkit, for example, 'cdf deploy', [red]you need to switch[/red] "
                    f"to the principal with source-id {cdf_toolkit_group.source_id!r}.",
                    title="Switch Principal",
                    expand=False,
                )
            )
            return None

        self.check_count_group_memberships(user_groups)

        self.check_source_id_usage(all_groups, cdf_toolkit_group)

        if extra := self.check_duplicated_names(all_groups, cdf_toolkit_group):
            if is_interactive and questionary.confirm("Do you want to delete the extra groups?", default=True).ask():
                try:
                    ToolGlobals.toolkit_client.iam.groups.delete(extra.as_ids())
                except CogniteAPIError as e:
                    raise ResourceDeleteError(f"Unable to delete the extra groups.\n{e}")
                print(f"  [bold green]OK[/] - Deleted {len(extra)} duplicated groups.")

        self.check_function_service_status(ToolGlobals.toolkit_client, dry_run, has_added_capabilities)

    def _create_toolkit_group_in_cdf(
        self,
        ToolGlobals: CDFToolConfig,
        toolkit_group: GroupWrite,
        all_groups: GroupList,
        is_interactive: bool,
        dry_run: bool,
    ) -> Group | None:
        if not is_interactive:
            raise AuthorizationError(
                f"Group {toolkit_group.name!r} does not exist in the CDF project. "
                "Please create the group and try again."
                f"\n{HINT_LEAD_TEXT}Run this command without --no-prompt to get assistance to create the group."
            )
        if not questionary.confirm(
            "Do you want to create a it?",
            default=True,
        ).ask():
            return None

        if dry_run:
            print(
                f"Would have created group {toolkit_group.name!r} with {len(toolkit_group.capabilities or [])} capabilities."
            )
            return None

        while True:
            source_id = questionary.text(
                "What is the source id for the new group (typically a group id in the identity provider)?"
            ).ask()
            if source_id:
                break
            print("Source id cannot be empty.")

        toolkit_group.source_id = source_id
        if already_used := [group.name for group in all_groups if group.source_id == source_id]:
            self.warn(
                HighSeverityWarning(
                    f"The source id {source_id!r} is already used by the groups: {humanize_collection(already_used)!r}."
                )
            )
            if not questionary.confirm("This is NOT recommended. Do you want to continue?", default=False).ask():
                return None
        created = ToolGlobals.toolkit_client.iam.groups.create(toolkit_group)
        print(
            f"  [bold green]OK[/] - Created new group {created.name}. It now has {len(created.capabilities or [])} capabilities."
        )
        return created

    def _check_missing_capabilities(
        self,
        ToolGlobals: CDFToolConfig,
        existing_group: Group,
        toolkit_group: GroupWrite,
        loaders_by_capability_id: dict[tuple, list[str]],
        is_interactive: bool,
    ) -> list[Capability]:
        print(f"\nChecking if the {existing_group.name} has the all required capabilities...")
        missing_capabilities = ToolGlobals.toolkit_client.iam.compare_capabilities(
            existing_group.capabilities or [],
            toolkit_group.capabilities or [],
            project=ToolGlobals.project,
        )
        if not missing_capabilities:
            print(f"  [bold green]OK[/] - The {existing_group.name} has all the required capabilities.")
            return []

        missing_capabilities = self._merge_capabilities(missing_capabilities)
        for s in sorted(map(str, missing_capabilities)):
            self.warn(MissingCapabilityWarning(s))

        resource_names: set[str] = set()
        for cap in missing_capabilities:
            for cap_tuple in cap.as_tuples():
                resource_names.update(loaders_by_capability_id[cap_tuple])
        if resource_names:
            print("[bold yellow]INFO:[/] The missing capabilities are required for the following resources:")
            for resource_name in resource_names:
                print(f"    - {resource_name}")

        if not is_interactive:
            raise AuthorizationError(
                "The service principal/application does not have the required capabilities for the Toolkit to support all resources"
            )
        return missing_capabilities

    def _update_missing_capabilities(
        self,
        ToolGlobals: CDFToolConfig,
        existing_group: Group,
        missing_capabilities: list[Capability],
        dry_run: bool,
    ) -> bool:
        """Updates the missing capabilities. This assumes interactive mode."""
        updated_toolkit_group = GroupWrite.load(existing_group.dump())
        if updated_toolkit_group.capabilities is None:
            updated_toolkit_group.capabilities = missing_capabilities
        else:
            updated_toolkit_group.capabilities.extend(missing_capabilities)

        adding = ToolGlobals.toolkit_client.iam.compare_capabilities(
            existing_group.capabilities or [],
            updated_toolkit_group.capabilities or [],
            project=ToolGlobals.project,
        )
        adding = self._merge_capabilities(adding)
        capability_str = "capabilities" if len(adding) > 1 else "capability"
        if dry_run:
            print(f"Would have updated group {updated_toolkit_group.name} with {len(adding)} new {capability_str}.")
            return False

        try:
            created = ToolGlobals.toolkit_client.iam.groups.create(updated_toolkit_group)
        except CogniteAPIError as e:
            raise ResourceCreationError(f"Unable to create group {updated_toolkit_group.name}.\n{e}")
        try:
            ToolGlobals.toolkit_client.iam.groups.delete(existing_group.id)
        except CogniteAPIError as e:
            raise ResourceDeleteError(
                f"Failed to cleanup old version of the {existing_group.name}.\n{e}\n"
                f"It is recommended that you manually delete the Group with ID {existing_group.id},"
                f"such that you don't have a duplicated group in your CDF project."
            )
        print(f"  [bold green]OK[/] - Updated the group {created.name} with {len(adding)} new {capability_str}.")
        return True

    @staticmethod
    def _create_toolkit_group(loader_capabilities: list[Capability]) -> GroupWrite:
        toolkit_group = GroupWrite(
            name=TOOLKIT_SERVICE_PRINCIPAL_GROUP_NAME,
            capabilities=[
                *loader_capabilities,
                # Add project ACL to be able to list and read projects, as the
                ProjectsAcl(
                    [ProjectsAcl.Action.Read, ProjectsAcl.Action.List, ProjectsAcl.Action.Update],
                    ProjectsAcl.Scope.All(),
                ),
            ],
        )
        return toolkit_group

    @staticmethod
    def _get_capabilities_by_loader(
        ToolGlobals: CDFToolConfig,
    ) -> tuple[list[Capability], dict[tuple, list[str]]]:
        loaders_by_capability_tuple: dict[tuple, list[str]] = defaultdict(list)
        capability_by_id: dict[frozenset[tuple], Capability] = {}
        for loader_cls in loaders.RESOURCE_LOADER_LIST:
            loader = loader_cls.create_loader(ToolGlobals, None)
            capability = loader_cls.get_required_capability(None, read_only=False)
            capabilities = capability if isinstance(capability, list) else [capability]
            for cap in capabilities:
                id_ = frozenset(cap.as_tuples())
                if id_ not in capability_by_id:
                    capability_by_id[id_] = cap
                for cap_tuple in cap.as_tuples():
                    loaders_by_capability_tuple[cap_tuple].append(loader.display_name)
        return list(capability_by_id.values()), loaders_by_capability_tuple

    def check_has_any_access(self, ToolGlobals: CDFToolConfig) -> TokenInspection:
        print("Checking basic project configuration...")
        try:
            # Using the token/inspect endpoint to check if the client has access to the project.
            # The response also includes access rights, which can be used to check if the client has the
            # correct access for what you want to do.
            token_inspection = ToolGlobals.toolkit_client.iam.token.inspect()
            if token_inspection is None or len(token_inspection.capabilities) == 0:
                raise AuthorizationError(
                    "Valid authentication token, but it does not give any access rights."
                    " Check credentials (CDF_CLIENT_ID/CDF_CLIENT_SECRET or CDF_TOKEN)."
                )
            print("  [bold green]OK[/]")
        except CogniteAPIError as e:
            raise AuthorizationError(
                "Not a valid authentication token. Check credentials (CDF_CLIENT_ID/CDF_CLIENT_SECRET or CDF_TOKEN)."
                "This could also be due to the service principal/application not having access to any Groups."
                f"\n{e}"
            )
        return token_inspection

    def check_has_project_access(self, token_inspection: TokenInspection, cdf_project: str) -> None:
        print("Checking projects that the service principal/application has access to...")
        if len(token_inspection.projects) == 0:
            raise AuthorizationError(
                "The service principal/application configured for this client does not have access to any projects."
            )
        print("\n".join(f"  - {p.url_name}" for p in token_inspection.projects))
        if cdf_project not in {p.url_name for p in token_inspection.projects}:
            raise AuthorizationError(
                f"The service principal/application configured for this client does not have access to the CDF_PROJECT={cdf_project!r}."
            )

    def check_has_group_access(self, ToolGlobals: CDFToolConfig) -> None:
        # Todo rewrite to use the token inspection instead.
        print(
            "Checking basic project and group manipulation access rights "
            "(projectsAcl: LIST, READ and groupsAcl: LIST, READ, CREATE, UPDATE, DELETE)..."
        )
        try:
            ToolGlobals.verify_authorization(
                [
                    ProjectsAcl([ProjectsAcl.Action.List, ProjectsAcl.Action.Read], ProjectsAcl.Scope.All()),
                    GroupsAcl(
                        [
                            GroupsAcl.Action.Read,
                            GroupsAcl.Action.List,
                            GroupsAcl.Action.Create,
                            GroupsAcl.Action.Update,
                            GroupsAcl.Action.Delete,
                        ],
                        GroupsAcl.Scope.All(),
                    ),
                ]
            )
            print("  [bold green]OK[/]")
        except AuthorizationError:
            self.warn(
                HighSeverityWarning(
                    "The service principal/application configured for this client "
                    "does not have the basic group write access rights."
                )
            )
            print("Checking basic group read access rights (projectsAcl: LIST, READ and groupsAcl: LIST, READ)...")
            try:
                ToolGlobals.verify_authorization(
                    capabilities=[
                        ProjectsAcl([ProjectsAcl.Action.List, ProjectsAcl.Action.Read], ProjectsAcl.Scope.All()),
                        GroupsAcl([GroupsAcl.Action.Read, GroupsAcl.Action.List], GroupsAcl.Scope.All()),
                    ]
                )
                print("  [bold green]OK[/] - can continue with checks.")
            except AuthorizationError:
                raise AuthorizationError(
                    "Unable to continue, the service principal/application configured for this client does not"
                    " have the basic read group access rights."
                )

    def check_identity_provider(self, ToolGlobals: CDFToolConfig, cdf_project: str) -> None:
        print("Checking identity provider settings...")
        project_info = ToolGlobals.toolkit_client.get(f"/api/v1/projects/{cdf_project}").json()
        oidc = project_info.get("oidcConfiguration", {})
        if "https://login.windows.net" in oidc.get("tokenUrl"):
            tenant_id = oidc.get("tokenUrl").split("/")[-3]
            print(f"  [bold green]OK[/]: Microsoft Entra ID (aka ActiveDirectory) with tenant id ({tenant_id}).")
        elif "auth0.com" in oidc.get("tokenUrl"):
            tenant_id = oidc.get("tokenUrl").split("/")[2].split(".")[0]
            print(f"  [bold green]OK[/] - Auth0 with tenant id ({tenant_id}).")
        else:
            self.warn(MediumSeverityWarning(f"Unknown identity provider {oidc.get('tokenUrl')}"))
        access_claims = [c.get("claimName") for c in oidc.get("accessClaims", {})]
        print(
            f"  Matching on CDF group sourceIds will be done on any of these claims from the identity provider: {access_claims}"
        )

    def check_count_group_memberships(self, user_group: GroupList) -> None:
        print("Checking CDF group memberships for the current client configured...")

        table = Table(title="CDF Group ids, Names, and Source Ids")
        table.add_column("Id", justify="left")
        table.add_column("Name", justify="left")
        table.add_column("Source Id", justify="left")
        for group in user_group:
            name = group.name
            if group.name == TOOLKIT_SERVICE_PRINCIPAL_GROUP_NAME:
                name = f"[bold]{group.name}[/]"
            table.add_row(str(group.id), name, group.source_id)
        print(table)

        if len(user_group) > 1:
            self.warn(
                LowSeverityWarning(
                    "This service principal/application gets its access rights from more than one CDF group."
                    "\nThis is not recommended. The group matching the group config file is marked in "
                    "bold above if it is present."
                )
            )
        else:
            print("  [bold green]OK[/] - Only one group is used for this service principal/application.")

    def check_source_id_usage(self, all_groups: GroupList, cdf_toolkit_group: Group) -> None:
        reuse_source_id = [
            group.name
            for group in all_groups
            if group.source_id == cdf_toolkit_group.source_id and group.id != cdf_toolkit_group.id
        ]
        if reuse_source_id:
            group_names_str = humanize_collection(reuse_source_id)
            self.warn(
                MediumSeverityWarning(
                    f"The following groups have the same source id, {cdf_toolkit_group.source_id},\n"
                    f"as the {cdf_toolkit_group.name!r} group: \n    {group_names_str!r}.\n"
                    f"It is recommended that only the {cdf_toolkit_group.name!r} group has this source id."
                )
            )

    def check_duplicated_names(self, all_groups: GroupList, cdf_toolkit_group: Group) -> GroupList:
        extra = GroupList(
            [group for group in all_groups if group.name == cdf_toolkit_group.name and group.id != cdf_toolkit_group.id]
        )
        if extra:
            self.warn(
                MediumSeverityWarning(
                    f"There are multiple groups with the same name {cdf_toolkit_group.name} in the CDF project."
                    "           It is recommended that this admin (CI/CD) application/service principal "
                    "only is member of one group in the identity provider. Suggest you delete all but one"
                    "           of the groups with the same name."
                )
            )

        return extra

    @staticmethod
    def _merge_capabilities(capability_list: list[Capability]) -> list[Capability]:
        """Merges capabilities that have the same ACL and Scope"""
        actions_by_scope_and_cls: dict[tuple[type[Capability], Capability.Scope], set[Capability.Action]] = defaultdict(
            set
        )
        for capability in capability_list:
            actions_by_scope_and_cls[(type(capability), capability.scope)].update(capability.actions)
        return [
            cap_cls(actions=list(actions), scope=scope, allow_unknown=False)
            for (cap_cls, scope), actions in actions_by_scope_and_cls.items()
        ]

    def check_function_service_status(self, client: ToolkitClient, dry_run: bool, has_added_capabilities: bool) -> None:
        print("Checking function service status...")
        has_function_read_access = self.has_function_rights(client, [FunctionsAcl.Action.Read], has_added_capabilities)
        if not has_function_read_access:
            self.warn(HighSeverityWarning("Cannot check function service status, missing function read access."))
            return None
        try:
            function_status = client.functions.status()
        except CogniteAPIError as e:
            self.warn(HighSeverityWarning(f"Unable to check function service status.\n{e}"))
            return None

        if function_status.status == "requested":
            print("  [bold yellow]INFO:[/] Function service activation is in progress (may take up to 2 hours)...")
        elif dry_run and function_status.status != "activated":
            print(
                "  [bold yellow]INFO:[/] Function service has not been activated, "
                "would have activated (will take up to 2 hours)..."
            )
        elif not dry_run and function_status.status != "activated":
            has_function_write_access = self.has_function_rights(
                client, [FunctionsAcl.Action.Write], has_added_capabilities
            )
            if not has_function_write_access:
                self.warn(HighSeverityWarning("Cannot activate function service, missing function write access."))
                return None
            try:
                client.functions.activate()
            except CogniteAPIError as e:
                self.warn(HighSeverityWarning(f"Unable to activate function service.\n{e}"))
                return None
            print(
                "  [bold green]OK[/] - Function service has been activated. "
                "This may take up to 2 hours to take effect."
            )

        else:
            print("  [bold green]OK[/] - Function service has been activated.")

        return None

    def has_function_rights(
        self, client: ToolkitClient, actions: list[FunctionsAcl.Action], has_added_capabilities: bool
    ) -> bool:
        t0 = time.perf_counter()
        while not (
            has_function_access := not client.iam.verify_capabilities(
                FunctionsAcl(actions, FunctionsAcl.Scope.All()),
            )
        ):
            if has_added_capabilities and (time.perf_counter() - t0 < 5.0):
                # Wait for the IAM service to update the capabilities
                sleep(1.0)
            else:
                break
        return has_function_access
