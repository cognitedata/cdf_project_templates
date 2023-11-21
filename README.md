# Official Cognite Data Fusion project templates

> [!NOTE]
> **ALPHA**
> 
> The templates and the `cdf-tk` tool are currently in ALPHA. The scope in alpha is on Asset
Performance Management focused on Infield (Digital Operator Rounds). The templates and tooling
will be continously improved throughout moving towards beta and general availability.

## Getting started

> [!IMPORTANT]
>
> To use this template, you will need to
> 1. Make your own copy of this repository
> 2. Change yaml-files that control the modules that are relevant to your Cognite Data Fusion projects(s)
> 3. Install the `cdf-tk` cli tool that can verify and deploy the modules you have configured
> 4. Optionally, set up GitHub Actions that deploy configuration changes as CI/CD

## Quickstart




### Toolkit

The CDF Toolkit is a command-line interface (`cdf-tk`) used for configuring and administrating Cognite Data
Fusion (CDF) projects.
It supports three different modes of operation:

1. As an **interactive command-line tool** used alongside the Cognite Data Fusion web application to retrieve and
   push configuration of the different Cognite Data Fusion services like data sets, data models, transformations,
   and more. This mode also supports configuration of new Cognite Data Fusion projects to quickly get started.
2. As tool to support the **project life-cyle by scripting and automating** configuration and management of Cognite Data
   Fusion projects where CDF configurations are kept as yaml-files that can be checked into version
   control. This mode also supports DevOps workflows with development, staging, and production projects.
3. As a **tool to deploy official Cognite project templates** to your Cognite Data Fusion project. The tool comes
   bundled with templates useful for getting started with Cognite Data Fusion, as well as for specific use cases
   delivered by Cognite or its partners. You can also create your own templates and share them.

>
> Below is an overview of the scope of what can be governed through using these templates:

![Overview of project templates](./static/overview.png "Overview")

## Quickstart

To install the `cdf-tk` tool, you need a working Python installation >=3.9 (recommended 3.11).
Run: `pip install cognite-toolkit`

The `cdf-tk` tool is available as a command line tool. Run `cdf-tk --help` to see the available commands.

## For more information

More details about the tool can be found at
[developer.cognite.com](http://developer.cognite.com/sdks/toolkit).

You can find an overview of the modules and packages in the
[module and package documentation](http://developer.cognite.com/sdks/toolkit/modules).

See [./CONTRIBUTING.md](./CONTRIBUTING.md) for information about how to contribute to the `cdf-tk` tool or
templates.
