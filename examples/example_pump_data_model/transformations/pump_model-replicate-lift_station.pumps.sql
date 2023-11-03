select
  concat(cast(`parent` as STRING), ':', cast(`externalId` as STRING)) as externalId,
  node_reference('cdfTemplate', cast(`parent` as STRING)) as startNode,
  node_reference('cdfTemplate', cast(`externalId` as STRING)) as endNode
from
  cdf_data_models("cdfTemplate", "AssetHierarchy", "1", "Asset")
where
  startswith(name, 'Pump')
