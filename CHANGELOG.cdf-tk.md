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

### Fixed

- Deploying multiple views with reverse direct relation dependencies no longer raises a `ResourceCreationError`.

## [0.4.9] - 2025-02-20

### Added

- Support for `auth0` as the provider when running `cdf auth init`.
- [alpha feature] When the flag `strict-validation` is set to `true` in the `cdf.toml` file, the Toolkit will
  no longer use its own authentication as a fallback when deploying WorkflowTriggers and FunctionSchedules in projects
  where `validation-type` is set to anything other than `dev`. This will be the default behavior from version `0.5.0`.
- [alpha feature] When the flag `credentials-hash` is set to `true` in the `cdf.toml` file, the Toolkit will hash
  the credentials of Transformations (if present), FunctionSchedules, and WorkflowTriggers before deploying them. This
  will be used to detect if the credentials have been changed when running `cdf deploy`.

### Improved

- You will get a warning if a WorkflowTrigger or a FunctionSchedule is missing authentication, and the Toolkit
  authentication is used.

### Changed

- In the `config.[env].yaml` file, the `type` key is renamed to `validation-type` in the `environment` section. This is
  to make it more clear that this key is used for validation. The `type` key is still supported for backward
  compatibility.

## [0.4.8] - 2025-02-14

### Fixed

- The Toolkit no longer tries to update a data modeling container that does not have the `usedFor` field set.
- The Toolkit no longer hides `409` errors when failing to create a resource behind a low severity warning.

## Improved

- If the `cdf deploy` command fails to deploy multiple `Group`s due to `Failed to buffer the request body` error, the Toolkit
  now retries to create the `Group`s one by one.

## [0.4.7] - 2025-02-13

### Added

- [alpha feature] New alpha command `cdf populate view`. You can populate a view with data from a local table
  using this command. To enable this feature, you need to set `populate = true` in the `alpha_flags` section of
  your `cdf.toml` file.

### Improved

- Improved flow for the `cdf auth init` command.

## [0.4.6] - 2025-02-10

### Fixed

- The `cdf purge space` no longer tries to delete nodes in other spaces.
- The `cdf purge space` now sorts node types topologically to delete them in the correct order.
- The `--hierarchy/-h` flag was missing from the `cdf dump timeseries` command. This is now fixed.
- The `cdf purge dataset` now accounts for the hierarchy when deleting assets.

## [0.4.5] - 2025-02-06

### Fixed

- Building a Group with a table scoped RAWAcl no longer complains about missing dependency `tables` if the
  `tables` keyword is used to specify the tables.
- When authentication with Toolkit, multiple `IDP_Scopes` are assumed to be separated by a comma in the environment
  variable `IDP_SCOPES`.

## [0.4.4] - 2025-02-05

### Fixed

- Deploying functions containing files that are not `utf-8` encoded no longer raises a `UnicodeDecodeError`.

## [0.4.3] - 2025-02-04

### Fixed

- Calling `cdf modules upgrade` will no longer raise `AmbiguousResourceFileError` error if you have a file named
  `my_file.File.yaml`.

## [0.4.2] - 2025-02-04

### Fixed

- An IndexError was reported when instances.nodes was an empty list. This is now fixed.
- Calling `cdf build` on a hosted extractor `Source` resource no longer produces unrelated
  `MissingRequiredParameterWarning`s.
- Reverting change from `0.3.29` that made the Toolkit update Groups by deleting then recreating. This was causing
  issues when sometimes the Group was not recreated. The Toolkit now updates by first creating the new Group and then
  deleting the old Group.
- Groups with a `rawAcl` that is table scoped no longer getr redeployed when they are not changed.

## [0.4.1] - 2025-02-03

### Added

- [alpha feature] The alpha flag `dump-extended` adds support for `cdf dump workflow/transformation/group/node` to the
  `dump` plugin command.

### Fixed

- The `cdf modules upgrade` no longer raises a `FileNotExists` when renaming files in an upgrade to `0.4.0`.
- The `cdf modules pull` command no longer raise a `NotImplementedError` for Groups with `members`.
- The `cdf modules pull` command no longer raise a `KeyError` if a variable is used as a key in a dictionary.
- Running `cdf deploy` for `Group` with `members` now only deploys the `Group` if it is new or has changed.

## [0.4.0] - 2025-01-31

### Added

- The `ado-pipeline` feature is no longer an alpha feature.
- The `cdf run workflow` feature is no longer an alpha feature.
- The resources `streamlit`, `edges`, `relationships`, `sequences rows` are no longer alpha features.
- The `cdf deploy --force-update` flag is no longer an alpha feature.
- The `cdf build --offline` flag is no longer an alpha feature.
- The `cdf modules pull` feature is no longer an alpha feature.

### Changed

- All `YAML` files now requires a `kind` in the files name to identify the resource type.
- Toolkit now hashes individual files in functions to check if they have changed. This is to get a better
  granularity when checking if a function has changed.

### Removed

- The plugin `cdf pull` has been removed and is now replaced by `cdf modules pull`.

### Fixed

- The `cdf purge dataset` now correctly falls back to internal IDs if external IDs are not found.
- Upserting nodes without a `source` does not raise an IndexError anymore.

## [0.3.30] - 2025-01-31

### Improved

- [alpha feature] The `cdf purge space` now automatically reduces the batch size when listing the nodes/edges to
  delete when getting a 408 timeout error.
- [alpha feature] The `cdf purge` now shows a spinner and updates the progress when deleting resources.

### Fixed

- Reverting the fix from `0.3.24` to read any csv dialect when uploading a `csv` file
  (RAW table, Datapoints, or Assets). Now, only the comma-separated dialect is supported. This is because the dialect
  inference performed too poorly and failed to read the data correctly in many cases.

## [0.3.29] - 2025-01-27

### Added

- Interactive selection mode if you don't provide a path or module name as argument to `cdf modules pull`.

### Improved

- Running `cdf deploy` and `cdf deploy --dry-run` now reports correctly delete + create for resources that do not
  support update. This is `Function`, `FunctionSchedule`, `Group`, and `SequenceRows`.
- [alpha feature] The `cdf purge space` now automatically reduces the batch size when deleting nodes when getting a
  408 timeout error.
- [alpha feature] The `cdf purge space` now tells which spaces needs to be purged first if the current space has
  dependencies. This happens when a node in one space is used as a node type in another space.

## [0.3.28] - 2025-01-21

### Fixed

- Variable replacement was too restrictive for environment variables. Previous behaviour to replace all
  environment variables has been restored except Extraction Pipeline Configs.
- Supporting non-ascii characters like æ,ø, å, ç, ã in built files  

## [0.3.27] - 2025-01-20

### Improved

- The `cdf dump asset` and `cdf dump timeseries` commands now always dump tables with
  the same columns in the same order.

### Fixed

- The `cdf build` no longer raises a `ToolkitFileNotFoundError` when building without a `config.[env].yaml` file.

## [0.3.26] - 2025-01-16

### Added

- [alpha feature] `cdf import transformation-cli` now has a new flag `--clean` to remove the
  source files after importing.

### Fixed

- All groups are now correctly deployed before resources that has authentication to them (`Transformation`,
  `'FunctionSchedule`, `WorkflowTrigger`).

### Changed

- Running `cdf auth init/verify` no longer automatically activates Cognite Functions on private link environments
  projects.

### Improved

- You now get a warning if you use the `$FILENAME` template incorrectly in the `CogniteFile`/`FileMetadata` resource.
- If a `{{ variable }}` replacement causes a `YAMLFormatError`, the Toolkit now gives you a hint on how to fix it.
- If you use a `dataSetId`, the Toolkit now gives you a hint to use `dataSetExternalId` instead.
- The Toolkit fallback to read any file as `utf-8` if it fails to read.
- The Toolkit no longer gives `UnusedParamterWarning` for `WorkflowVersion` using a `subworkflow` task.
- If a `Transformation`/`FunctionSchedule`/`WorkflowTrigger` fails to deploy due to environment variables missing,
  the Toolkit now gives a hint on how to fix it.
- [alpha feature] If you get a duplicated item due to using the `repeated-module` feature. The Toolkit now gives
  you a hint on how to fix it.

