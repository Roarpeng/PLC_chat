using Prism.Events;

namespace TiaPortalOpennessCore.Events.Project
{
    /// <summary>
    /// Global event definition for shard usage between multiple modules.
    /// The event should triggered when the view should be refresh
    /// </summary>
    public class RefreshProjectEvent : PubSubEvent<bool>
    {
    }
}
