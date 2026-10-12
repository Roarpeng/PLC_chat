using Prism.Events;
using TiaPortalOpennessAdapterContracts;

namespace TiaPortalOpennessCore.Events.Project
{
    /// <summary>
    /// Global event definition for shard usage between multiple modules.
    /// The event should triggered when the TIA portal network editor should be open
    /// </summary>
    public class OpenNetworkEditorEvent : PubSubEvent<IOpennessDemoNavigationContext>
    {
    }
}