## [0.3.25] - 2025-01-10

### Added

- [alpha feature] Support for `SequenceRows` resources in the `classic` directory. Alpha flag `classic=True`.

### Fixed

- Deploying raw tables or datapoints from csv should no longer raise a `pandas.errors.ParserError`.

### Improved

- On Windows, commands such as `cdf modules list` were Toolkit needs to delete a temporary directory no longer
  raise an `PermissionError`, but instead has a gracefully fallback, and gives a warning if the fallback fails.

## [0.3.24] - 2025-01-06

### Added

- [alpha feature] Support for running `cdf build` without comparing against CDF project for missing dependencies
  with the flag `--offline`.
- [alpha feature] New subcommand `cdf modules pull` which pulls the configuration from the CDF project to the local
  modules directory.
- Support for property `dataModelingType` in `LocationFilter` resources.

### Fixed

- No more warning about missing `.env` file when running in `Google Cloud Build`.
- No more warning about missing `.env` file if all variables are set in the environment.
- When deploying a `Sequence` resource, Cognite Toolkit now replaces `dataSetExternalId` with `dataSetId`.
- Cognite Toolkit has improved resources that have server set default values that can lead to redeploy even when
  unchanged. This includes `Sequences`, `Containers`, `DataSets`, `Views`, `Nodes`, `Edges`, `ExtractionPipelines`,
  `CogniteFiles`, `HostedExtractorJobs`, `Relationships`, `RobotMaps`, and `WorkflowVersions`.
- When uploading a `csv` file (RAW table, Datapoints, or Assets) any CSV dialect is now supported.
- `LocationFilters` now parses the `version` key of `View` and `DataModel` correctly as a string.
- `LocationFilters` now converts an empty string of `dataSetExternalId` to `0` instead of ignoring it.
- On CDF deployed on Azure and AWS clouds, setting the `CPU` and `memory` of a CogniteFiles to lower than
  the required value no longer triggers a redeploy.
- Toolkit now looks up the `assetExternalId` in the `Sequence` resource when deploying.

## [0.3.23] - 2024-12-13

### Fixed

- Running `cdf auth init` now works for `CDF` as the `IDP` provider.

### Improved

- You can now set the `CDF_CLIENT_TIMEOUT` and `CDF_CLIENT_MAX_WORKERS` to control the timeout and the number of
  workers used by Toolkit when communicating with CDF.

## [0.3.22] - 2024-12-12

### Fixed

- Deploying `GraphQL` is no longer sensitive to the newlines inside of directives.
- Functions are no longer always redeployed if `indexUrl` or `extraIndexUrls` are set in the `Function` resource.

## [0.3.21] - 2024-12-11

### Fixed

- [alpha feature] Deploying `GraphQL` now correctly ignores end-of-line comments in the `.graphql` file.

## [0.3.20] - 2024-12-10

### Fixed

- `cdf deploy` no longer raises a `OSError` when deploying a `Transformation` with the SQL query in the `YAML` file.

## [0.3.19] - 2024-12-09

### Added

- [alpha feature] `cdf purge dataset` now supports purging resources with internal IDs.

### Fixed

- Replacing variables in an inline SQL query no longer removes the quotes around the variable.
- Running `cdf build` on an older module will no longer raise an `KeyError` if the `module.toml` does
  not have a `package` key.
- [alpha feature] `cdf purge dataset` no longer deletes `LocationFilters`
- [alpha feature] `GraphQL` resources with views that specify a `rawFilter` no longer raise an error when
  running `cdf deploy`.
- In the `cdf dump datamodel` command, properties that are overridden in a view are now correctly dumped.

### Changed

- [alpha feature] `cdf purge` now requires a confirmation before deleting resources.
- Building a `Transformation` will store the `.sql` file in the build directory instead of inlined in the
  resource YAML file.

### Improved

- Consistent display names of resources in output table of `cdf deploy` and `cdf clean`.

## [0.3.18] - 2024-12-03

### Fixed

- The `toolkit.demo` no longer fails du to wrong authentication variables.

## [0.3.17] - 2024-12-02

### Improved

- Toolkit will no longer give the warning `UserWarning: Unknown capability` in irrelevant cases.

### Added

- [alpha feature] Support `Edges` resources in the `data_models` directory.
- [alpha feature] Support `Event` resources in the `classic` directory.
- [alpha feature] Support `Relpationship` resources in the `classic` directory.
- [alpha feature] New command `cdf purge` this enables you to delete a `dataset` or `space` and all resources
  connected to it. This is useful if you want to clean up your CDF project.

### Fixed

- Using cdf for the identity provider no longer makes assumption about `IDP_CLIENT_SECRET` format.
- [alpha feature] Using `GraphQL` with an empty `@view` directive no longer raises
  an `Failed to parse GraphQL schema` error.

## [0.3.16] - 2024-11-28

No changes to cdf CLI.

## [0.3.15] - 2024-11-28

### Improved

- Better hint on activating plugins.

### Fixed

- Error message in Auth process shows correct variable names IDP_CLIENT_ID and IDP_CLIENT_SECRET.

## [0.3.14] - 2024-11-27

### Added

- Support for authentication with `CogIDP`

## [0.3.13] - 2024-11-26

### Fixed

- When using the commands `cdf deploy/clean`, the Toolkit no longer warns about unrelated resources
  that are not part of the deployment.
