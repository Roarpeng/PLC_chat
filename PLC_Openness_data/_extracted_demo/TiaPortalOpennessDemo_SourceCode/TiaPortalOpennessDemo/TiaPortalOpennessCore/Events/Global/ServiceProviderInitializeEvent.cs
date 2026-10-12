using Prism.Events;

namespace TiaPortalOpennessCore.Events.Global
{
    /// <summary>
    /// Global event definition for shard usage between multiple modules.
    /// The event should triggered when the service provider can or should be initialize
    /// </summary>
    public class ServiceProviderInitializeEvent : PubSubEvent
    {
    }
}
