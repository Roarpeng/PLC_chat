using Prism.Events;
using TiaPortalOpennessAdapterContracts;

namespace TiaPortalOpennessCore.Events.Project
{
    /// <summary>
    /// Global event definition for shard usage between multiple modules.
    /// The event should triggered when the project should be save
    /// </summary>
    public class SaveProjectEvent : PubSubEvent<IOpennessDemoNavigationContext>
    {
    }
}