- When using `cdf deploy/clean/build, the Toolkit no longer warns about duplicated RAW databases.
- Changes to Streamlit app code were not deployed. This is now fixed.

## [0.3.12] - 2024-11-21

### Added

- [Alpha feature] Support for specifying list of variables under modules in `config.[env].yaml` file.
  This allows you to reuse the same module with different variables.
- [Alpha feature] GraphQL now supports the `preserveDml` parameter.

## [0.3.11] - 2024-11-19

### Fixed

- [Alpha feature] `cdf deploy` will no longer deploy `GraphQL` resources if they are not changed.
- In `cdf build` when loading `config.[env].yaml` the Toolkit now correctly prefers variables deeper, more
  specific, in the hierarchy over more general variables.
- [Alpha feature] `cdf build` will no longer copy content `YAML` files to the build directory.
- A bug caused the comparison with existing Tranformation Notifications to fail. This is now fixed.

### Improved

- The `cdf auth verify` no longer gives UserWarning is the user has unknown capabilities.

## [0.3.10] - 2024-11-14

### Fixed

- `cdf auth verify` no longer asks to update missing capabilities if there are no missing capabilities.
- `run function local` now works with functions that are importing adjacent modules.
- Environment variables were not replaced in Functions. This is now fixed.

### Improved

- `run function local` give a more informative error message if the function code cannot be imported.
- `run function local` now automatically loads environment variables from `.env` file. This is useful if you want to
  run the `run_check.py` script manually, for example, in debug mode with your IDE.

## [0.3.9] - 2024-11-12

### Added

- [alpha-feature] `--force-update` flag to `cdf deploy` to force update of all resources even if they are not changed.

## [0.3.8] - 2024-11-11

### Fixed

- Running `cdf run function local` no longer defaults to `IDP_CLIENT_SECRET` as the environment variable
  for the client secret. Instead, it will use the name specified in the function schedule configuration.
- `cdf auth verify` now asks the user to verify before updating the capabilities of the service principal.

## [0.3.7] - 2024-11-06

### Fixed

- Deploying RAW Tables/Databases no longer raises a `ToolkitRequiredValueError`.
- Deploying Asset given as `.csv`/`.parquet` is now supported again.
- Running `cdf deploy` no longer complains about `!keyvault` syntax in `ExtractionPipelineConfig` resources.

## [0.3.6] - 2024-11-04

### Fixed

- When running `cdf modules add`, the Toolkit removed trailing slash in the module path causing a
  build error. This is now fixed.
- When running `cdf build`, the Toolkit now stops if an error is encountered.
- `Asset` resources without `metadata` are no longer always redeployed when running `cdf deploy`,
  only if the local is different than the CDF configuration.
- Asset centric `LocationFilter`s are no longer always redeployed when running `cdf deploy`,
  only if the local is different than the CDF configuration.
- When deleting a `Function` the file is also removed if it exists.
- The `parentExternalId` in `LocationFilter` is now correctly replaced by `parentId` when running `cdf deploy`.

## [0.3.5] - 2024-10-24

No changes to cdf CLI.

## [0.3.4] - 2024-10-18

### Fixed

- Building a `WorkflowTrigger` will no longer complain that `authentication` is an unused variable.
- In resource `Group`, the following lookups are now done when running `cdf deploy/clean`:
  - `securityCategoriesAcl` `idscope` Security Names are now replaced by IDs.
  - `locationFiltersAcl` `idscope` external LocationFilter Ids are now replaced by IDs.
  - `timeSeriesAcl` `idscope` external TimeSeries IDs are now replaced by internal IDs.
  - `assetRootIdScope` external Asset IDs are now replaced by internal IDs.
- The resource `ResourceScopedGroup` is now correctly deployed after `RAW` `Tables` and `Databases`,
  `LocationFilters`, and `SecurityCategories` when running `cdf deploy`.

## [0.3.3] - 2024-10-15

### Fixed

- Running `cdf deploy --verbose` will no longer raise a `ToolkitRequiredValueError` when creating a new
  `FunctionSchedule`.
- If `--verbose` is set on any command and an error occurs, the Toolkit will now print a full traceback.

## [0.3.2] - 2024-10-11

### Fixed

- Deploying `Robotics` resource `Map` now accounts for the dependencies on `Frame` and `Location`.
- The Hosted Extractor Resources now respects the dependencies between the resources. For example, if a `Job`
  is referencing a `Destination`, the `Destination` will be deployed before the `Job`.
- Deploying a view-based `LocationFilter` no longer raises a `400` error.
- When running `cdf modules init` required modules are now created. Before, the Toolkit would skip creating
  the required modules.
- When running `cdf build`, in the `hosted_extractors` folder, the Toolkit will now give a warning if a `Destination`
  is referring toa non-existing dataset.
- Running `cdf modules upgrade` from version `0.3.0` and earlier will no longer fail if you
  have a view based `LocationFilter` in the `locations` folder.

## [0.3.1] - 2024-10-09

### Fixed

- Views based location filters no longer raises a TypeError when running `cdf clean` or `cdf deploy`.
- CogniteFiles are not recognized by `CogniteFile` and not `.CogniteFile` suffix in the `files` resource folder.

## [0.3.0] - 2024-10-08

### Added

- Support for `$FILENAME` expansion pattern for `CogniteFile` in the `files` folder.
- The `cdf repo init` command now creates a `GitHub` workflow for the Toolkit.

### Changed

- Running `cdf dump datamodels` now dumps containers and views into separate folders.

## [0.3.0b5] - 2024-10-03

### Added

- Added support for device code login flow.
- Support for uploading `CogniteFiles`.
- Docker release of the Toolkit.

### Changed

- When running `deploy --dry-run`, the Toolkit will not require write access to the CDF project.

### Fixed

- Uploading a file will no longer overwrite the `FileMetadata`.

## [0.3.0b4] - 2024-09-30

### Fixed

- Upgrading the `cognite-sdk` to `6.62.5` no longer raises an `ImportError` when running the `cdf` commands.

## [0.3.0b3] - 2024-09-25

### Added

- Support for hosted extractors mappings.

### Fixed

- [Feature Preview] Deploying `GraphQL` resources with `cdf deploy` no longers fails with a `ToolkitRequiredValueError`,
  if there is a comment in the `.graphql` file or a multiline `@import` directive is used. For example:

```graphql
type MyType
  @import(
    dataModel: {
      externalId: "MyModel"
      version: "v1"
      space: "MySpace"
    }
  ) {
  name: String!
}
```

## [0.3.0b2] - 2024-09-24

### Added

- If there are multiple `cognite_toolkit_service_principal`s, the `cdf auth verify` will offer to delete duplicates.

### Fixed

- Running `cdf auth verify` now prompts the user to create the `cognite_toolkit_service_principal` if it does not exist.
- In the `cdf build` command, version variables (`DataModel`, `View`, `Transformations`) are now always read as
  string and not integer. This ensures no false positive warnings for missing dependencies.
- In the `cdf deploy/clean` command, if a transformation is writing to a `DataModel` or a `View` the version is
  now always read as a string. Before if it was for example, `3_0_0` it would be read as `300` and cause
  the deployment of the transformation to fail.
- [Feature Preview] The `GraphQL` loader now includes the `.graphql` file in the `cdf build` command.

## [0.3.0b1] - 2024-09-23

### Added

- Dump for `Assets` and `TimeSeries` with `cdf dump asset` and `cdf dump timeseries` commands.
- Support for Hosted Extractors `Destination` and `Job`.
- Support for `CogniteFile`.

### Changed

- The Toolkit no longer gives a warning if it cannot import Cognite Function code when executing the `cdf build`
  command. This is to separate the build and deploying of artifacts from validating/debugging the function code.
  Validation of the function code is expected to be handled by `cdf run function local`.
- [BREAKING] The resource folder `timeseries_datapoints` is removed and `csv` and `parquet` files with
  datapoints are now expected to be in the `timeseries` folder.
- The dump of data models has changed interface, now the data model id is optionally given as positional instead
  of flags. If now data model is given, the user will be prompted to select one.

### Removed

- CSV files in the `timeseries_datapoins` folder with the string `timeshift_` in the index will no longer
  be timeshifted to today when running `cdf build`
- FileMetadata pattern `$FILENAME` is no longer supports prefix and suffix in the `name` parameter. This is to
  simplify the pattern.
- [BREAKING] The command `cdf describe` is removed. This functionality was not used and thus removing it to simplify
  the Toolkit and to focus on the core functionality.
- [BREAKING] Support for api parameters in `Node` resource is removed.
- Support for Python 3.9.

## [0.3.0a7] - 2024-09-23

### Fixed

- Running `cdf modules upgrade` no longer raises an error when upgrading from `0.2.x`.

## [0.3.0a6] - 2024-09-20

### Added

- Added flag `--modules`/`-m` to select which modules to build in the `cdf build` command.
- The `cdf build` command no longer requires `config.[env].yaml` to be present. If it is not present, the Toolkit
  will use the default values for the environment.

### Fixed

- If you removed `metadata` in any resource file, the Toolkit would not update this change in CDF. This is now fixed.

## [0.3.0a5] - 2024-09-18

### Added

- The new `cdf modules add` subcommand lets users add modules to an existing modules directory.
- [Feature Preview] Support for resource type Hosted Extractor Source. This should be in the `hosted_extractors` folder,
  and the file needs to be suffixed with `.Source.yaml`, for example, `my_eventhub.Source.yaml`.
  [CAUTION] The current implementation will always redeploy the source, even if it has not changed. This will be
  fixed in a future release.
- Added support for resource type `Sequence` in the `classic` folder.
- Added parameter `--selected` to the `cdf build` command to overwrite the `selected` in the `config.[env].yaml` file.
- Made the `config.[env].yaml` optional when running the `cdf build command.

### Changed

- [BREAKING] The command `cdf auth verify` has been split into `cdf auth init` and `cdf auth verify`. The `init` command
  is used to initialize the auth parameters, and the `verify` command is used to verify that required privileges are
  set. The `init` command will by default run the `verify` command after the initialization unless a `--no-verify`
  flag is set. In addition, the two commands have been reworked to be more user-friendly. They are now interactive
  (no longer requires a `--interactive` flag) and have no longer supports passing in a custom Group file. Instead,
  they are intended to only set up and verify a service principal for the Toolkit.

### Fixed

- The `config` value of a `ExtractionPipelineConfig` is now correctly parsed as a string. Before it was parsed as YAML,
  typically an object/dict, which caused loss of information. This is because
  `yaml.safe_dump(yaml.safe_load(config)) != config` as, for example, special YAML tags are lost.
- Deploying a `LocationFilter` with a data model no longer returns a `400` error.

### Removed

- The `--interactive` flag from the `cdf deploy` and `cdf clean` commands.
- The shared flags `--verbose`. This has been deprecated and has been replaced by `--verbose` on each individual
  command. For example, before you could write `cdf --verbose build --env dev`, now you should write
  `cdf build --env dev --verbose`.

