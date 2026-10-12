using Prism.Events;

namespace TiaPortalOpennessCore.Events.Content
{
    /// <summary>
    /// Global event definition for shard usage between multiple modules.
    /// The event should triggered when the project tree changes or the project is closed
    /// </summary>
    public class ResetContentEvent : PubSubEvent
    {
    }
}
