using Prism.Events;
using System.Windows.Controls;

namespace TiaPortalOpennessCore.Events.Project
{
    /// <summary>
    /// Global event definition for shard usage between multiple modules.
    /// The event should triggered when an entry is selected in the project tree.
    /// The payload is the selected tree item.
    /// </summary>
    public class LoadContentEvent : PubSubEvent<TreeViewItem>
    {
    }
}
