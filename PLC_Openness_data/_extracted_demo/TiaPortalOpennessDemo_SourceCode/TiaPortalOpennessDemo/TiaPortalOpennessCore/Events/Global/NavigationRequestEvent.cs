using Prism.Events;

namespace TiaPortalOpennessCore.Events.Global
{
    /// <summary>
    /// Global event definition for shard usage between multiple modules.
    /// The event should triggered when navigation is requested
    /// </summary>
    public class NavigationRequestEvent : PubSubEvent<string>
    {
    }
}