## [0.3.0a4] - 2024-09-13

### Added

- The `WorkflowTrigger` config files now supports `object` (`dict`) as a valid type for the
  `data` field. This will automatically be converted to a `json` string when deploying the trigger.

### Fixed

- The field `default_organization_dir` was not read in the `cdf.toml` file. This is now fixed.
- The `cdf modules upgrade` command would fail to update `0.3.0a1` and `0.3.0a2` to `0.3.0a3`. This is now fixed.
- If the version of a `DataModel` or `View` was set to `1_0_0` in the resource file, Toolkit would send
  it as `100` to the API. This is now fixed.
- Groups without metadata no longer triggers redeploy when running `cdf deploy`

## [0.3.0a3] - 2024-09-11

### Fixed

- LocationFilter did not load subclasses properly. This is now fixed.
- When running any command, the terminal would print warnings from the `cognite-sdk`. This is now fixed.
- The `cdf modules init` no longer creates an invalid `cdf.toml` file when the user uses an `organization-dir`.

### Changed

- In the commands `build` and `pull`, `modules upgrade` and `modules list`,  `organization-dir` is now an
  optional argument `--organization-dir` and `-o` instead of positional argument. This is to have consistent
  behavior with other commands.
- The config filed `cdf.toml` is now created with `cdf modules init` instead of `cdf repo init`.
- In `cdf.toml` the `organization_dir` is renamed `default_organization_dir`.

## [0.3.0a2] - 2024-09-10

### Fixed

- Running `cdf repo init` now creates a `cdf.toml` with the correct version.

## [0.3.0a1] - 2024-09-10

### Added

- Loaders for resource types `Assets`, `3DModel`, and `Robotic` (`Map`, `DataPostProcessing`, `RobotCapability`,
  `Frame`, and `Location`). These loaders were earlier available as feature preview.
- Support for `LocationFilter` in the `locations` folder.
- Command `cdf repo init` to initialize the repository with `.gitignore`, `.env`, and the new
  Toolkit configuration file `cdf.toml`
- Command `cdf modules list` to list all modules.
- Command `cdf modules init` to setup modules. This is interactive and will guide you through selecting the
  modules you want to use. You can bypass the interactive mode by using the `--all` flag. which
  will select all modules, similar to the previous `cdf-tk init` command.
- Command `cdf modules upgrade` to upgrade all modules automatically.

## Changed

- The resource `FunctionSchedule` is not uniquely identified by `name` instead of `cronExpression` by the Toolkit.
  This enables multiple schedules with the same cron expression for the same function.
- The Toolkit no longer gives warnings for naming conventions that are not followed.
- [BREAKING] The resource `Label` is now in the resource folder `classic` and not in the `labels` folder.

## Removed

- [BREAKING] The command `cdf-tk init` it now replaced by `cdf repo init` and `cdf modules init`.

## [0.2.20] - 2024-08-31

### Fixed

- Ignore `.pyc` files when hashing function directories in the `cdf-tk deploy` command. This prevents unnecessary
  redeployments of functions.

## [0.2.19] - 2024-08-26

### Fixed

- Views and DataModels with versions that are integers are only being redeployed if they have changed in the
  `cdf-tk deploy` command. They were earlier always redeployed.

## [0.2.18] - 2024-08-22

### Added

- Location Filter support

### Fixed

- When running `cdf-tk deploy`, the Toolkit would not detect `Function` secrets that were changed, which leads to the
  `Function` not being updated. This is now fixed.

- [Feature Preview] improved `--interactive / -i` for `dump asset` and `dump timeseries`
  - which can list datasets or assets with `clear-name (external_id) [count]`

    ```bash
    ? Select a data set listed as 'name (external_id) [count]'
      (Use arrow keys to move, <space> to select, <a> to toggle, <i> to invert)
    » ○ (WITSML) [286,088]
      ○ (DBCalculations) [6,007]
      ○ (SAP) [6]
      ○ (Wells) [0]
      ○ (Drilling) [45]
    ```

  - an "Abort" option is now available

    ```bash
    No data set selected.
    Select a data set to dump (Use arrow keys)
      Data Set
      Done
    » Abort
    ```

- [Feature Preview] new feature `TIMESERIES_DUMP` added
  - `cdf-tk dump timeseries` now dumps to yaml/csv/parquet
  - supports `--data-set / -d` selection
  - supports `--interactive / -i`
  - feature does not include datapoints

- [Feature Preview] In the command `cdf-tk import transformation-cli`, the Toolkit no longer raises
  an `UnicodeDecodeError` when importing a manifest with a query file that contains special characters
  on Windows.

- The Toolkit previously detected a version as changed in the cdf-tk deploy command if it was an integer in
  a DataModel or View resource file. This issue is now fixed.

## [0.2.17] - 2024-07-26

### Changed

- [Feature Preview] `cdf-tk dump asset` now dumps into multiple files and no longer raise an Exception
  when dumping into `.parquet` format.
- [Feature Preview] `cdf-tk dump asset` now also dumps labels used by the assets.

### Fixed

- [Feature Preview] `cdf-tk dump asset` now respects the selected `dataset` when set in interactive mode.
- The Toolkit no longer tries to do variable replacement in `.parquet` files in `cdf-tk build`, which would
  raise an error.
- When running `cdf-tk deploy` with a capability that is undocumented but supported in the API, the Toolkit
  would raise an error. This is now fixed.
- [Feature Preview] When using `functionExternalID`+`name` to identify a function schedule, the `cdf-tk deploy` command
  no longer raise a `ValueError`.

## [0.2.16] - 2024-07-23

### Changed

- In the `cdf-tk build` command, if the `Function` code cannot be imported, the Toolkit will now give a
  warning instead of an `ToolkitValidationError`. This is to allow you to deploy code developed in a
  different environment than the environment used to run Toolkit.

## [0.2.15] - 2024-07-22

### Added

- [Feature Preview] Support for uploading `3DModel` resource to CDF. Note this is the metadata about a 3D model
  Turn on the feature by running `cdf-tk features set model-3d --enable`.

### Fixed

- Running `cdf-tk deploy` after a failed build would raise an incorrect `ToolkitNotADirectoryError`,
  instead of a `ToolkitFileNotFoundError` for the `_build_enviroment.yaml` file. This is now fixed.
- When running `cdf-tk deploy` with `Functions` that have not explicitly set `cpu`, `memory`, or `runtime`,
  would always be classified as changed. This is now fixed.
- [Feature Preview] When dumping assets to `csv`, headers are no longer repeated for each 1000 asset.
- [Feature Preview] When dumping assets to `parquet`, you can now dump more than 1000 assets without
  getting the error `TypeError: write() got an unexpected keyword argument 'mode'`.
- [Feature Preview] When dumping assets to `parquet/csv`, the Toolkit now keeps all asset in memory until it finds
  all unique metadata keys. This is to ensure that header is correct in the resulting `parquet/csv` file.
- In the `config.[env].yaml`, the `name` parameter in the `environment` section is no longer required.
  This was supposed to be remove in `0.2.0a4`.
- If you run `cdf-tk build --env dev`, and then `cdf-tk deploy -env prod` the Toolkit will
  now raise a `ToolkitEnvError`.
- If you run `cdf-tk build`, the Toolkit will no longer complain about resources that exist in
  CDF but not in the build directory (given that the Toolkit has access to CDF).
- If you deploy a data model that already exists in CDF, the API will silently fail to update the data model if
  there are any changes to the views in the data model. The Toolkit will now verify that the update of data models
  was successful and raise an error if it was not.

### Changed

- When running `cdf-tk deploy` for a function the Toolkit checked that it could import the function code
  before deploying the function. This is now removed. The reason is that the toolkit is often run in a
  different Python environment than the function code. This made this check unnecessarily restrictive
  as it would fail even though the function code was correct due to missing dependencies.
- [Feature Preview] Instead of using `functionExternalID`+`cron` expression to identify a function schedule,
  the Toolkit now uses `functionExternalID`+`name`. This is to avoid the Toolkit to create multiple schedules
  for the same function if the cron expression is changed and allow to have multiple schedules with the same
  cron expression for the same function. To enable this feature, run `cdf-tk features set fun-schedule --enable`.

