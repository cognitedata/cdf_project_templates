import shutil
import sys
import venv
from pathlib import Path
from subprocess import PIPE, Popen
from types import SimpleNamespace

from cognite_toolkit._cdf_tk.exceptions import ToolkitEnvError


class FunctionVirtualEnvironment(venv.EnvBuilder):
    def __init__(self, requirements_txt: Path) -> None:
        super().__init__(
            system_site_packages=False,
            clear=True,
            with_pip=True,
        )
        self.requirements_txt = requirements_txt
        self._context: SimpleNamespace | None = None

    def post_setup(self, context: SimpleNamespace) -> None:
        args = [str(context.env_exe), "install", "-r", "requirements.txt"]

        function_dir = Path(context.env_dir).parent
        requirements_destination_path = function_dir / "requirements.txt"
        shutil.copy(self.requirements_txt, requirements_destination_path)

        process = Popen(args, stdout=PIPE, stderr=sys.stderr, cwd=str(function_dir))
        process.wait()
        if process.returncode != 0:
            raise ToolkitEnvError(f"Invalid 'requirements.txt' file in {self.requirements_txt.as_posix()}")
        self._context = context

    def check_import(self) -> None: ...

    def run(self, environment: dict[str, str]) -> None: ...
