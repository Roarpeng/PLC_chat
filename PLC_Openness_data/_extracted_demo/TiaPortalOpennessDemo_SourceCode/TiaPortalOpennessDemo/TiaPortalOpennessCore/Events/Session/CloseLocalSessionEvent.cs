using Prism.Events;
using TiaPortalOpennessAdapterContracts;

namespace TiaPortalOpennessCore.Events.Session
{
    /// <summary>
    /// Global event definition for shard usage between multiple modules.
    /// The event should triggered when the local session is closed, the boolean parameter indicates which tree is loaded
    /// </summary>
    public class CloseLocalSessionEvent : PubSubEvent<IOpennessDemoNavigationContext>
    {
    }
}
