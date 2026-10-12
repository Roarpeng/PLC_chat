using Prism.Events;
using TiaPortalOpennessAdapterContracts;

namespace TiaPortalOpennessCore.Events.Project
{
    /// <summary>
    /// Global event definition for shard usage between multiple modules.
    /// The event should triggered when an TIA portal editor should be open
    /// </summary>
    public class OpenEditorEvent : PubSubEvent<IOpennessDemoNavigationContext>
    {
    }
}
