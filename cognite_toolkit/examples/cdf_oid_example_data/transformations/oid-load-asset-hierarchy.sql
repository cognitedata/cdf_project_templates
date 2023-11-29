select
  cast(`externalId` as STRING) as externalId,
  cast(`externalId` as STRING) as name,
  cast(`description` as STRING) as description,
  cast(`sourceDb` as STRING) as source,
  cast(`parentExternalId` as STRING) as parentExternalId
from
  `{{source_assets}}_assets`.`assets`;
