using Prism.Events;
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Reflection;
using System.Windows;
using TiaPortalOpennessAdapter.Contracts;
using TiaPortalOpennessAdapterContracts;
using TiaPortalOpennessCore.Events.Global;
using TiaPortalOpennessInfrastructure.Contracts;
using TiaPortalOpennessInfrastructure.Exceptions;
using TiaPortalOpennessInfrastructure.Utils;

namespace TiaPortalOpennessModuleProvider.Services
{
    /// <summary>
    /// Implementation of the openness module provider
    /// </summary>
    public class OpennessModuleProvider : IModuleProvider
    {
        #region fields

        private readonly IEventAggregator _eventAggregator;
        private readonly ITraceLogService _traceLogService;
        //private string _qualifiedInterface;

        #endregion // fields

        #region ctor

        /// <summary>
        /// Default constructor with constructor injection 
        /// </summary>
        /// <param name="eventAggregator"></param>
        /// <param name="traceLogService"></param>
        public OpennessModuleProvider(IEventAggregator eventAggregator, ITraceLogService traceLogService)
        {
            _eventAggregator   = eventAggregator;
            _traceLogService   = traceLogService;

            OpennessAssemblies = new List<Assembly>();
            OpennessServices   = new List<IOpennessService>();
            OpennessTypes      = new Dictionary<string, Type>();
        }

        #endregion // ctor

        #region propties

        /// <summary>
        /// Openness service catalog
        /// </summary>
        public IList<IOpennessService> OpennessServices { get; }

        /// <summary>
        /// Openness assembly (module) catalog
        /// </summary>
        public IList<Assembly> OpennessAssemblies { get; }

        public Dictionary<string, Type> OpennessTypes { get; }

        #endregion // properties

        #region methods

        /// <summary>
        /// Add module to assembly catalog
        /// </summary>
        /// <param name="assembly"></param>
        public void AddModule(Assembly assembly)
        {
            if (!OpennessAssemblies.Contains(assembly))
            {
                OpennessAssemblies.Add(assembly);
            }
        }

        /// <summary>
        /// Config services for selected modules and options.
        /// Instance will be create
        /// </summary>
        /// <param name="engineeringVersion"></param>
        /// <param name="opennessVersion"></param>
        public void ConfigureServices(string engineeringVersion, string opennessVersion)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(OpennessModuleProvider) + " - " + nameof(ConfigureServices) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var sw1 = Stopwatch.StartNew();

                foreach (var assembly in OpennessAssemblies)
                {
                    var typeCollection = assembly.GetExportedTypes();
                    foreach (var typeInfo in typeCollection)
                    {
                        var nameSpace = "V" + opennessVersion.Replace('.', '_');

                        if (typeInfo.FullName != null && typeInfo.FullName.Contains(nameSpace))
                        {
                            var type = assembly.GetType(typeInfo.FullName);
                            if (type != null && typeInfo.DeclaringType == null)
                            {
                                Debug.WriteLine(typeInfo.FullName);

                                var instance = Activator.CreateInstance(type, _traceLogService);

                                if (instance is IOpennessService opennessService)
                                {
                                    OpennessServices.Add(opennessService);
                                    OpennessTypes.Add(type.Name, opennessService.GetType());
                                }
                            }
                        }
                    }
                }

                sw1.Stop();
                Debug.WriteLine($"ConfigureServices with Activator.CreateInstance: " + $"{(double)sw1.ElapsedMilliseconds} milliseconds per object");

                if (OpennessServices.Count > 0)
                {
                    _eventAggregator.GetEvent<ServiceProviderInitializeEvent>().Publish();
                }
            }
            catch (OpennessApiException)
            {
                throw;
            }
            catch (Exception exception)
            {
                throw OpennessApiExceptionHandler.CatchedException(exception);
            }
        }

        /// <summary>
        /// Retrieve service by type
        /// </summary>
        /// <typeparam name="T"></typeparam>
        /// <param name="type"></param>
        /// <returns></returns>
        public object GetService<T>(T type)
        {
            foreach (var service in OpennessServices)
            {
                var t = service.GetType();
                var interfaceFullName = type.ToString();
                var interfaces = t.GetInterfaces();

                foreach (var item in interfaces)
                {
                    if (item.FullName == interfaceFullName)
                    {
                        return service;
                    }
                }
            }

            return null;
        }

        /// <summary>
        /// Retrieve service by name
        /// </summary>
        /// <param name="typeName"></param>
        /// <returns></returns>
        public object GetService(string typeName)
        {
            OpennessTypes.TryGetValue(typeName, out var type);

            if (type != null)
            {
                foreach (var service in OpennessServices)
                {
                    Type serviceType = service.GetType();
                    if (type.FullName == serviceType.FullName)
                    {
                        return service;
                    }
                }
                return type;
            }

            return null;
        }

        #endregion // methods

        #region trace

        /// <summary>
        /// Execute writing trace log in different thread.
        /// </summary>
        /// <param name="traceLog"></param>
        private void WriteTraceLogProxy(string traceLog)
        {
            Application.Current.Dispatcher.Invoke(delegate
            {
                _traceLogService.Write(traceLog);
            });
        }

        #endregion // trace
    }
}
