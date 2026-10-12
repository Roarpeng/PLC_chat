using Prism.Events;
using TiaPortalOpennessAdapterContracts;

namespace TiaPortalOpennessCore.Events.TiaPortal
{
    /// <summary>
    /// Global event definition for shard usage between multiple modules.
    /// The event should triggered when the application should be disconnect from a TIA portal instance.
    /// </summary>
    public class DisconnectTiaPortalEvent : PubSubEvent<IOpennessDemoNavigationContext>
    {
    }
}
