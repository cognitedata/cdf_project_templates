from abc import ABC
from typing import Any, Literal

from cognite.client import CogniteClient
from cognite.client.data_classes._base import (
    CogniteResourceList,
    ExternalIDTransformerMixin,
    WriteableCogniteResource,
    WriteableCogniteResourceList,
)


class _StreamlitCore(WriteableCogniteResource["StreamlitWrite"], ABC):
    def __init__(
        self,
        external_id: str,
        name: str,
        creator: str,
        entrypoint: str,
        description: str | None = None,
        published: bool = False,
        theme: Literal["Light", "Dark"] = "Light",
        thumbnail: str | None = None,
        data_set_id: int | None = None,
    ) -> None:
        self.external_id = external_id
        self.name = name
        self.creator = creator
        self.entrypoint = entrypoint
        self.description = description
        self.published = published
        self.theme = theme
        self.thumbnail = thumbnail
        self.data_set_id = data_set_id


class StreamlitWrite(_StreamlitCore):
    def as_write(self) -> "StreamlitWrite":
        return self

    @classmethod
    def _load(cls, resource: dict[str, Any], cognite_client: CogniteClient | None = None) -> "StreamlitWrite":
        args = dict(
            external_id=resource["externalId"],
            name=resource["name"],
            creator=resource["creator"],
            entrypoint=resource["entrypoint"],
            description=resource.get("description"),
            thumbnail=resource.get("thumbnail"),
            data_set_id=resource.get("dataSetId"),
        )
        # Trick to avoid specifying defaults twice
        for key in ["published", "theme"]:
            if key in resource:
                args[key] = resource[key]
        return cls(**args)


class Streamlit(_StreamlitCore):
    def __init__(
        self,
        external_id: str,
        name: str,
        creator: str,
        entrypoint: str,
        created_time: int,
        last_updated_time: int,
        description: str | None = None,
        published: bool = False,
        theme: Literal["Light", "Dark"] = "Light",
        thumbnail: str | None = None,
        data_set_id: int | None = None,
    ) -> None:
        super().__init__(external_id, name, creator, entrypoint, description, published, theme, thumbnail, data_set_id)
        self.created_time = created_time
        self.last_updated_time = last_updated_time

    @classmethod
    def _load(cls, resource: dict[str, Any], cognite_client: CogniteClient | None = None) -> "Streamlit":
        args = dict(
            external_id=resource["externalId"],
            name=resource["name"],
            creator=resource["creator"],
            entrypoint=resource["entrypoint"],
            created_time=resource["createdTime"],
            last_updated_time=resource["lastUpdatedTime"],
            description=resource.get("description"),
            thumbnail=resource.get("thumbnail"),
            data_set_id=resource.get("dataSetId"),
        )
        # Trick to avoid specifying defaults twice
        for key in ["published", "theme"]:
            if key in resource:
                args[key] = resource[key]
        return cls(**args)

    def as_write(self) -> StreamlitWrite:
        return StreamlitWrite(
            external_id=self.external_id,
            name=self.name,
            creator=self.creator,
            entrypoint=self.entrypoint,
            description=self.description,
            published=self.published,
            theme=self.theme,
            thumbnail=self.thumbnail,
            data_set_id=self.data_set_id,
        )


class StreamlitWriteList(CogniteResourceList[StreamlitWrite], ExternalIDTransformerMixin):
    _RESOURCE = StreamlitWrite


class StreamlitList(WriteableCogniteResourceList[StreamlitWrite, Streamlit], ExternalIDTransformerMixin):
    _RESOURCE = Streamlit

    def as_write(self) -> StreamlitWriteList:
        return StreamlitWriteList([item.as_write() for item in self])
