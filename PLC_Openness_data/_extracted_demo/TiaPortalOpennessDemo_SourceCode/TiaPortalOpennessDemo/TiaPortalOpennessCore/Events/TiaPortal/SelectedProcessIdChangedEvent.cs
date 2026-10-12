using Prism.Events;

namespace TiaPortalOpennessCore.Events.TiaPortal
{
    /// <summary>
    /// Global event definition for shard usage between multiple modules.
    /// The event should triggered when the selected process id is changed.
    /// </summary>
    public class SelectedProcessIdChangedEvent : PubSubEvent
    {
    }
}
