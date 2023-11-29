select 
cast(`externalId` as STRING) as externalId, 
cast(`isCompleted` as BOOLEAN) as isCompleted, 
cast(`plannedStart` as TIMESTAMP) as plannedStart, 
cast(`isSafetyCritical` as BOOLEAN) as isSafetyCritical, 
cast(`workPackageNumber` as STRING) as workPackageNumber, 
cast(`endTime` as TIMESTAMP) as endTime, 
cast(`status` as STRING) as status, 
cast(`durationHours` as INT) as durationHours, 
cast(`workOrderNumber` as STRING) as workOrderNumber, 
cast(`title` as STRING) as title, 
cast(`percentageProgress` as INT) as percentageProgress, 
cast(`startTime` as TIMESTAMP) as startTime, 
cast(`actualHours` as INT) as actualHours, 
cast(`description` as STRING) as description, 
cast(`isCancelled` as BOOLEAN) as isCancelled, 
cast(`isActive` as BOOLEAN) as isActive, 
cast(`priorityDescription` as STRING) as priorityDescription, 
cast(`dueDate` as TIMESTAMP) as dueDate, 
cast(`createdDate` as TIMESTAMP) as createdDate, 
cast(`programNumber` as STRING) as programNumber 
from `{{workorders_raw_db}}`.`workorders`;
