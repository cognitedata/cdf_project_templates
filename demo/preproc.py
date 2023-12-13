#!/usr/bin/env python
import os, shutil
from pathlib import Path

import yaml

THIS_FOLDER = Path(__file__).parent.absolute()
DEMO_PROJECT = THIS_FOLDER.parent / "demo_project"


def run() -> None:
    print("Running copy commands to prep deployment of demo...")
    os.makedirs(DEMO_PROJECT, exist_ok=True)
    print("Copying my enviroments.yaml to root of repo...")
    shutil.copy(THIS_FOLDER / "environments.yaml", DEMO_PROJECT / "environments.yaml")
    print("Copying config.yaml into demo project...")
    shutil.copy(THIS_FOLDER / "config.yaml", DEMO_PROJECT / "config.yaml")
    config_yaml_path = DEMO_PROJECT / "config.yaml"

    variables = yaml.safe_load((THIS_FOLDER / "config.yaml").read_text())
    config_yaml = config_yaml_path.read_text()
    for key, value in variables.items():
        config_yaml = config_yaml.replace(f"{key}: <change_me>", f"{key}: {value}")
    
    config_yaml_path.write_text(config_yaml)


if __name__ == "__main__":
    run()
