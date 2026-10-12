using Prism.Events;

namespace TiaPortalOpennessCore.Events.Session
{
    /// <summary>
    /// Global event definition for shard usage between multiple modules.
    /// The event should triggered when an multi user project (local session) should be load
    /// </summary>
    public class LoadMultiuserProjectEvent : PubSubEvent<bool>
    {
    }
}