## [0.2.14] - 2024-07-15

### Fixed

- If a container with a direct relation property with a required constraint on another container, the `cdf-tk build`
  would not give a warning if the required container was missing. This is now fixed.
- [Feature Preview] In the feature preview, `robotics`, the properties `inputSchema` or `dataHandlingSchema`
  in `RobotCapability` and `DataPostProcessing` were not updated correctly. This is now fixed.
- When running `cdf-tk build`, with a `Node` resource. You would get a `MissingRequiredIdentifierWarning` even though
  the `Node` had a `space`/`externalId`. This is now fixed.
- In the `cdf-tk deploy/clean` command, the `-i` short flag was used for `--interactive` and `--include` at the same time.
  This is now fixed, and the `-i` flag is only used for `--interactive`.
- Require `cognite-sdk>=7.54.1`, this version fixed a bug in the `cognite-sdk` that caused the `cdf-tk` to raise
  an `CogniteAPIError` when deploying or cleaning more than 10 `functions`.

## [0.2.13] - 2024-07-10

### Fixed

- [Feature Preview] In the feature preview, `cdf-tk import transformation-cli`, the Toolkit would fail to convert
  manifest with `destination: <string>` correctly. This is now fixed.
- On Windows, when reading files from disk, the Toolkit could raise an `UnicodeDecodeError`. This is now fixed.
- [Feature Preview] In the feature preview, `robotics`, if you tried to update a set of resources in which some
  were existing and others not, the Toolkit would create the new resources. This is now fixed.

## [0.2.12] - 2024-07-08

### Added

- [Feature Preview] Robotic support.

## [0.2.11] - 2024-07-05

### Fixed

- When running `cdf-tk build`, if you had two files non-YAML files named the same in different modules, or subdirectories
  in the same module, the Toolkit would overwrite the first file with the second file. This is now fixed.

## [0.2.10] - 2024-07-03

### Fixed

- When running `cdf-tk build`, if you use subdirectories in a resource directories, and have two resources with the
  same file name, the Toolkit would overwrite the first resource with the second resource. This is now fixed. For
  example, if you have `my_module/transformation/subdirectory1/my_transformation.Transformation.yaml` and
  `my_module/transformation/subdirectory2/my_transformation.Transformation.yaml`, the Toolkit would only build the
  second resource.

## [0.2.9] - 2024-07-02

### Changed

- Tracking usage of Toolkit commands.

## [0.2.8] - 2024-07-01

### Added

- [Feature Preview] Option to turn off semantic naming checks for resources. Turn on the feature by running
  `cdf-tk features set no-naming --enable`.

### Fixed

- When running `cdf-tk run function --local`, the toolkit would raise an `ToolkitValidationError`. This is now fixed.
- When running `cdf-tk deploy --dry-run`, if any resource was referencing a `DataSet`, `SecurityCategory`,
  or `ExtractionPipeline`, it would incorrectly be classified as changed. This is now fixed. This applied to
  `ExtractionPipeline`, `FileMetadata`, `Function`, `Group`, `Label`, `TimeSeries`, and `Transformation` resources.

### Changed

- Function configurations for multiple functions can now be in multiple files in the function directory. Before
  all configurations had to be listed in the same YAML file.

## [0.2.7] - 2024-06-28

### Fixed

- Function schedule for functions with a `:` in the external id would raise an `ValueError`.
  This is now fixed.
- Transformation notifications for transformations with a `:` in the external id would raise an `ValueError`.
  This is now fixed.
- When running `cdf-tk deploy`, you would get warnings about unrelated resources that were not part of the deployment.
  This is now fixed.
- The `transformations/notifications` endpoint was giving `500` errors for requests to non-exising transformations.
  This is now handled by the toolkit and will not raise an error.
- When doing variable replacement in a `sql` such as `dataset_id('{{dataset_external_id}}')`, the toolkit would
  remove the quotes. This is now fixed.

## [0.2.6] - 2024-06-26

### Improved

- The `--verbose` flag is now moved to the end of the command. For example, instead of `cdf-tk --verbose build`,
  you should now write `cdf-tk build --verbose`. The old syntax is still supported but will raise a deprecation warning.
- When running `cdf-tk deploy --verbose` you will now get a detailed output for each resource that has changed
  (or will change if you use --dry-run).
- Allow values `test` and `qa` as `type` in the `config.[env].yaml` file.

### Fixed

- When running `cdf-tk build` with `Views` with custom filters, the Toolkit would likely give a `UnusedParameterWarning`.
  This is now fixed by not validating the details of `View.filters`. The motivation is that `View.filters` is a complex
  structure, and it is likely that you will get a false warning. The users that starts to use `View.filters` are
  expected to know what they are doing.
- If you run `cdf-tk deploy` and you had a child view that overrides a property from a parent view, the Toolkit would
  log it as changed even though it was not. This is now fixed.

## [0.2.5] - 2024-06-25

### Fixed

- When running `cdf-tk build`, with `RAW` tables in the selected modules, the Toolkit would always warn that the
  tables were missing, even though they were present. This is now fixed.
- When running `cdf-tk init --upgrade <YOUR PROJECT>` form version `0.1.4` the user would get a
  `ERROR (ToolkitMigrationError): Failed to find migration from version 0.1.4.`. This is now fixed.
- When running `cdf-tk build`, the Toolkit would give you warning when referencing a system `Space`, `View`, `Container`
  or `DataModel`. This is now fixed.
- [Feature Preview] When running `cdf-tk import transformation-cli` on a manifest with a query file that
  is separated from the manifest, the toolkit would raise a `FileNotFoundError`. This is now fixed.

## [0.2.4] - 2024-06-24

### Added

- [Feature Preview] Support for resource type `Asset` in the `assets` folder. Turn on the feature by running
  `cdf-tk features set assets --enable`.

### Improved

- When running `cdf-tk build` and the selected modules is missing, the user will now get a hint about
  how to fix the issue.
- When running `cdf-tk build` and a module contains non-resource directories, the user will now get a warning
  that the directory is not a resource directory.

### Fixed

- The data type of variables `config.[env].yaml` file is now preserved. For example, if you had `my_variable: "123"`,
  then the `cdf-tk build`  would build the resource file with the number instead of the string, `my_variable: 123`.
  This is now fixed.
- File configurations given as a list/array, lost the `dataSetExternalId` in the `cdf-tk deploy` command.
  This is now fixed.
- Added missing required dependency `packaging` to `cognite-toolkit`.

## [0.2.3] - 2024-06-20

### Improved

- When running `cdf-tk build` and missing `CDF_PROJECT` environment variable, the user will now get a more informative
  error message.

### Fixed

- The variable `type` in the `environment` section of the `config.[env].yaml` now raises an error if it is not
  set to `dev`, `staging`, or `prod`.

### Added

- The preview feature `IMPORT_CMD` added. This enables you to import a `transformation-cli` manifest into
  resource configuration files compatible with the `cognite-toolkit`. Activate by running
  `cdf-tk features set IMPORT_CMD --enable`, and deactivate by running `cdf-tk features set IMPORT_CMD --disable`.
  Run `cdf-tk import transformation-cli --help` for more information about the import command.

## [0.2.2] - 2024-06-18

### Improved

- The command line messages have been improved to be more informative and user-friendly when running
  `cdf-tk auth verify`.
- The `variables` section in `config.[env].yaml` is now optional.
- In `cdf-tk build`, more informative error message when a variable is unresolved in a resource file.

### Fixed

- In the `cdf-tk auth verify` command, if the flag `--interactive` was set, the `--update-group` and `create-group`
  flags were not ignored. This is now fixed.
- In the `cdf-tk auth verify` command, if there was no `.env` or `--cluster` and `--project` flags, the toolkit
  would raise an `AuthentciationError`, instead of prompting the user for cluster and project. This is now fixed.
- In the `cdf-tk auth verify` command, the if function service was not activated, the toolkit will
  now activate it.
