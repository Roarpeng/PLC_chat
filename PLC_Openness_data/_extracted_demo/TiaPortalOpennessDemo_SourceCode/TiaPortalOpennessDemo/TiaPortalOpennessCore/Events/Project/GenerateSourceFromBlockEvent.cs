using Prism.Events;
using TiaPortalOpennessAdapterContracts;

namespace TiaPortalOpennessCore.Events.Project
{
    /// <summary>
    /// Global event definition for shard usage between multiple modules.
    /// The event should triggered when an source should be generate from block object
    /// </summary>
    public class GenerateSourceFromBlockEvent : PubSubEvent<IOpennessDemoNavigationContext>
    {
    }
}
