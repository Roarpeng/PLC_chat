using Prism.Events;

namespace TiaPortalOpennessCore.Events.TiaPortal
{
    /// <summary>
    /// Global event definition for shard usage between multiple modules.
    /// The event should triggered when the TIA portal is already disconnected
    /// </summary>
    public class TiaPortalDisconnectedEvent : PubSubEvent
    {
    }
}
