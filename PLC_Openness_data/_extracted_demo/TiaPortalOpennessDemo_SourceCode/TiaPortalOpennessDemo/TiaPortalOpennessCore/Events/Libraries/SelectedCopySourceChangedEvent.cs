using Prism.Events;
using TiaPortalOpennessAdapterContracts;

namespace TiaPortalOpennessCore.Events.Libraries
{
    /// <summary>
    /// Global event definition for shard usage between multiple modules.
    /// The event should triggered when the selected copy source has changed
    /// </summary>
    public class SelectedCopySourceChangedEvent : PubSubEvent<ILibraryContext>
    {
    }
}
