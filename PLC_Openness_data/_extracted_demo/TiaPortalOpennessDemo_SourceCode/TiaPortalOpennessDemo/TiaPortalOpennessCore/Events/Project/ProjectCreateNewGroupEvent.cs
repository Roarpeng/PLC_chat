using Prism.Events;
using TiaPortalOpennessAdapterContracts;

namespace TiaPortalOpennessCore.Events.Project
{
    /// <summary>
    /// Global event definition for shard usage between multiple modules.
    /// The event should triggered when an new object group should be create
    /// </summary>
    public class ProjectCreateNewGroupEvent : PubSubEvent<IOpennessDemoNavigationContext>
    {
    }
}
