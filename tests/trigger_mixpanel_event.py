"""This script is for triggering a Mixpanel event. It is used for testing purposes only."""

import sys
from pathlib import Path

from cognite_toolkit._cdf_tk.cdf_toml import CDFToml
from cognite_toolkit._cdf_tk.data_classes import (
    BuildLocationEager,
    BuildVariables,
    BuiltModule,
    ResourceBuildInfo,
    ResourceBuiltList,
)
from cognite_toolkit._cdf_tk.tk_warnings import WarningList
from cognite_toolkit._cdf_tk.tracker import Tracker
from tests.constants import REPO_ROOT, chdir


def track_cli_command() -> None:
    sys.argv = ["commandTest", "pos0", "pos1", "--opt1", "opt1", "--opt2", "opt2", "--flag"]

    with chdir(REPO_ROOT):
        # To ensure that cdf.toml is loaded correctly
        _ = CDFToml.load()
        tracker = Tracker()
        is_sent = tracker.track_cli_command(WarningList([]), "Success", "test")
        if is_sent:
            print("Event sent")
        else:
            print("Event not sent")


def track_module_build() -> None:
    with chdir(REPO_ROOT):
        # To ensure that cdf.toml is loaded correctly
        tracker = Tracker()
        is_sent = tracker.track_module_build(DEMO_MODULE)
        if is_sent:
            print("Event sent")
        else:
            print("Event not sent")


DEMO_MODULE = BuiltModule(
    "cdf_module_test",
    location=BuildLocationEager(
        path=Path("modules/cdf_module_test"),
        _hash="hash",
    ),
    build_variables=BuildVariables([]),
    resources={
        "files": ResourceBuiltList(
            [
                ResourceBuildInfo("file1", BuildLocationEager(Path("files/file1.yaml"), "hash"), kind="File"),
            ]
        ),
        "functions": ResourceBuiltList(
            [
                ResourceBuildInfo(
                    "function1",
                    BuildLocationEager(Path("functions/function1.yaml"), "hash"),
                    kind="Function",
                )
            ]
        ),
    },
    warning_count=4,
    status="success",
)

if __name__ == "__main__":
    # track_module_build()
    track_cli_command()
