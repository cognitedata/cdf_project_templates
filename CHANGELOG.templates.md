# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Changes are grouped as follows:

- `Added` for new features.
- `Changed` for changes in existing functionality.
- `Deprecated` for soon-to-be removed features.
- `Improved` for transparent changes, e.g. better performance.
- `Removed` for now removed features.
- `Fixed` for any bug fixes.
- `Security` in case of vulnerabilities.

## TBD

### Added

- The (alpha) scene data model which is used for storing 3D scenes

## [0.4.9] - 2025-02-20

No changes to templates.

## [0.4.8] - 2025-02-14

### Fixed

- The annotation containers in the `models/cdf_cdm_extension_full` and `models/cdf_process_industry_extension_full`
  modules have now correctly set the `usedFor` to `edge`. This caused a 409 error when deploying these modules.

## [0.4.7] - 2025-02-13

No changes to templates.

## [0.4.6] - 2025-02-10

No changes to templates.

## [0.4.5] - 2025-02-06

No changes to templates.

## [0.4.4] - 2025-02-05

No changes to templates.

## [0.4.3] - 2025-02-04

No changes to templates.

## [0.4.2] - 2025-02-04

No changes to templates.

## [0.4.1] - 2025-02-03

No changes to templates.

## [0.4.0] - 2025-01-31

No changes to templates.

## [0.3.30] - 2025-01-31

No changes to templates.

## [0.3.29] - 2025-01-27

No changes to templates.

## [0.3.28] - 2025-01-21

No changes to templates.

## [0.3.27] - 2025-01-20

### Fixed

- The `inrobot` module no longer raises a `ResourceUpdateError/ResourceCreateError` when running
  `cdf deploy`.

## [0.3.26] - 2025-01-16

No changes to templates.

## [0.3.25] - 2025-01-10

No changes to templates.

## [0.3.24] - 2025-01-06

### Fixed

- Renamed non-toolkit Function config files for `bootcamp` module.

## [0.3.23] - 2024-12-13

No changes to templates.

## [0.3.22] - 2024-12-12

No changes to templates.

## [0.3.21] - 2024-12-11

No changes to templates.

## [0.3.20] - 2024-12-10

No changes to templates.

## [0.3.19] - 2024-12-09

No changes to templates.

## [0.3.18] - 2024-12-03

No changes to templates.

## [0.3.17] - 2024-12-02

### Fixed

- The user group in the `QuickStart` package now has capabilities to inspect the RAW tables and
  extraction pipelines.
- Missing table `diagramParsing` in the `QuickStart` is now created.
- Bug in the SQL transformation of the `cdf_sharepoint` modules.

## [0.3.16] - 2024-11-28

### Fixed

- Bug in the `QuickStart` packages causing the P&ID contextualization to fail.

## [0.3.15] - 2024-11-28

No changes to templates.

## [0.3.14] - 2024-11-27

No changes to templates.

## [0.3.13] - 2024-11-26

## Changed

- The modules `cdf_idm_extension` and `cdf_idm_extension_full` are renamed to `cdf_process_industry_extension` and
  `cdf_process_industry_extension_full` respectively.
- The Source System data pipelines now requires `cdf_process_industry_extension` and writes to the extension model
  instead of the Core model.
- The modules in Source System, Contextualization, and Industrial Tool packages now use shared resources
  in `cdf_common`.

## [0.3.12] - 2024-11-21

### Added

- Added new modules `cdf_entity_matching` in the `contextualization` package. This contains a pipeline for
  doing entity matching based on the Cognite Core model.

### Fixed

- Bug in extension models in the `models` package. The `through` field was not correctly set. In addition,
  simplified the `CogniteCore` and `CogniteProcessIndustries` minimum extension models further. Finally, all
  containers were duplicated. This has been fixed.
- Bug in `cdf_sap_assets` causing the asset transformation to fail to a READ access error.

## [0.3.11] - 2024-11-19

No changes to templates.

## [0.3.10] - 2024-11-14

No changes to templates.

## [0.3.9] - 2024-11-12

No changes to templates.

## [0.3.8] - 2024-11-11

### Added

- The `sourcesystem` modules now has example data.

### Fixed

- Ensure uniqueness of joins in the transformations of the `cdf_connection_sql` module.

## [0.3.7] - 2024-11-06

No changes to templates.

## [0.3.6] - 2024-11-04

### Added

- The `modules init` wizard provides an option for an empty, custom module scaffolding.

### Changed

- Module Bootcamp removed schedules and file from ice_cream_api
- Module Bootcamp removed function definitions from ice_cream_api

### Fixed

- Removed unused variables from default InRobot configuration.
- Added missing transformation `asset to asset` in `cdf_sap_asset` module.
- Module Bootcamp OEE function now correctly calculates current OEE time series

