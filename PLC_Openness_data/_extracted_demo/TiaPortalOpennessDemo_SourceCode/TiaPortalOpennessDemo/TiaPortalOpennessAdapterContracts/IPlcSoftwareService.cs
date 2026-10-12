using System;
using System.IO;

namespace TiaPortalOpennessAdapterContracts
{
    public interface IPlcSoftwareService : IOpennessService
    {
        void GetStructure<T1, T2, T3, T4>(T1 deviceItem, T2 treeItem, T3 engineeringProjectItem, T4 engineeringProjectModel);

        bool IsKnownObject(Type item);

        bool IsPlcSoftware(object item);

        bool IsPlcStructureDestination(object item);

        bool IsPlcUnitSystemGroup(object item);

        bool CanExportExecute(object item);

        bool ImportElement(object destination, FileInfo importFileInfo, object option);

        bool ImportStructure(object destination, string importFolderPath, object option);

        void ExportStructure(object element, bool exportWithDefaults, bool exportReadOnly, string exportPath, string exportName);

        void CreateGroup(object item, string groupName);

        void CopyLibraryVersionToProject(object copyDestination, object copySource);

        void CreateCopyFromMasterCopy(object copyDestination, object copySource);
    }
}
