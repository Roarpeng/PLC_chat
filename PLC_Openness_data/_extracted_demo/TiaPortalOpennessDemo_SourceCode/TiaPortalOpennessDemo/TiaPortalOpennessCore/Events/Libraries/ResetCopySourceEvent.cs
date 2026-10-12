using Prism.Events;
using TiaPortalOpennessAdapterContracts;

namespace TiaPortalOpennessCore.Events.Libraries
{
    /// <summary>
    /// Global event definition for shard usage between multiple modules.
    /// The event should triggered when the copy source should be reset
    /// </summary>
    public class ResetCopySourceEvent : PubSubEvent<IOpennessDemoNavigationContext>
    {
    }
}
