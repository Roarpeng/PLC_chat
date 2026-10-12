using Prism.Events;
using System.Windows.Controls;

namespace TiaPortalOpennessCore.Events.Libraries
{
    /// <summary>
    /// Global event definition for shard usage between multiple modules.
    /// The event should triggered when the selected system library has changed
    /// </summary>
    public class SelectedSystemLibraryChangedEvent : PubSubEvent<TreeViewItem>
    {
    }
}
