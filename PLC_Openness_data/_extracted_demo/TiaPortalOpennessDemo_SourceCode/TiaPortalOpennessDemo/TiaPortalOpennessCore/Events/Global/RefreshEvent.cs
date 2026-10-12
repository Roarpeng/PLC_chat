using Prism.Events;
using TiaPortalOpennessAdapterContracts;

namespace TiaPortalOpennessCore.Events.Global
{
    /// <summary>
    /// Global event definition for shard usage between multiple modules.
    /// The event should triggered when the view should be refresh
    /// </summary>
    public class RefreshEvent : PubSubEvent<IOpennessDemoNavigationContext>
    {
    }
}
