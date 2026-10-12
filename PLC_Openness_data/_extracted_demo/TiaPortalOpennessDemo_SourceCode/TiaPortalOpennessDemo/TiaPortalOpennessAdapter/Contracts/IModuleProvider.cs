using System.Collections.Generic;
using System.Reflection;
using TiaPortalOpennessAdapterContracts;

namespace TiaPortalOpennessAdapter.Contracts
{
    /// <summary>
    /// Interface definition for the module provider
    /// </summary>
    public interface IModuleProvider
    {
        /// <summary>
        /// Collection of available services
        /// </summary>
        IList<IOpennessService> OpennessServices { get; }

        /// <summary>
        /// Collection of loaded modules
        /// </summary>
        IList<Assembly> OpennessAssemblies { get; }

        /// <summary>
        /// Add a module to the collection of loaded modules
        /// </summary>
        /// <param name="assembly"></param>
        void AddModule(Assembly assembly);

        /// <summary>
        /// Config the module provider and creates the service instances
        /// </summary>
        /// <param name="engineeringVersion">engineering version to be use</param>
        /// <param name="opennessVersion">openness api version to be use</param>
        void ConfigureServices(string engineeringVersion, string opennessVersion);

        /// <summary>
        /// Get a service by type
        /// </summary>
        /// <typeparam name="T"></typeparam>
        /// <param name="type">type of the service</param>
        /// <returns>service object</returns>
        object GetService<T>(T type);

        /// <summary>
        /// Get a service by name
        /// </summary>
        /// <param name="typeName">name of the service</param>
        /// <returns>service object</returns>
        object GetService(string typeName);
    }
}
