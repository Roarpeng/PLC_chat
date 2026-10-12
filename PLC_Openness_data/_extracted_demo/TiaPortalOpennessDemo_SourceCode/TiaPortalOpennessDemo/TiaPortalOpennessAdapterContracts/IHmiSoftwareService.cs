using System;

namespace TiaPortalOpennessAdapterContracts
{
    public interface IHmiSoftwareService : IOpennessService
    {
        void GetStructure<T1, T2, T3, T4>(T1 deviceItem, T2 treeItem, T3 engineeringProjectItem, T4 engineeringProjectModel);

        bool IsKnownObject(Type item);

        bool IsHmiSoftware(object item);

        object GetHmiSoftware(object item);

        void CreateCopyFromMasterCopy(object copyDestination, object copySource);
    }
}
