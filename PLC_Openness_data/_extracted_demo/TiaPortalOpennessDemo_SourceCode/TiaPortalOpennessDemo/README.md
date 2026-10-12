# TIA Portal Openness Demo
The "TIA Portal Openness Demo" is intended to show how to the development of an Openness application can be implemented easily and efficiently while supporting multiple Openness api versions in a single solution.

**Notice:**
Note the information in the manual in Chapter 6.2. Setup Solution.

## ContentModule
Contains the functionality for reading and displaying the properties of Siemens.Engineering types and devices.

## Dependencies/Openness
Contains the Siemens.Engineering dll’s of the supported versions.

## Documentation
The is available at the common manual "TIA Portal Openness: Introduction and demo application" in the project "TiaPortalOpennesDemo" 

## LibraryModule
Contains the functionality for handling a project-, global system- or global user library.

## MultiuserProjectModule
Contains the functionality for handling a multiuser project as local session.

## ProjectModule
Contains the functionality for handling a TIA Portal project.

## SharedResouceDictionary
Contains the functionality for central access to solution-wide resources such as icons or styles.

## SinamicsStartdrive
Contains the functionality for handling sinamics startdrive specific api calls.

## Step7
Contains the functionality for handling step7 specific api calls.

## TiaPortalModule
Contains the functionality for handling a TIA Portal instance.

## TiaPortalOpennessAdpter
Contains the functionality of the api version-independent api calls. 

## TiaPortalOpennessBase
Contains base implementations without references to siemens.engineering.dll’s, such as enums or models.

## TiaPortalOpennessContracts
Contains the solution-wide contract definitions.

## TiaPortalOpennessAdapterService
Contains the functionality of the base implementation for the version-independent api calls.

## TiaPortalOpennessCore
Contains the core functionality and implementation for the TIA Portal Openness Demo, such as menu or event definitions.

## TiaPortalOpennessDemo
Contains the functionality and main implementation for the TIA Portal Openness Demo.

## TiaPortalOpennessDemoStyling
Contains the resources provided by solution.

## TiaPortalOpennessInfrastructure
Contains the functionality and implementation of the infrastructure, such as log-service, exception- or constant defintions.

## TiaPortalOpennessModuleProvider
Contains the functionality to pre config the environment of the TIA Portal Openness Demo.

## WinCcProfessional
Contains the functionality for handling WinCC Professional specific api calls.

## WinCcUnified
Contains the functionality for handling WinCC Unified specific api calls.
