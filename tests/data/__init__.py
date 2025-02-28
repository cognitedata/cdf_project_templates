from pathlib import Path

DATA_FOLDER = Path(__file__).resolve().parent

DESCRIPTIONS_FOLDER = DATA_FOLDER / "describe_data"
AUTH_DATA = DATA_FOLDER / "auth_data"
PROJECT_NO_COGNITE_MODULES = DATA_FOLDER / "project_no_cognite_modules"
RESOURCES_WITH_ENVIRONMENT_VARIABLES = DATA_FOLDER / "resources_with_environment_variables"
PROJECT_WITH_DUPLICATES = DATA_FOLDER / "project_with_duplicates"
PROJECT_FOR_TEST = DATA_FOLDER / "project_for_test"
LOAD_DATA = DATA_FOLDER / "load_data"
RUN_DATA = DATA_FOLDER / "run_data"
TRANSFORMATION_CLI = DATA_FOLDER / "transformation_cli"
PROJECT_WITH_BAD_MODULES = DATA_FOLDER / "project_with_bad_modules"

BUILD_GROUP_WITH_UNKNOWN_ACL = DATA_FOLDER / "build_group_with_unknown_acl"
COMPLETE_ORG = DATA_FOLDER / "complete_org"
COMPLETE_ORG_ALPHA_FLAGS = DATA_FOLDER / "complete_org_alpha_flags"
CDF_TOML_DATA = DATA_FOLDER / "cdf_toml_data"
ORG_FOR_PULL = DATA_FOLDER / "org_for_pull"

__all__ = [
    "AUTH_DATA",
    "BUILD_GROUP_WITH_UNKNOWN_ACL",
    "CDF_TOML_DATA",
    "COMPLETE_ORG",
    "DATA_FOLDER",
    "DESCRIPTIONS_FOLDER",
    "LOAD_DATA",
    "ORG_FOR_PULL",
    "PROJECT_FOR_TEST",
    "PROJECT_NO_COGNITE_MODULES",
    "PROJECT_WITH_BAD_MODULES",
    "PROJECT_WITH_DUPLICATES",
    "RESOURCES_WITH_ENVIRONMENT_VARIABLES",
    "RUN_DATA",
    "TRANSFORMATION_CLI",
]
