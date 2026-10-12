namespace TiaPortalOpennessAdapterContracts
{
    public interface ILibraryContext
    {
        IOpennessDemoNavigationContext NavigationContext { get; set; }

        object LibraryItem { get; set; }
    }
}
