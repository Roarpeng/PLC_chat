using Prism.Events;
using TiaPortalOpennessInfrastructure.Utils;

namespace TiaPortalOpennessCore.Events.Shell
{
    /// <summary>
    /// Global event definition for shard usage between multiple modules.
    /// The event should triggered when a long run process is done.
    /// </summary>
    public class DoneEvent : PubSubEvent<ProcessInfo>
    {
    }
}
