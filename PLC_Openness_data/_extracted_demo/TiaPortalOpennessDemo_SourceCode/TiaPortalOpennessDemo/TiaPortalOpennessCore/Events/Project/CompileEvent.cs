using Prism.Events;
using TiaPortalOpennessAdapterContracts;

namespace TiaPortalOpennessCore.Events.Project
{
    /// <summary>
    /// Global event definition for shard usage between multiple modules.
    /// The event should triggered when an selected element should be compile
    /// </summary>
    public class CompileEvent : PubSubEvent<IOpennessDemoNavigationContext>
    {
    }
}
