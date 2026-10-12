namespace TiaPortalOpennessAdapterContracts
{
    public interface IStartdriveService : IOpennessService
    {
        void GetStructure<T1, T2, T3, T4>(T1 deviceItem, T2 treeItem, T3 engineeringProjectItem, T4 engineeringProjectModel);
    }
}
