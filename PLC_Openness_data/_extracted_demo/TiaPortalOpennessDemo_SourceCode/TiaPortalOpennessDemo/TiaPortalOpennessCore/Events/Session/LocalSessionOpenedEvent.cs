using Prism.Events;

namespace TiaPortalOpennessCore.Events.Session
{
    /// <summary>
    /// Global event definition for shard usage between multiple modules.
    /// The event should triggered when the local session is already opened
    /// </summary>
    public class LocalSessionOpenedEvent : PubSubEvent
    {
    }
}
