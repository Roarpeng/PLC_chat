using Prism.Events;
using TiaPortalOpennessAdapterContracts;

namespace TiaPortalOpennessCore.Events.Session
{
    /// <summary>
    /// Global event definition for shard usage between multiple modules.
    /// The event should triggered when a local session should be open, the boolean parameter indicates whether the logical tree should be loaded or not
    /// </summary>
    public class OpenLocalSessionEvent : PubSubEvent<IOpennessDemoNavigationContext>
    {
    }
}
