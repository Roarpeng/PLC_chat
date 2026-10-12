using System;
using System.IO;

namespace TiaPortalOpennessAdapterContracts
{
    public interface IHmiTargetService : IOpennessService
    {
        void GetStructure<T1, T2, T3, T4>(T1 deviceItem, T2 treeItem, T3 engineeringProjectItem, T4 engineeringProjectModel);

        bool IsKnownObject(Type item);

        bool IsHmiTarget(object item);

        bool IsHmiTargetStructureDestination(object item);

        bool IsVbScript(object item);

        bool ImportElement(object destination, FileInfo importFileInfo, object option);

        bool ImportStructure(object destination, string importFolderPath, object option);

        void ExportStructure(object element, bool exportWithDefaults, bool exportReadOnly, string exportPath, string exportName);

        void CopyLibraryVersionToProject(object copyDestination, object copySource);

        void CreateCopyFromMasterCopy(object copyDestination, object copySource);
    }
}
