using Prism.Events;

namespace TiaPortalOpennessCore.Events.TiaPortal
{
    /// <summary>
    /// Global event definition for shard usage between multiple modules.
    /// The event should triggered when the TIA Portal navigation state should be update
    /// </summary>
    public class TiaPortalStateEvent : PubSubEvent
    {
    }
}
