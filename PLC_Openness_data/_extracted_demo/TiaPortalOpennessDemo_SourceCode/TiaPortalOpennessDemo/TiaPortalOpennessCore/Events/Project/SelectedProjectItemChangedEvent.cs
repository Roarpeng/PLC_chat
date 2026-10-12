using Prism.Events;
using System.Windows.Controls;

namespace TiaPortalOpennessCore.Events.Project
{
    /// <summary>
    /// Global event definition for shard usage between multiple modules.
    /// The event should triggered when the project tree changes or the project is closed
    /// </summary>
    public class SelectedProjectItemChangedEvent : PubSubEvent<TreeViewItem>
    {
    }
}
