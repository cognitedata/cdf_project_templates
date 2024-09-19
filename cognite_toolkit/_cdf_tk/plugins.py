from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from cognite_toolkit._cdf_tk.cdf_toml import CDFToml
from cognite_toolkit._cdf_tk.constants import clean_name


@dataclass
class Plugin:
    name: str
    description: str

    @staticmethod
    def is_enabled(plugin: Plugin) -> bool:
        return CDFToml.load().plugins.get(clean_name(plugin.name), False)


class Plugins(Enum):
    dump = Plugin("dump_assets", "plugin for Dump command to retrieve Asset resources from CDF")
    graphql = Plugin("graphql", "GraphQL plugin")

    @staticmethod
    def list() -> dict[str, bool]:
        res = {plugin.name: Plugin.is_enabled(plugin.value) for plugin in Plugins}
        return res
