using Prism.Events;

namespace TiaPortalOpennessCore.Events.Project
{
    /// <summary>
    /// Global event definition for shard usage between multiple modules.
    /// The event should triggered when the project is already opened
    /// </summary>
    public class ProjectOpenedEvent : PubSubEvent
    {
    }
}
