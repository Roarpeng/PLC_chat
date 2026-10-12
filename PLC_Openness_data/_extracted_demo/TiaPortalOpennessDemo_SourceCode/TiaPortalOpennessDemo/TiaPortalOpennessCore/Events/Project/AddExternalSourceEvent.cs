using Prism.Events;
using TiaPortalOpennessAdapterContracts;

namespace TiaPortalOpennessCore.Events.Project
{
    /// <summary>
    /// Global event definition for shard usage between multiple modules.
    /// The event should triggered when an external source should be add (command execution)
    /// </summary>
    public class AddExternalSourceEvent : PubSubEvent<IOpennessDemoNavigationContext>
    {
    }
}