## [0.3.5] - 2024-10-24

### Added

- Added new module `cdf_sharepoint` to the `sourcesystem` package.
- Added new package `industrial_tool` for data exploration and analytics with modules
  - `cdf_search` for setting up location filters
- Added new package `contextualization` with modules
  - `cdf_p_and_id_parser`
  - `cdf_timeseries_equipment_sql`

## [0.3.4] - 2024-10-18

- Added new package `sourcesystem` with modules
  - `sap_asset`
  - `sap_events`
  - `pi`
- Added new modules for extension of `CogniteProcessIndustries` model.
  Full and minimum extension templates in `quickstart` and `example` packages.

## [0.3.3] - 2024-10-15

### Changed

- The `cdf_location_filter_example` has been split into two separate modules: `cdf_location_asset_centric`,
  and `cdf_location_datamodel_based`. This is to better demonstrate the different ways to filter locations in CDF.

### Removed

- Module `bootcamp` data_sets and raw modules removed from `ice_cream_api` and `oee`
- Module `bootcamp` default config removed from `ice_cream_api`

### Fixed

- Added missing default variable `scheduleHourly` to `InField` module `cdf_infield_common`.
- The property `featureConfiguration` is in the `APM_Config` is now correctly a blob and not a list of blobs. This
  impacted the InRobot and InField options in `cdf modules init` and `cdf modules add`.
- Module `bootcamp` error in calculation of site names for `ooe_timeseries`
- Module `bootcamp` comment for `icapi_extractors_source_id` incorrect.
- Added missing dataset `ds_asset_oid` to `cdf_data_pipeline_3d_valhall` example.
- Added missing RAW table `asset_oid_workmate` to `cdf_data_pipeline_asset_valhall` example.
- Added missing RAW table `files_oid_fileshare` and dataset `ds_asset_oid` to `cdf_data_pipeline_files_valhall` example.
- Added missing dataset `ds_asset_oid` to `cdf_data_pipeline_timeseries_valhall` example.

## [0.3.2] - 2024-10-11

### Fixed

- Added missing views, containers, and spaces to the `cdf_apm_base` module.

## [0.3.1] - 2024-10-09

No changes to templates.

## [0.3.0] - 2024-10-08

## Added

- CogniteCore full and minimum extension templates in `quickstart` and `example` packages.

## [0.3.0b5] - 2024-10-03

No changes to templates.

## [0.3.0b4] - 2024-09-30

### Fixed

- Module `bootcamp` error in calculation of `quality` and `performance` in the `oee_timeseries` function.

## [0.3.0b3] - 2024-09-25

No changes to templates.

## [0.3.0b2] - 2024-09-24

No changes to templates.

## [0.3.0b1] - 2024-09-23

No changes to templates.

## [0.3.0a7] - 2024-09-23

No changes to templates.

## [0.3.0a6] - 2024-09-20

Added `bootcamp` modules `ice_cream_api` and `oee`.

## [0.3.0a5] - 2024-09-18

No changes to templates.

## [0.3.0a4] - 2024-09-13

No changes to templates.

## [0.3.0a3] - 2024-09-11

No changes to templates.

## [0.3.0a2] - 2024-09-10

No changes to templates.

## [0.3.0a1] - 2024-09-10

No changes to templates.

## [0.2.20] - 2024-08-31

## Fixed

- Added missing `common_function_code` to the `cognite_modules/inrobot/cdf_inrobot_common` module.

## [0.2.19] - 2024-08-26

No changes to templates.

## [0.2.18] - 2024-08-22

### Added

- New modules `cognite_modules/inrobot`.

### Fixed

- In the module `cdf_apm_simple_data_model`. The version of the view `6.WorkOrder.view` was incorrect.

## [0.2.17] - 2024-07-26

No changes to templates.

## [0.2.16] - 2024-07-23

No changes to templates.

## [0.2.15] - 2024-07-22

### Added

- Module `cognite_modules/example/cdf_data_pipeline_3d_valhall` 3D contextualization
  example pipeline. Reading 3D nodes and matching to asset hierarchy

## [0.2.14] - 2024-07-15

No changes to templates.

## [0.2.13] - 2024-07-10

No changes to templates.

## [0.2.12] - 2024-07-08

No changes to templates.

## [0.2.11] - 2024-07-05

No changes to templates.

## [0.2.10] - 2024-07-03

No changes to templates.

## [0.2.9] - 2024-07-02

No changes to templates.

## [0.2.8] - 2024-07-01

### Fixed

- Added missing dependency to `requirements.txt` in `cognite_modules/examples/cdf_functions_dummy`.

## [0.2.7] - 2024-06-28

No changes to templates.

## [0.2.6] - 2024-06-26

No changes to templates.

## [0.2.5] - 2024-06-25

No changes to templates.

