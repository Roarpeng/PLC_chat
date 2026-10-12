using Prism.Events;

namespace TiaPortalOpennessCore.Events.Global
{
    /// <summary>
    /// Global event definition for shard usage between multiple modules.
    /// The event should triggered when the settings editor should be open
    /// </summary>
    public class EditSettingsEvent : PubSubEvent
    {
    }
}
