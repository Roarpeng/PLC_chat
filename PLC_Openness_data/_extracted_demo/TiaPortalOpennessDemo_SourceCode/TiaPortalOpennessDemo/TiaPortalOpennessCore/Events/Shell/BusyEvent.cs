using Prism.Events;
using TiaPortalOpennessInfrastructure.Utils;

namespace TiaPortalOpennessCore.Events.Shell
{
    /// <summary>
    /// Global event definition for shard usage between multiple modules.
    /// The event should triggered when a long run process is started, the string parameter are the process infos
    /// </summary>
    public class BusyEvent : PubSubEvent<ProcessInfo>
    {
    }
}
