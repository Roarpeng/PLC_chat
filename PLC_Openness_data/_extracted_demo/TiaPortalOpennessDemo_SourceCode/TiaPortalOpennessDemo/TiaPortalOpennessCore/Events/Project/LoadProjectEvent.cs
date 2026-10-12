using Prism.Events;

namespace TiaPortalOpennessCore.Events.Project
{
    /// <summary>
    /// Global event definition for shard usage between multiple modules.
    /// The event should triggered when the project content is loaded, the boolean parameter indicates whether the logical tree is loaded or not
    /// </summary>
    public class LoadProjectEvent : PubSubEvent<bool>
    {
    }
}
