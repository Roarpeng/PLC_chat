using Prism.Events;
using TiaPortalOpennessAdapterContracts;

namespace TiaPortalOpennessCore.Events.Project
{
    /// <summary>
    /// Global event definition for shard usage between multiple modules.
    /// The event should triggered when an import should be execute
    /// </summary>
    public class ImportElementEvent : PubSubEvent<IOpennessDemoNavigationContext>
    {
    }
}
