import tempfile
from pathlib import Path

from rich import print
from rich.panel import Panel

from cognite_toolkit._cdf_tk.commands import BuildCommand, DeployCommand, ModulesCommand
from cognite_toolkit._cdf_tk.loaders import LOADER_BY_FOLDER_NAME
from cognite_toolkit._cdf_tk.utils.auth import CDFToolConfig


class CogniteToolkitDemo:
    def __init__(self) -> None:
        self._cdf_tool_config = CDFToolConfig()

    @property
    def _tmp_path(self) -> Path:
        return Path(tempfile.gettempdir()).resolve()

    @property
    def _build_dir(self) -> Path:
        build_path = self._tmp_path / "cognite-toolkit-build"
        build_path.mkdir(exist_ok=True)
        return build_path

    @property
    def _organization_dir(self) -> Path:
        organization_path = self._tmp_path / "cognite-toolkit-organization"
        organization_path.mkdir(exist_ok=True)
        return organization_path

    def quickstart(self) -> None:
        print(Panel("Running Toolkit QuickStart..."))
        # Lookup user ID to add user ID to the group to run the workflow
        user = self._cdf_tool_config.toolkit_client.iam.user_profiles.me()

        modules_cmd = ModulesCommand()
        modules_cmd.run(
            lambda: modules_cmd.init(
                organization_dir=self._organization_dir,
                user_select="quickstart",
                clean=True,
                user_download_data=True,
                user_environments=["dev"],
            )
        )
        config_yaml = self._organization_dir / "config.dev.yaml"
        config_raw = config_yaml.read_text()
        # Ensure the user can execute the workflow
        config_raw = config_raw.replace("<your user id>", user.user_identifier)
        # To avoid warnings about not set values
        config_raw = config_raw.replace("required_field: null", "required_field: 'value'")
        config_yaml.write_text(config_raw)

        build = BuildCommand()
        build.run(
            lambda: build.execute(
                build_dir=self._build_dir,
                organization_dir=self._organization_dir,
                selected=None,
                build_env_name="dev",
                verbose=False,
                ToolGlobals=self._cdf_tool_config,
                on_error="raise",
                no_clean=False,
            )
        )

        deploy = DeployCommand()

        deploy.run(
            lambda: deploy.execute(
                ToolGlobals=self._cdf_tool_config,
                build_dir=self._build_dir,
                build_env_name="dev",
                dry_run=False,
                drop_data=False,
                drop=False,
                force_update=False,
                include=list(LOADER_BY_FOLDER_NAME.keys()),
                verbose=False,
            )
        )