- When running `cdf-tk build`, and a resource file was missing its identifier, for example, `externalId` for a
  dataset, an error such as `AttributeError: 'NoneType' object has no attribute 'split'` was raised. This is now fixed.

## [0.2.1] - 2024-06-17

### Improved

- When running `cdf-tk auth verify`, if the client does not have access to the `CDF_PROJECT` the user will now get
  a more informative error message.
- When running `cdf-tk auth verify` and missing the `FunctionAcl(READ)` capability, the user will now get a more
  informative error message when checking the function service status

### Added

- Preview feature `MODULES_CMD` to allow interactive init and automatic upgrade of modules. Activate by running
  `cdf-tk features set MODULES_CMD --enable`, and deactivate by running `cdf-tk features set MODULES_CMD --disable`.
  Run `cdf-tk modules init/upgrade` to interactively initialize or upgrade modules.
  
## Fixed

- When running `cdf-tk build`, you would get a `DuplicatedItemWarning` on RAW Databases that are used with multiple
  tables. This is now fixed.

### Added

- Preview feature `MODULES_CMD` to allow interactive init and automatic upgrade of modules. Activate by running
  `cdf-tk features set MODULES_CMD --enable`, and deactivate by running `cdf-tk features set MODULES_CMD --disable`.
  Run `cdf-tk modules init/upgrade` to interactively initialize or upgrade modules.

## [0.2.0] - 2024-06-10

### Fixed

- When running `cdf-tk clean` or `cdf-tk deploy --drop --drop-data` there was an edge case that triggered the bug
  `ValueError: No capabilities given`. This is now fixed.
- When deploying `containers` resources with an index, the `cdf-tk deploy` would consider the resource as changed
  even though it was not. This is now fixed.
- When parsing yaml without `libyaml`, `cognite-toolkit` would raise an
  `AttributeError: module 'yaml' has no attribute 'CSafeLoader'`. This is now fixed by falling back to the
  python `yaml` parser if `libyaml` (c-based) is not available.

## [0.2.0b4] - 2024-06-06

### Added

- Support for resource type `TransformationNotification` in the `transformations` folder.

### Changed

- [BREAKING] In `functions`, the function config file must be in the root function directory. This means
  that, for example, `my_module/function/some_folder/function.yaml` will no longer be included by
  the `cdf-tk build` command. Instead, it must be in `my_module/function/function.yaml`. The motivation
  is to allow arbitrary YAML files as part of the function code.
- The toolkit now only gives a `TemplateVariableWarning` (`Variable my_variable has value <change_me> ...`) if
  the variable is used by `selected` in the `config.[env].yaml`. This is to avoid unnecessary warnings.
- The `FeaturePrevieWarnings` are no longer printed when running `cdf-tk deploy` or `cdf-tk clean`. These warnings
  are from the `cognite-sdk` and can be confusing to the user.

### Fixed

- When running `cdf-tk init --upgrade` from version `0.1.4` the user would get a `ToolkitMigrationError`.
  This is now fixed.

## [0.2.0b3] - 2024-06-04

### Added

- Support for resource type `Label` in the  `labels` folder.

### Fixed

- The toolkit now ensures `Transformations` and `Functions` are deployed before `Workflows`
- The toolkit now ensures `TimeSeries` and `Groups` are deployed before `DatapointSubscriptions`.

## [0.2.0b2] - 2024-06-03

### Fixed

- Running the build command, `cdf-tk build`, with `Group` resources scoped will read to incorrect
  warning such as `WARNING [HIGH]: Space 'spaceIds' is missing and is required by:` and
  `WARNING [HIGH]: DataSet 'ids' is missing and is required by:`. This is now fixed.
- Running the build command, `cdf-tk build`, with a `View` resource with a `hasData` filter would print a
  `UnusedParameterWarning: Parameter 'externalId' is not used in section ('filter', 'hasData', 0, 'externalId').`.
  This is incorrect and is now fixed to not print this warning.
- If you had a `container` with a direct relation property with a required constraint, the `cdf-tk build` command
  would incorrectly yield a warning that the `Parameter 'type' is not used ...`. This is now fixed.

## [0.2.0b1] - 2024-05-20

### Added

- Support for loading `nodes` with `APICall` arguments. The typical use case is when `node types` are part of a
  data model, and the default `APICall` arguments works well.

### Fixed

- Error message displayed to console on failed `cdf-tk deploy` command could be modified. This is now fixed.
- Using display name instead of folder name on a failed `cdf-tk deploy` or `cdf-tk clean` command. For example,
  if `datapoints subscription` was failing the error message would be `Failure to load/deploy timeseries as expected`,
  now it is `Failure to load/deploy timeseries.subscription as expected`.
- Unique display names for all resource types.
- Fixed bug when deploying extraction pipeline config, when none existed from before:
  `There is no config stored for the extraction pipeline`.

### Changed

- In `config.[env].yaml`, in the `environment` section, `selected_modules_and_packages` is renamed to `selected`.
  The old names will still work, but will trigger a deprecation warning.

## [0.2.0a5] - 2024-05-28

### Added

- If a resource is referring to another resource, the `cdf-tk build` will now give a warning if the referred resource
  is not found in the same build. For example, if you have a data model and is missing the space, the build command
  will give a warning that the space required by the data model is missing.
- The `cdf-tk build` command will now give warnings on duplicated resource. For example, if you have two files with
  the same externalId in the same module, the build command will give a warning that the externalId is duplicated,
  and that only the first file is used.
- Support for `securityCategories` in the `auth` folder.
- Added support for resource type `DatapointSubscription` in the `timeseries` folder.

### Fixed

- In a `function` config, if you did not set `fileId` you would get an error when running `cdf-tk deploy`,
  `Missing required field: 'fileId'.`. The `fileId` is generated automatically when the function is created,
  so it is not necessary to set it in the config file. This is now fixed.
- If you do `cdf-tk init --upgrade`, on a pre `0.2.0a3` version, you are met with
  `ERROR (ToolkitModuleVersionError): Failed to load previous version, ...`. This is now fixed.
- The parameter `container.properties.<property>.type.list` was required to be set, even thought it is optional
  in the CDF API. This is now fixed.
- The `ExtractionPipelineConfig` create, update and delete report numbers were incorrect. This is now fixed.

### Improved

- Gives a more informative error message when the authentication segment of a transformation resource file is
  missing a required field.
- Transformation queries can be inline, i.e. set in either the Transformation `query` property in the yaml or
  as a separate file. If set in both, an error is raised because it is ambiguous which query to use.
- In the `cdf-tk pull` command, if an error occurs, the temporary directory was not removed. This is now fixed.
- Improved error message when running `cdf-tk deploy/clean` before running `cdf-tk build`.

### Changed

- [BREAKING] In function YAML config `externalDataSetId` is renamed to `dataSetExternalId` to be consistent with
  the naming convention used in the rest of the toolkit.

## [0.2.0a4] - 2024-04-29

### Removed

- [BREAKING] `cognite-tookit` no longer supports `common_function_code`. The code used by functions must be in each
  function directory. The reason for this is that `cognite-toolkit` is a tool for governance and deployment of
  modules, it is not for development of functions. The `common_function_code` was a feature to support easier
  development of functions. It is expected that functions are developed in a separate environment and then
  moved to the `cognite_modules` folder for deployment and promotion between environments.

### Changed

- In `config.[env].yaml`, in the `environment` section, `name` is no longer required. Instead, the `[env]` part
  of the `config.[env].yaml` file is used as the `name` of the environment. This is to avoid redundancy.

### Improved

- When running `cdf-tk clean --dry-run` the output would show local resources regardless of whether they existed
  in CDF or not. This is now fixed and only resources that exist in CDF are shown in the output.
- Better error message (no exception raised) if the config file has `selected_modules_and_packages`, but with no list items.
- If yaml files are invalid, a link to the API docs for the resource is shown in the error message.

### Fixed

- When deploying a `FunctionSchedule` that requires an update, the `cdf-tk` would fail with error
  `Failed to update functions.schedules. Error 'FunctionSchedulesAPI' object has no attribute 'update'.`.
  This is now fixed.
- When calling `cdf-tk init --upgrade`, the user is met with a `Failed to load previous version, ...`.
  This is now fixed.
