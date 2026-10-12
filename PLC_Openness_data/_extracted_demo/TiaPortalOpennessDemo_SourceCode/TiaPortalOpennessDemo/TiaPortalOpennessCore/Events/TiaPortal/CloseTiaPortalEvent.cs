using Prism.Events;
using TiaPortalOpennessAdapterContracts;

namespace TiaPortalOpennessCore.Events.TiaPortal
{
    /// <summary>
    /// Global event definition for shard usage between multiple modules.
    /// The event should triggered when the TIA Portal should be close
    /// </summary>
    public class CloseTiaPortalEvent : PubSubEvent<IOpennessDemoNavigationContext>
    {
    }
}
