using Prism.Events;
using TiaPortalOpennessAdapterContracts;

namespace TiaPortalOpennessCore.Events.Project
{
    /// <summary>
    /// Global event definition for shard usage between multiple modules.
    /// The event should triggered when a new project is created
    /// </summary>
    public class CreateNewProjectEvent : PubSubEvent<IOpennessDemoNavigationContext>
    {
    }
}