- When running `cdf-tk auth verify --interactive` and the user want to create a new group with the necessary
  capabilities, the `cdf-tk` would successfully create a group, but then raise
  an Error: `cognite.client.exceptions.CogniteAPIError: Insufficient access rights.` when trying to validate.
  This is now fixed.

## [0.2.0a3] - 2024-04-23

### Added

- Support for the Workflow and WorkflowVersion resource type
- Support for specifying `selected_modules_and_packages` as paths and parent paths. For example, you can
  now write `cognite_modules/core/cdf_apm_base` instead of just `cdf_apm_base`. This is to support
  modules that have the same name but are in different parent directories. In addition, this also better reflects
  the structure of the `cognite_modules` and `custom_modules` folder better.

### Fixed

- Functions that are deployed with schedules no longer uses a short-lived session (before: failed after ~an hour).

### Changed

- [BREAKING] The `cdf-tk build` will now clean the build directory by default before building the modules to avoid
  unwanted side effects from previous builds. To stop this behavior, use the `--no-clean` flag.
- [BREAKING] The `_system.yaml` is now required to be on the root level when running any `cdf-tk` command. This
  means that the `_system.yaml` file must be in the same directory as the `config.[env].yaml` files. This is to
  support running `cdf-tk` without the `cognite_modules` folder.
- [BREAKING] In the `config.[env].yaml` files, the `modules` section is now renamed to `variables`. This is to
  better reflect the content of this section, which is variables that can be used in the resource files.
- In addition to `cognite_modules` and `custom_modules`, the `cognite-toolkit` now also support `modules` as the
  top-level folder for modules. This together with the two changes above, is to have a better support for running
  the `cognite-toolkit` as a standalone CLI without the `cognite_modules`.
- The `.gitignore` file you get by running `cdf-tk init` now ignores the `/build` by default.
- The dependency `cognite-sdk` must now be `>=7.37.0` to use the `cdf-tk`.

## [0.2.0a2] - 2024-04-03

### Added

- Variables can now have extra spaces between curly braces and the variable name. For example, `{{  my_variable }}` is now
  a valid variable. Before this change, you would have to write `{{my_variable}}`.
- If an environment variable is not found in a resource file, for example, `${CDF_CLUSTER}`, when
  running `cdf-tk deploy` the user will now get a warning message that the variable is missing. Before this change,
  this would pass silently and potentially cause an error when trying to deploy to CDF that was hard to debug.

### Fixed

- When running `cdf-tk` with a Token for initialization, the `cdf-tk` would raise an `IndexError`. This is now fixed.
- Container resources that did not have set the optional property `usedFor` would always be classified as changed,
  when, for example, running `cdf-tk deploy --dry-run`. This is now fixed.

### Changed

- If two modules have the same name, the `cdf-tk build` command will now stop and raise an error. Before this change,
  the `cdf-tk build` command would continue and overwrite the first module with the second module.

## [0.2.0a1] - 2024-03-20

### Added

- Support for interactive login. The user can now set `LOGIN_FLOW=interactive` in the `.env` file
  to use interactive login.

### Changed

- The verification of access by the tool is now scoped to the resources that are being deployed instead of
  the entire project. This means that if the user only has access to a subset of the resources in the project,
  the tool will still be able to deploy those resources.

## [0.1.2] - 2024-03-18

### Fixed

- Running the command `cdf-tk auth verify --interactive` without a `.env` would raise a
  `AttributeError: 'CDFToolConfig' object has no attribute '_client'` error. This is now fixed and instead the user
  gets a guided experience to set up the `.env` file.

### Changed

- `cognite-toolkit` have moved the upper bound on the `cognite-sdk` dependency from `7.27` to `8.0`.
- Creating/Removing `spaces` no longer requires `DataModelingInstances` capability.

## [0.1.1] - 2024-03-01

### Fixed

- When running `cdf-tk clean` or `cdf-tk deploy --drop-data` for a data model with more than 10 containers,
  the command would raise an APIError. This is now fixed.
- A few minor potential `AttributeError` and `KeyError` bugs have been fixed.

## [0.1.0] - 2024-02-29

### Added

- Command `cdf-tk dump datamodel` for dumping data models from CDF into a local folder. The use case for this is to
  dump an existing data model from CDF and use it as a basis for building a new custom module with that data model.
- A Python package API for the cdf-tk. This allows for programmatic access to the cdf-tk functionality. This
  is limited to the `build` and `deploy` functionality. You can start by `from cognite_toolkit import CogniteToolkit`.

### Fixed

- In the function deployment, the hashing function used of the directory was independent of the location of the files
  within the function directory. This caused moving files not to trigger a redeployment of the function. This is now
  fixed.

### Changed

- Removed unused dependencies `mypy`, `pyarrow` and `chardet` from `cognite-toolkit` package.
- Lowered the required version of `pandas` to `1.5.3` in the `cognite-toolkit` package.

## [0.1.0b9] - 2024-02-20

### Added

- Introduced `cdf-tk pull transformation` and `cdf-tk pull node` commands to pull transformation or nodes
  from CDF to the local module.
- Support for using a template for file names `name: prefix_$FILENAME_suffix` in the `files` resource. The files will
  be processed and renamed as part of the build step.

### Fixed

- Fixed a bug that caused `Group` upsert to leave duplicate Groups
- Fixed issue with `run function --local` that did not pick up functions in modules without config variables.
- Fixed error when running `run function --local` on a function without all optional parameters for handle() being set.
- Bug when `cdf-tk deploy` of `ExtractionPipelineConfig` with multiple `config` objects in the same file.
  Then only the first `config` object was deployed. This is now fixed.

### Changed

- `cdf-tk` now uses --external-id consistently instead of --external_id.
- Removed upper limit on Python version requirement, such that, for example, `Python 3.12` is allowed. Note
  that when working with `functions` it is recommended to use `Python 3.9-3.11` as `Python 3.12` is not
  supported yet.
- `cdf-tk deploy`/`cdf-tk clean` now deploys all config files in one go, instead of one by one. This means batching
  is no longer done based on the number of resource files, but instead based on the limit of the CDF API.
- Files in module directories that do not live in a recognised resource directory will be skipped when building. If
  verbose is enabled, a warning will be printed for each skipped file.
- Only .yaml files in functions resource folders and the defined function sub-directories will be processed as part of
  building.

## [0.1.0b8] - 2024-02-14

### Added

- `Group` resource type supports list of groups in the same file

### Fixed

- `View` which implements other views would always be classified as changed, ven though no change
  has been done to the `view`, in the `cdf-tk deploy` command. This is now fixed.
- `DataModels` which are equal would be wrongly classified as changed if the view order was different.
  This is now fixed.
- In the `cdf-tk build`, modules with a nested folder structure under the resource folder were not built correctly.
  For example, if you had `my_module/data_models/container/my_container.container.view`, it would be put inside
  a `build/container/my_container.container.yaml` instead of `build/data_models/my_container.container.yaml`,
  and thus fail in the `cdf-tk deploy/clean` step. This is now fixed.
- When running `cdf-tk deploy` the prefixed number on resource file was not used to sort the deployment order.
  This is now fixed.
- Fixed a bug that caused Extraction Pipeline Config update to fail

## [0.1.0b7] - 2024-02-07

### Added

**NOTE: The function changelog was by accident included in beta6 and has been moved to the correct version.**

- Added support for loading functions and function schedules. Example of a function can be found in `cognite_modules/example/cdf_functions_dummy`.
- Added support for common function code as defined by `common_function_code` parameter in the environment config file.
- Added support for new command, `run function` that runs a function with a one-shot session created using currently
  configured credentials for cdf-tk.
- Added support for running a Cognite function locally using the `run function --local` command. This command will run the
  function locally in a virtual environment simulating CDF hosted run-time environment and print the result to the console.

### Changed

- **BREAKING:** The cdf-toolkit now requires one `config.yaml` per environment, for example, `config.dev.yaml` and `config.prod.yaml`.
- **BREAKING:** The file `environments.yaml` has been merged into `config.[env].yaml`.
  This means that the `environments.yaml` file is no longer used and the `config.[env].yaml`
  file now contains all the information needed to deploy to that environment.
