using Prism.Events;
using TiaPortalOpennessAdapterContracts;

namespace TiaPortalOpennessCore.Events.Global
{
    /// <summary>
    /// Global event definition for shard usage between multiple modules.
    /// The event should triggered when the selected view type (logical or physical tree) has changed
    /// </summary>
    public class SetNavigationPathEvent : PubSubEvent<IOpennessDemoNavigationContext>
    {
    }
}
