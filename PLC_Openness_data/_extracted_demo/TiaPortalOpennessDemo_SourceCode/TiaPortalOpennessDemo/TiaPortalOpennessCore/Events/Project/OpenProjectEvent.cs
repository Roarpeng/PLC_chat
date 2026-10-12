using Prism.Events;
using TiaPortalOpennessAdapterContracts;

namespace TiaPortalOpennessCore.Events.Project
{
    /// <summary>
    /// Global event definition for shard usage between multiple modules.
    /// The event should triggered when an project should be open
    /// </summary>
    public class OpenProjectEvent : PubSubEvent<IOpennessDemoNavigationContext>
    {
    }
}
