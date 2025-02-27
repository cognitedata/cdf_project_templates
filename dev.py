"""This is a small CLI used to develop Toolkit.

It is not used in production and is only intended to be used for development purposes.
"""

import itertools
import re
from pathlib import Path
from typing import Literal, get_args

import marko
import marko.block
import marko.element
import marko.inline
import typer
from packaging.version import Version, parse
from rich import print

REPO_ROOT = Path(__file__).parent
CHANGELOG = REPO_ROOT / "CHANGELOG.cdf-tk.md"
TEMPLATE_CHANGELOG = REPO_ROOT / "CHANGELOG.templates.md"
TBD_HEADING = "## TBD"
IMAGE_NAME = "cognite/toolkit"
CDF_TOML = REPO_ROOT / "cdf.toml"

VALID_CHANGELOG_HEADERS = {"Added", "Changed", "Removed", "Fixed"}
BUMP_OPTIONS = Literal["major", "minor", "patch", "skip"]
VALID_BUMP_OPTIONS = get_args(BUMP_OPTIONS)
LAST_GIT_MESSAGE_FILE = REPO_ROOT / "last_git_message.txt"
CHANGELOG_ENTRY_FILE = REPO_ROOT / "last_changelog_entry.md"
LAST_VERSION = REPO_ROOT / "last_version.txt"
VERSION_PLACEHOLDER = "0.0.0"

app = typer.Typer(
    add_completion=False,
    help=__doc__,
    pretty_exceptions_short=False,
    pretty_exceptions_show_locals=False,
    pretty_exceptions_enable=False,
)


@app.command()
def bump(verbose: bool = False) -> None:
    version_files = [
        REPO_ROOT / "pyproject.toml",
        REPO_ROOT / "cognite_toolkit" / "_version.py",
        REPO_ROOT / "cdf.toml",
        *(REPO_ROOT / "tests" / "data").rglob("cdf.toml"),
        *(REPO_ROOT / "tests" / "data").rglob("_build_environment.yaml"),
        *(REPO_ROOT / "cognite_toolkit").rglob("cdf.toml"),
    ]
    docker_image_files = [
        *(REPO_ROOT / "cognite_toolkit" / "_repo_files").rglob("*.yml"),
        *(REPO_ROOT / "cognite_toolkit" / "_repo_files").rglob("*.yaml"),
    ]
    last_version_str = LAST_VERSION.read_text().strip().removeprefix("v")
    try:
        last_version = parse(last_version_str)
    except ValueError:
        print(f"Invalid last version: {last_version_str}")
        raise SystemExit(1)

    changelog_items, _ = _read_last_commit_message()
    version_bump = _get_change(changelog_items)
    if version_bump == "skip":
        print("No changes to release.")
        return
    if version_bump == "major":
        new_version = Version(f"{last_version.major + 1}.0.0")
    elif version_bump == "minor":
        new_version = Version(f"{last_version.major}.{last_version.minor + 1}.0")
    elif version_bump == "patch":
        new_version = Version(f"{last_version.major}.{last_version.minor}.{last_version.micro + 1}")
    else:
        raise typer.BadParameter("You must specify one of major, minor, patch, alpha, or beta.")

    for file in version_files:
        file.write_text(file.read_text().replace(str(VERSION_PLACEHOLDER), str(new_version), 1))
        if verbose:
            typer.echo(f"Bumped version from {last_version} to {new_version} in {file}.")
    for file in docker_image_files:
        file.write_text(file.read_text().replace(f"{IMAGE_NAME}:{last_version!s}", f"{IMAGE_NAME}:{new_version!s}", 1))
        if verbose:
            typer.echo(f"Bumped version from {last_version} to {new_version} in {file}.")

    typer.echo(f"Bumped version from {last_version} to {new_version} in {len(version_files)} files.")


@app.command("alpha")
def set_alpha(off: bool = False) -> None:
    if not off:
        return
    is_feature_flag = False
    new_lines = []
    for line in CDF_TOML.read_text().splitlines():
        if header_match := re.match(r"\[(\w+)\]", line.strip()):
            header = header_match.group(1)
            print(header)
            if header == "alpha_flags":
                is_feature_flag = True
            else:
                is_feature_flag = False
        if is_feature_flag:
            line = line.replace("true", "false")
        new_lines.append(line)

    CDF_TOML.write_text("\n".join(new_lines) + "\n")


@app.command("changelog")
def create_changelog_entry() -> None:
    changelog_items, changelog_text = _read_last_commit_message()
    version_bump = _get_change(changelog_items)
    if version_bump == "skip":
        print("No changes to release.")
        return
    if not changelog_items[1:]:
        print(f"Trying to {version_bump} bump but no changes found in the changelog.")
        raise SystemExit(1)
    if not _is_header(changelog_items[1], level=2, text="cdf"):
        print("The first header in the changelog must be '## cdf'.")
        raise SystemExit(1)
    cdf_entries = list(itertools.takewhile(lambda x: not _is_header(x, level=2), changelog_items[2:]))
    _validate_entries(cdf_entries, "cdf")
    no = next((no for no, item in enumerate(changelog_items) if _is_header(item, level=2, text="templates")), None)
    if no is None:
        print("No '## templates' section found in the changelog.")
        raise SystemExit(1)
    if not changelog_items[no + 1 :]:
        print("No template entries found in the changelog.")
        raise SystemExit(1)
    template_entries = list(changelog_items[no + 1 :])
    _validate_entries(template_entries, "templates")

    changelog_entry = changelog_text.split("## cdf")[1]
    CHANGELOG_ENTRY_FILE.write_text(f"## cdf {changelog_entry}", encoding="utf-8")
    print(f"Changelog entry written to {CHANGELOG_ENTRY_FILE}.")