- The module `cognite_modules` is no longer considered to be a black box governed by the toolkit, but should instead
  be controlled by the user. There are two main changes to the `cognite_modules` folder:
  - All `default.config.yaml` are removed from `cognite_modules` and only used when running `cdf-tk init`to generate
    `config.[env].yaml` files.
  - The file `default.packages.yaml` has been renamed `_system.yaml` and extended to include the `cdf-tk` version.
    This should not be changed by the user and is used to store package information for the toolkit itself and
    version.
- Running the `cdf-tk init --upgrade` now gives the user instructions on how to update the breaking changes
  since their last upgrade.
- If the user has changed any files in `cognite_modules`, the command `cdf-tk init --upgrade` will no longer
  overwrite the content of the `cognite_modules` folder. Instead, the user will be given instructions on how to
  update the `cognite_modules` files in the folder manually.

### Fixed

- In the generation of the `config.[env].yaml` multiline comments were lost. This is now fixed.

## [0.1.0b6] - 2024-01-25

### Added

- In `raw` resources, a RAW database or tables can be specified without data. Example, of a single database

 ```yaml
dbName: RawDatabase
```

or a database with table, no need to also specify a `.csv` or `.parquet` file for the table as was necessary before.

```yaml
dbName: myRawRawDatabase
tableName: myRawTable
```

### Changed

- Update is implemented for all resources. This means that if a resource already exists and is exactly the same as
  the one to be deployed, it will be updated instead of deleted and recreated.
- The `cdf-tk deploy` `--drop-data` is now independent of the `--drop` flag. This means that you can now drop data
  without dropping the resource itself. The reverse is not true, if you specify `--drop` without `--drop-data`, only
  resources that can be deleted without dropping data will be deleted.
- The output of the `cdf-tk deploy` command has been improved. Instead of created, deleted, and skipped resources
  being printed in a table at the end of the command, the resources are now printed as they are created, deleted, changed,
  and unchanged. In addition, an extra table is printed below with the datapoints that have been uploaded and dropped.
- The output of the `cdf-tk clean` command has also been changed in the same way as the `cdf-tk deploy` command.
- The `files` resource has been split into two resources, `FileMetadata` and `Files` to separate the metadata from
  the data (the file).
- To ensure comparison of resources and be able to determine whether they need to be updated, any resource
  defined in a YAML file will be augmented with default values (as defined by the CDF API) if they are missing before
  they are deployed.

### Fixed

- Bug in `auth` resource, this caused  groups with `all` and `resource` scoped capabilities to be written in two steps
  first with only `all` scoped capabilities and then all capabilities. This is now fixed by deploying groups in
  a single step.

## [0.1.0b5] - 2024-01-11

### Added

- Support for custom environment variables injected into build files when calling the command `cdf-tk deploy`.
- All resources that are unchanged are now skipped when running `cdf-tk deploy`.
- Support for loading `Group` Capabilities with scope `idScope` of type string. This means you can now set the
  `idScope` to the external id of a `dataSet` and it will be automatically replaced by the dataset id
  `cdf-tk deploy`.

### Fixed

- Fixed bug when calling any command loading a `.env` file and the path is not relative to the current working
  directory. This is now fixed.
- Calling `cdf-tk init --upgrade` overwrote all variables and comments set in the `config.yaml` file. This is now
  fixed.

### Improved

- Improved error message when missing a variable in `config.yaml` and a variable with the same name is defined
  for another module.

## [0.1.0b4] - 2024-01-08

### Added

- Added `--env-path` option to specify custom locations of `.env` file

### Fixed

- Fixed bug in command `cdf-tk build` that can occur when running on `Python>=3.10` which caused an error with text
  `TypeError: issubclass() arg 1 must be a class`. This is now fixed.

## [0.1.0b3] - 2024-01-02

### Fixed

- Fixed bug in `cdf-tk deploy` where auth groups with a mix of all and resource scoped capabilities skipped
  the all scoped capabilities. This is now fixed.

## [0.1.0b2] - 2023-12-17

### Fixed

- Handle duplicate `TransformationSchedules` when loading `Transformation` resources.
- Print table at the end of `cdf-tk deploy` failed with `AttributeError`, if any of resources were empty.
  This is now fixed.
- The `cdf-tk build` command no longer gives a warning about missing `sql` file for
  `TransformationSchedule`s.

## [0.1.0b1] - 2023-12-15

### Added

- Warnings if a configuration file is using `snake_case` when then resource type is expecting `camelCase`.
- Added support for validation of `space` for data models.
- Check for whether template variables `<change_me>` are present in the config files.
- Check for whether data set id is present in the config files.
- Print table at the end of `cdf-tk deploy` with the resources that were created, deleted, and skipped.
- Support for Extraction Pipelines and Extraction Pipeline configuration for remotely configured Extractors
- Separate loader for Transformation Schedule resources.

### Removed

- In the `deploy` command `drop_data` option has been removed. To drop data, use the `clean` command instead.

### Changed

- Require all spaces to be explicitly defined as separate .space.yaml file.
- The `data_set_id` for `Transformations` must now be set explicitly in the yaml config file for the `Transformation`
  under the `data_set_id` key. Note that you also need to explicitly define the `data_set` in its own yaml config file.
- All config files have been merged to a single config file, `config.yaml`. Upon calling `cdf-tk init` the `config.yaml`
  is created in the root folder of the project based on the `default.config.yaml` file of each module.
- DataSetID is no longer set implicitly when running the `cdf-tk deploy` command. Instead, the `data_set_id` must be
  set explicitly in the yaml config file.

### Fixed

- When running `cdf-tk deploy` with `--dry-run` a `ValueError` was raised if not all datasets were pre-existing.
  This is now fixed by skipping dataset validation when running with `--dry-run`.
- When having a `auth` group with mixed capabilities of all scoped and resource scoped, the all scoped capabilities
  were not removed when running `cdf-tk deploy`. This is now fixed.
- Loading `Transformation` did not support setting `dataSetExternalId` in the yaml config file. This is now fixed.

## [0.1.0a3] - 2023-12-01

### Changed

- Refactored load functionality. Loading raw tables and files now requires a `yaml` file with metadata.
- Fix container comparison to detect identical containers when loading data models (without --drop flag).
- Clean up error on resource does not exist when deleting (on `deploy --drop` or using clean command).

### Added

- Support for loading `data_sets`.
- Support for loading auth without --drop, i.e. `deploy --include=auth` and only changed groups are deployed.
- `cdf-tk --verbose build` now prints the resolution of modules and packages.
- Added `cdf-tk --version` to print the version of the tool and the templates.
- Support for `upsert` for `data_sets`.
- The cmd `cdf-tk deploy` creates the `data_set` before all other resources.
- Data sets are no longer implicitly created when referenced by another resource, instead an error is raised.
- Require all spaces to be explicitly defined as separate .space.yaml file.
- Add protection on group deletion and skip any groups that the current service principal belongs to.
- Support for multiple file resources per yaml config file for files resources.
- Support templated loading of * files in a folder when a single yaml has `externalId: something_$FILENAME`.
- You can now name the transformation .sql either with the externalId (as defined in the
  corresponding yaml file) or with the name of the file of the corresponding yaml file.
  I.e. if a transformation is defined in my_transformation.yaml with externalId:
  `tr_something`, the SQL file should be named either `tr_something.sql` or `my_transformation.sql`.
- Missing .sql files for transformations will now raise an error in the build step.
- The build step will now raise a number of warnings for missing externalIds in the yaml files,
  as well as if the naming conventions are not followed.
- System section in `environments.yaml` to track local state of `cdf-toolkit`.
- Introduced a `build_environment.yaml` in the `/build` folder to track how the build was run.

### Fixed

- `cdf-tk clean` not supporting `--include` properly.
- `cdf-tk clean` not working properly for data models with data.
- Fix group deletion on use of clean command to actually delete groups.

## [0.1.0a2] - 2023-11-22

### Fixed

- The `experimental` module was not included when running command `cdf-tk init`. This is now fixed.

## [0.1.0a1] - 2023-11-21

Initial release
