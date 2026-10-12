using Prism.Events;

namespace TiaPortalOpennessCore.Events.TiaPortal
{
    /// <summary>
    /// Global event definition for shard usage between multiple modules.
    /// The event should triggered when the TIA portal is already closed
    /// </summary>
    public class TiaPortalClosedEvent : PubSubEvent
    {
    }
}
