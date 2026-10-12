using Prism.Events;

namespace TiaPortalOpennessCore.Events.Libraries
{
    /// <summary>
    /// Global event definition for shard usage between multiple modules.
    /// The event should triggered when the library context should be refresh
    /// </summary>
    public class RefreshLibraryEvent : PubSubEvent<bool>
    {
    }
}