def _read_last_commit_message() -> tuple[list[marko.element.Element], str]:
    last_git_message = LAST_GIT_MESSAGE_FILE.read_text()
    if "## Changelog" not in last_git_message:
        print("No changelog entry found in the last commit message.")
        raise SystemExit(1)
    changelog_text = last_git_message.split("## Changelog")[1].strip()
    changelog_items = [
        item for item in marko.parse(changelog_text).children if not isinstance(item, marko.block.BlankLine)
    ]
    if not changelog_items:
        print("No changelog items found in the last commit message.")
        raise SystemExit(1)
    return changelog_items, changelog_text


def _is_header(item: marko.element.Element, level: int, text: str | None = None):
    if not (
        isinstance(item, marko.block.Heading)
        and item.level == level
        and isinstance(item.children[0], marko.inline.RawText)
    ):
        return False
    return text is None or item.children[0].children == text


def _get_change(changelog_items: list[marko.element.Element]) -> Literal["major", "minor", "patch", "skip"]:
    item = changelog_items[0]
    if not isinstance(item, marko.block.List):
        print("The first item in the changelog must be a list with the type of change.")
        raise SystemExit(1)
    selected: list[Literal["major", "minor", "patch", "skip"]] = []
    for child in item.children:
        if not isinstance(child, marko.block.ListItem):
            print(f"Unexpected item in changelog: {child}")
            raise SystemExit(1)
        if not isinstance(child.children[0], marko.block.Paragraph):
            print(f"Unexpected item in changelog: {child.children[0]}")
            raise SystemExit(1)
        if not isinstance(child.children[0].children[0], marko.inline.RawText):
            print(f"Unexpected item in changelog: {child.children[0].children[0]}")
            raise SystemExit(1)
        list_text = child.children[0].children[0].children
        if list_text.startswith("[ ]"):
            continue
        elif list_text.startswith("[x]"):
            change_type = list_text.removeprefix("[x]").strip()
            if change_type.casefold() not in VALID_BUMP_OPTIONS:
                print(f"Unexpected change type in changelog: {change_type}")
                raise SystemExit(1)
            selected.append(change_type.casefold())
        else:
            print(f"Unexpected item in changelog: {list_text}")
            raise SystemExit(1)

    if len(selected) > 1:
        print("You can only select one type of change.")
        raise SystemExit(1)
    if not selected:
        print("You must select a type of change.")
        raise SystemExit(1)
    return selected[0]


def _validate_entries(items: list[marko.element.Element], section: str) -> None:
    seen_headers: set[str] = set()
    if not items:
        print(f"No entries found in the {section} section of the changelog.")
        raise SystemExit(1)
    if (
        isinstance(items[0], marko.block.Paragraph)
        and isinstance(items[0].children[0], marko.inline.RawText)
        and items[0].children[0].children == "No changes."
    ):
        return
    last_header: str = ""
    for item in items:
        if isinstance(item, marko.block.Heading):
            if last_header:
                print(f"Expected a list of changes after the {last_header} header.")
                raise SystemExit(1)
            elif item.level != 3:
                print(f"Unexpected header level in changelog: {item}. Should be level 3.")
                raise SystemExit(1)
            elif not isinstance(item.children[0], marko.inline.RawText):
                print(f"Unexpected header in changelog: {item}.")
                raise SystemExit(1)
            header_text = item.children[0].children
            if header_text not in VALID_CHANGELOG_HEADERS:
                print(f"Unexpected header in changelog: {header_text}.")
                raise SystemExit(1)
            if header_text in seen_headers:
                print(f"Duplicate header in changelog: {header_text}.")
                raise SystemExit(1)
            seen_headers.add(header_text)
            last_header = header_text
        elif isinstance(item, marko.block.List):
            if not last_header:
                print("Expected a header before the list of changes.")
                raise SystemExit(1)
            last_header = ""
        else:
            print(f"Unexpected item in changelog: {item}.")
            raise SystemExit(1)


# This is just for demo purposes, to test the secret plugin in the Toolkit CLI
import_app = typer.Typer(
    pretty_exceptions_short=False, pretty_exceptions_show_locals=False, pretty_exceptions_enable=False
)


@import_app.command("cdf")
def cdf(
    ctx: typer.Context,
) -> None:
    """Import resources into Cognite Data Fusion."""
    print("Ran CDF Import Command")


CDF_TK_PLUGIN = {
    "bump": app,
    "import": import_app,
}

if __name__ == "__main__":
    app()
