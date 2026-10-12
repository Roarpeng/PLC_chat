using Prism.Events;
using TiaPortalOpennessAdapterContracts;

namespace TiaPortalOpennessCore.Events.Project
{
    /// <summary>
    /// Global event definition for shard usage between multiple modules.
    /// The event should triggered when an block should be generate from source object
    /// </summary>
    public class GenerateBlockFromSourceEvent : PubSubEvent<IOpennessDemoNavigationContext>
    {
    }
}
