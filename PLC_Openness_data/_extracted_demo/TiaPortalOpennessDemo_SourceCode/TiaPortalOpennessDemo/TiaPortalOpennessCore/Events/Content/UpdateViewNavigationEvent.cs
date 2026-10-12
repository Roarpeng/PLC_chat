using Prism.Events;

namespace TiaPortalOpennessCore.Events.Content
{
    /// <summary>
    /// Global event definition for shard usage between multiple modules.
    /// The event should triggered when the view navigation should be update
    /// </summary>
    public class UpdateViewNavigationEvent : PubSubEvent<bool>
    {
    }
}