## [0.2.4] - 2024-06-24

No changes to templates.

## [0.2.3] - 2024-06-20

No changes to templates.

## [0.2.2] - 2024-06-18

No changes to templates.

## [0.2.1] - 2024-06-17

No changes to templates.

## [0.2.0] - 2024-06-10

No changes to templates.

## [0.2.0b4] - 2024-06-06

### Added

- Extended `cognite_modules/examples/my_example_module` with a `TransformationNotification` case.

## [0.2.0b3] - 2024-06-04

### Added

- Extended `cognite_modules/examples/my_example_module` with a `Label` case.

## [0.2.0b2] - 2024-06-03

No changes to templates.

## [0.2.0b1] - 2024-05-20

### Fixed

- Removed illegal characters from `DatapointSubscriptoin` description in
  `cognite_modules/examples/my_example_module`.

## [0.2.0a5] - 2024-05-28

### Added

- Function used to schedule & trigger workflow
- Extended `cognite_modules/examples/my_example_module` with a `SecurityCategory` case.
- Extended `cognite_modules/examples/my_example_module` with a `DatapointSubscription` case.

### Removed

- The parameter `fileId` is removed from all `function` configurations
  (`cdf_functions_dummy`, `cdf_data_pipeline_files_valhall`, `cdf_data_pipeline_timeseries_valhall`,
  and `my_example_module`) as it is no longer required.
- In all modules with an `extraction_pipelines` resource, removed `dataSetExternalId` and `name` from all
  ExtractionPipelineConfigs as this is not used and thus only causes confusion.
- In all modules with a `function`, renamed `externalIdDataSet` to `dataSetExternalId` to be consistent with the
  naming convention used in the Cognite API.
- In module `my_example_module`, removed `interval` and `isPaused` from the Transformation as these are not used.
  These parameters should only be present in a TransformationSchedule.

### Changed

- Removed schedule from annotation function `context:files:oid:fileshare:annotation`
- Add use of `map_concat`in transformation `files_oid_fileshare_file_metadata` to keep existing files metadata.
- Switched to using `file.uploaded_time` instead of `file.last_updated_time` since update time
  potentially is updated every time the transformation runs, and don't require a reannotation.

## [0.2.0a4] - 2024-04-29

### Added

- Workflow with a Function and a Transformation to the cdf_data_pipeline_files_valhall example
  
### Changed

- The `cdf_functions_dummy` module now includes codes from the former `common_function_code` directory.

### Fixed

- In `example_pump_data_model`, in the `Pump.view.yaml` the property `source` used `external_id` instead of
  `externalId`.

## [0.2.0a3] - 2024-04-23

### Fixed

- Align tag name in asset hierarchy between the 2 example transformations
- Added default root asset ID to documents for initial annotation
- Aligned use of asset external ID across contextualization functions
- Annotation logic with local time stamp for when to reprocess P&ID files
- Input to P&ID annotation based on list of synonyms for tag
- Updated module `apm_simple_data_model` for `cognite-sdk>=7.37`, i.e., container properties
  of type `direct` have now `list: false` explicitly set.

### Added

- Added Transformation for WorkOrder and WorkItems to OID testdata template
- Added Workflow with a Function and a Transformation to the custom module example

## [0.2.0a2] - 2024-04-03

No changes to templates.

## [0.2.0a1] - 2024-03-20

- Added functionality for wildcard detection of tags in P&ID
- Added functionality for multiple overlapping annotation to same tag - related to wildcards

## [0.1.2] - 2024-03-18

No changes to templates.

## [0.1.1] - 2024-03-11

No changes to templates.

### Added

- Module `cognite_modules/example/cdf_data_pipeline_timeseries_valhall` opcua / time series
  extractor pipeline, CDF function running contextualization of time series to assets.

## [0.1.0] - 2024-02-29

### Changed

- In the `infield` section, the `infield_apm_app_config.node.yaml` was moved from `cdf_infield_location` to `cdf_infield_common`
  module. In addition, the module `cdf_infield_second_location` was added to the `infield` section. This is to demonstrate
  how multiple locations in Infield should be handled.
- In the `cdf_data_pipeline_files_valhall` example, the Cognite Function `fu_context_files_oid_fileshare_annotation`
  has been renamed to `fn_context_files_oid_fileshare_annotation`. It has also been split into several files, to be
  easier to understand. It has also been changed to using `print`s (over `logging`), as that is unfortunately a hard
  requirement from the API.

### Added

- In the `cdf_data_pipeline_files_valhall` example, the `README.md` file has been updated with instructions on how to
  run and test Cognite Functions locally.

## [0.1.0b9] - 2024-02-20

### Changed

- In cdf_oid_example_data, the filename prefixes have been removed from the filenames and instead the new name template
  functionality is used to prefix the filenames as part of the build step.

