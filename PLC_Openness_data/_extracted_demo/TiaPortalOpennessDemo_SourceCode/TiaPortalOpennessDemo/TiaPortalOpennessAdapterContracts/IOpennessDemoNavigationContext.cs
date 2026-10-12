namespace TiaPortalOpennessAdapterContracts
{
    public interface IOpennessDemoNavigationContext
    {
        bool IsLocalSession { get; set; }

        bool ShowLogicalTree { get; set; }

        string NavigationTarget { get; set; }
    }
}
