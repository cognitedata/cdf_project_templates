from __future__ import annotations

from typing import Literal, cast

from cognite.client import ClientConfig, CogniteClient

from .api.dml import DMLAPI
from .api.location_filters import LocationFiltersAPI
from .api.lookup import LookUpGroup
from .api.robotics import RoboticsAPI
from .api.verify import VerifyAPI


class ToolkitClientConfig(ClientConfig):
    @property
    def cloud_provider(self) -> Literal["azure", "aws", "gcp", "unknown"]:
        cdf_cluster = self.cdf_cluster
        if cdf_cluster is None:
            return "unknown"
        elif cdf_cluster.startswith("az-") or cdf_cluster in {"azure-dev", "bluefield", "westeurope-1"}:
            return "azure"
        elif cdf_cluster.startswith("aws-") or cdf_cluster in {"orangefield"}:
            return "aws"
        elif cdf_cluster.startswith("gc-") or cdf_cluster in {
            "greenfield",
            "asia-northeast1-1",
            "cognitedata-development",
            "cognitedata-production",
        }:
            return "gcp"
        else:
            return "unknown"

    @property
    def is_private_link(self) -> bool:
        if "cognitedata.com" not in self.base_url:
            return False
        subdomain = self.base_url.split("cognitedata.com", maxsplit=1)[0]
        return "plink" in subdomain


class ToolkitClient(CogniteClient):
    def __init__(self, config: ToolkitClientConfig | None = None) -> None:
        super().__init__(config=config)
        self.location_filters = LocationFiltersAPI(self._config, self._API_VERSION, self)
        self.robotics = RoboticsAPI(self._config, self._API_VERSION, self)
        self.dml = DMLAPI(self._config, self._API_VERSION, self)
        self.verify = VerifyAPI(self._config, self._API_VERSION, self)
        self.lookup = LookUpGroup(self._config, self._API_VERSION, self)

    @property
    def config(self) -> ToolkitClientConfig:
        """Returns a config object containing the configuration for the current client.

        Returns:
            ToolkitClientConfig: The configuration object.
        """
        return cast(ToolkitClientConfig, self._config)
