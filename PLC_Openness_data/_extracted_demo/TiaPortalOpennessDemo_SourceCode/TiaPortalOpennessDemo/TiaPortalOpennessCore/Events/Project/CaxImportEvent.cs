using Prism.Events;
using TiaPortalOpennessAdapterContracts;

namespace TiaPortalOpennessCore.Events.Project
{
    /// <summary>
    /// Global event definition for shard usage between multiple modules.
    /// The event should triggered when CAx should be import (command execution)
    /// </summary>
    public class CaxImportEvent : PubSubEvent<IOpennessDemoNavigationContext>
    {
    }
}
