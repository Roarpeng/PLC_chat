using Prism.Events;
using TiaPortalOpennessAdapterContracts;

namespace TiaPortalOpennessCore.Events.Session
{
    /// <summary>
    /// Global event definition for shard usage between multiple modules.
    /// The event should triggered when a local session should be save
    /// </summary>
    public class SaveLocalSessionEvent : PubSubEvent<IOpennessDemoNavigationContext>
    {
    }
}