### Fixed

- Replaced `shared: True` to `isPublic: True` and `action: upsert` to `conflictMode: upsert` in all
  transformation configurations to match the CDF API specification.

## [0.1.0b8] - 2024-02-14

### Added

- Added a new module `cognite_modules/example/cdf_data_pipeline_files_valhall` file extractor pipeline, transformation
  and CDF function running annotation on P&ID documents.

### Fixed

- Added missing cognite-sdk dependency to the common_functions_code.

## [0.1.0b7] - 2024-02-07

- Added a new module `cognite_modules/example/cdf_functions_dummy` that shows how to create functions and deploy them.
- Added common function code examples in `common_function_code/` directory as well as an
  example of how to use the common code in the `cognite_modules/example/cdf_functions_dummy/fn_test2` and
  `fn_example_repeater` functions.

### Fixed

- In module `cognite_modules/example/example_pump_asset_hierarchy`, in the transformation
  `pump_asset_hierarchy_load-collections_pump.sql` the value `pump_assets` was hardcoded instead of using the variable
  `{{raw_db}}`. This has been fixed.

## [0.1.0b6] - 2024-01-26

No changes to templates.

## [0.1.0b5] - 2024-01-11

No changes to templates.

## [0.1.0b4] - 2024-01-08

No changes to templates.

## [0.1.0b3] - 2024-01-02

No changes to templates.

## [0.1.0b2] - 2023-12-17

### Fixed

- In the package `example_pump` ensure all transformations are prefixed with `tr_`.

## [0.1.0b1] - 2023-12-15

### Added

- Explicitly define model `space` in `experimental/cdf_asset_source_model/` and `experimental/example_pump_model/`.
- The module `my_example_module` has been added to the `custom_modules` folder.
- Added globally defined schedule variables that can be used across all modules.
- A complete example of an Asset data pipeline in `examples/cdf_asset_data_pipeline/` shows how to configure an
  Extractor, monitor the status of the Extraction Pipeline, and load the data into the asset hierarchy using Transformations.
- DataSet to all example modules: `cdf_apm_simple_data_model`, `cdf_asset_source_model`, `cdf_oid_example_data`,
  `example_pump_data_model`, `example_pump_asset_hierarchy`.

### Changed

- **BREAKING** All externalIds and names have been changed to follow the naming conventions for resources
  in `examples/cdf_oid_example_data`, `examples/cdf_apm_simple_data_model`, `modules/cdf_apm_base`,
  `modules/cdf_infield_common`, and `modules/cdf_infield_location`.
- **BREAKING** Transformation Schedules broken out into separate files, following naming convention `<transformation_name>.schedule.yaml`.
- All cognite templates have been moved into `cognite_templates` folder, while `local_templates` is renamed to `custom_templates`.
- Move cdf_apm_base into separate folder.
- The file `local.yaml` has been renamed `environments.yaml` to better reflect its purpose.
- Removed demo `sourceId` from `cdf_infield_location` module.
- Changed the isPaused flag to use a module-level variable instead of hardcoded in `cdf_apm_simple_data_model`.
- Combined the child and parent transformations `sync_assets_from_hierarchy_to_apm` in `cdf_infield_location`.
  This has the benefit of not having to wait for the parent transformation to finish before starting the child transformation,
  thus no longer a dependency between the two transformations.

### Fixed

- Removed transformation identity provider variables from modules and reused the global cicd_ prefixed ones.
- Ensure all transformations in `cognite_modules` are prefixed with `tr_` and all spaces are prefixed with `sp_`.

## [0.1.0a3] - 2023-11-29

### Changed

- Remove unused template_version variable from groups and use of group metadata.
- Split up cdf_oid_example_data into data sets and RAW databases per source system.

### Fixed

- Add space yaml files for existing data models when explicit space definition was introduced.
- Fix use of integer value in version for data models.
- Fix wrong reference to `apm_simple` in `examples/cdf_apm_simple_data_model` and `modules/cdf_infield_location`.
- Exemplify use of a single config yaml file for multiple file resources in `examples/cdf_oid_example_data/files/files.yaml`.

## [0.1.0a2] - 2023-11-23

### Changed

- Changed format of infield external_ids to be more readable, moving `_dataset` (ds) and `_space` to the beginning of
  the external_id.
- `examples/cdf_apm_simple/raw` and `examples/example_dump_asst_hierarchy/raw` now explicitly
  defines database and table name in `.yaml` files for each table.
- Added `data_set` to `examples/example_dump_asst_hierarchy/`, which was implicitly defined in
  before.

### Fixed

- cdf_infield_common module and the auth applications-configuration.yaml did not load group source id
   correctly due to source_id being used instead of sourceId. This is now fixed.

## [0.1.0a1] - 2023-11-21

Initial release
