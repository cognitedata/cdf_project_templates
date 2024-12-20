from collections.abc import Iterable
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from _pytest.mark import ParameterSet
from _pytest.monkeypatch import MonkeyPatch
from cognite.client.data_classes import FileMetadataWrite, FileMetadataWriteList

from cognite_toolkit._cdf_tk.loaders import FileMetadataLoader
from cognite_toolkit._cdf_tk.utils import CDFToolConfig
from tests.test_unit.approval_client import ApprovalToolkitClient
from tests.test_unit.approval_client.client import LookUpAPIMock


def file_metadata_config_cases() -> Iterable[ParameterSet]:
    yield pytest.param(
        """externalId: sharepointABC
name: A file.txt
dataSetExternalId: ds_files
source: sharepointABC
""",
        ["1.A file.txt"],
        FileMetadataWriteList(
            [
                FileMetadataWrite(
                    external_id="sharepointABC",
                    source="sharepointABC",
                    name="A file.txt",
                    data_set_id=LookUpAPIMock._create_id("ds_files"),
                )
            ]
        ),
        id="Single file as mapping",
    )
    yield pytest.param(
        """- externalId: sharepointABC
  name: A file.txt
  dataSetExternalId: ds_files
  source: sharepointABC
- externalId: sharepointABC2
  name: Another file.txt
  dataSetExternalId: ds_files
  source: sharepointABC
""",
        ["1.A file.txt", "1.Another file.txt"],
        FileMetadataWriteList(
            [
                FileMetadataWrite(
                    external_id="sharepointABC",
                    source="sharepointABC",
                    name="A file.txt",
                    data_set_id=LookUpAPIMock._create_id("ds_files"),
                ),
                FileMetadataWrite(
                    external_id="sharepointABC2",
                    source="sharepointABC",
                    name="Another file.txt",
                    data_set_id=LookUpAPIMock._create_id("ds_files"),
                ),
            ]
        ),
        id="Multiple files as array",
    )


class TestLoadResources:
    @pytest.mark.parametrize("yaml_content, files, expected", list(file_metadata_config_cases()))
    def test_load_resources(
        self,
        yaml_content: str,
        files: list[str],
        expected: FileMetadataWriteList,
        toolkit_client_approval: ApprovalToolkitClient,
        monkeypatch: MonkeyPatch,
    ) -> None:
        loader = FileMetadataLoader(toolkit_client_approval.client, None)
        filepath = MagicMock(spec=Path)
        filepath.read_text.return_value = yaml_content
        filepath.parent.glob.return_value = [Path(f) for f in files]
        cdf_tool = CDFToolConfig(skip_initialization=True)
        resources = loader.load_resource_file(filepath, cdf_tool)

        assert resources.dump() == expected.dump()

    @staticmethod
    def always_existing_path(*_) -> Path:
        path = MagicMock(spec=Path)
        path.exists.return_value = True
        return path
