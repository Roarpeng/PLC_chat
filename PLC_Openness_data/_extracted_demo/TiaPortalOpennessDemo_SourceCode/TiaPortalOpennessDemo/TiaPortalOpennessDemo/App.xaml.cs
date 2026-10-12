using Prism.Ioc;
using Prism.Modularity;
using Prism.Regions;
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Reflection;
using System.Windows;
using System.Windows.Controls;
using TiaPortalOpennessAdapter.Contracts;
using TiaPortalOpennessAdapter.Models;
using TiaPortalOpennessAdapter.Utils;
using TiaPortalOpennessAdapterContracts;
using TiaPortalOpennessCore;
using TiaPortalOpennessCore.ViewModels;
using TiaPortalOpennessDemo.Adapter;
using TiaPortalOpennessDemo.Properties;
using TiaPortalOpennessDemo.Services;
using TiaPortalOpennessDemo.ViewModels;
using TiaPortalOpennessDemo.Views;
using TiaPortalOpennessInfrastructure.Constants;
using TiaPortalOpennessInfrastructure.Contracts;
using TiaPortalOpennessInfrastructure.Exceptions;
using TiaPortalOpennessInfrastructure.Services;
using TiaPortalOpennessInfrastructure.Utils;
using TiaPortalOpennessModuleProvider.Services;

namespace TiaPortalOpennessDemo
{
    /// <summary>
    /// Interaction logic for App.xaml
    /// </summary>
    public partial class App
    {
        #region fields

        private ShellWindow _shellWindow;
        private ITraceLogService _traceLogService;
        private bool? _dialogResult = false;

        #endregion // fields

        #region ctor

        /// <summary>
        /// Default constructor
        /// </summary>
        public App()
        {

            AppDomain.CurrentDomain.AssemblyResolve += Resolver.OnResolve;
            AppDomain.CurrentDomain.ReflectionOnlyAssemblyResolve += Resolver.OnResolve;

            //dialogResult = GetSelectedAssemblyVersions();
        }

        #endregion // ctor

        #region overrides

        /// <summary>
        /// Create the first and only shell window
        /// </summary>
        /// <returns>The shell window</returns>
        protected override Window CreateShell()
        {
            _shellWindow = Container.Resolve<ShellWindow>();
            return _shellWindow;
        }

        /// <summary>
        /// Registrations of types and instances for late binding
        /// </summary>
        /// <param name="containerRegistry">The IoC container registrations</param>
        protected override void RegisterTypes(IContainerRegistry containerRegistry)
        {
            containerRegistry.RegisterSingleton<RegionNames>();
            containerRegistry.RegisterSingleton<StackPanelRegionAdapter>();

            containerRegistry.RegisterSingleton<ITraceLogService, TraceLogService>();
            containerRegistry.RegisterSingleton<ISettingsService, SettingsService>();
            containerRegistry.RegisterSingleton<IOpennessDemoNavigationContext, OpennessDemoNavigationContext>();

            containerRegistry.RegisterSingleton<IOpennessDemoModel, OpennessDemoModel>();
            containerRegistry.RegisterSingleton<IModuleProvider, OpennessModuleProvider>();
        }

        /// <summary>
        /// Create the module catalog as configuration for the entire application
        /// </summary>
        /// <returns>The module catalog</returns>
        protected override IModuleCatalog CreateModuleCatalog()
        {
            return new DirectoryModuleCatalog() { ModulePath = @".\Modules" };
        }

        /// <summary>
        /// Is needed to be register custom region adapter
        /// </summary>
        /// <param name="regionAdapterMappings">The region mapping registrations</param>
        protected override void ConfigureRegionAdapterMappings(RegionAdapterMappings regionAdapterMappings)
        {
            base.ConfigureRegionAdapterMappings(regionAdapterMappings);
            regionAdapterMappings.RegisterMapping(typeof(StackPanel), Container.Resolve<StackPanelRegionAdapter>());
        }

        /// <summary>
        /// Initialize the application and show pre selection dialogs
        /// </summary>
        protected override void OnInitialized()
        {
            try
            {
                _traceLogService = Container.Resolve<ITraceLogService>();

                if (!Resolver.IsOpennessInstalled())
                {
                    // Message and Shutdown...
                    MessageBox.Show("TIA Portal Openness API isn't installed!", "Error", MessageBoxButton.OK, MessageBoxImage.Error);
                    Shutdown();
                }

                if (_dialogResult != null && (bool)_dialogResult)
                {
                    _dialogResult = GetSelectedModulesAndOptions();
                }

                // ReSharper disable once ConditionIsAlwaysTrueOrFalse
                if (_dialogResult == null || (_dialogResult != null && (bool)!_dialogResult))
                {
                    Shutdown();
                }

                ((ShellWindowViewModel)_shellWindow.DataContext).InitEvents();

                base.OnInitialized();

            }
            catch (Exception ex)
            {
                Debug.WriteLine(ex.Message);
                Debug.WriteLine(ex.StackTrace);
                MessageBox.Show("Please delete the 'TiaPortalOpennessDemo.exe.config' file and start the application again.", "Error", MessageBoxButton.OK, MessageBoxImage.Error);
                Shutdown();
            }
        }

        protected override void OnStartup(StartupEventArgs e)
        {
            _dialogResult = GetSelectedAssemblyVersions();

            base.OnStartup(e);
        }

        protected override void ConfigureModuleCatalog(IModuleCatalog moduleCatalog)
        {
            var type = typeof(TiaPortalOpennessCoreModule);
            moduleCatalog.AddModule(
                new ModuleInfo()
                {
                    ModuleName = type.Name,
                    ModuleType = type.AssemblyQualifiedName
                });

            base.ConfigureModuleCatalog(moduleCatalog);
        }

        #endregion // overrides

        #region methods

        /// <summary>
        /// Shows the pre selection dialog to select the api version to be loaded
        /// </summary>
        /// <returns>Dialog result</returns>
        private bool? GetSelectedAssemblyVersions()
        {
            _dialogResult = true;

            if (!Settings.Default.HidePreSelectionAssemblyVersion)
            {
                var preSelectionAssemblyVersion = new PreSelectionAssemblyVersionView
                {
                    DataContext = new PreSelectionAssemblyVersionViewModel()
                };

                preSelectionAssemblyVersion.ShowDialog();
                _dialogResult = preSelectionAssemblyVersion.DialogResult;
            }

            var selectedEngineeringVersion = Settings.Default.SelectedEngineeringVersion;
            var selectedOpennessApiVersion = Settings.Default.SelectedOpennessApiVersion;

            if (!string.IsNullOrEmpty(selectedEngineeringVersion) && !string.IsNullOrEmpty(selectedOpennessApiVersion))
            {
                Resolver.GetAssemblyPath(selectedEngineeringVersion, selectedOpennessApiVersion);
            }
            else
            {
                _dialogResult = false;
            }

            return _dialogResult;
        }

        /// <summary>
        /// Shows the pre selection dialog to select the modules that to be loaded
        /// </summary>
        /// <returns>Dialog result</returns>
        private bool? GetSelectedModulesAndOptions()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(App) + " - " + nameof(GetSelectedModulesAndOptions) };
            try
            {
                WriteTraceLogProxy(processInfo.ProcessMessage);

                var engineeringVersion = Settings.Default.SelectedEngineeringVersion.Split('.');

                if (!Int32.TryParse(engineeringVersion[0], out var version) || version < 15)
                {
                    MessageBox.Show("The minimum version required is not installed or has not been selected!", "Error", MessageBoxButton.OK, MessageBoxImage.Error);
                    return false;
                }

                var preConfigurationEnvironment = Container.Resolve<PreConfigurationEnvironmentView>();
                preConfigurationEnvironment.ShowDialog();
                var result = preConfigurationEnvironment.DialogResult;

                if (preConfigurationEnvironment.DataContext is PreConfigurationEnvironmentViewModel viewModel)
                {
                    ((ShellWindowViewModel)_shellWindow.DataContext).InitEnvironment(viewModel.BaseServiceFound);

                    var baseModules = viewModel.BaseModules.ToList();

                    var modulesAndOptions = (from item in viewModel.ModulesAndOptions
                                             where item.IsSelected
                                             select item).ToList();

                    LoadModulesAndOptions(baseModules, modulesAndOptions);
                }

                return result;
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, SharedResourceDictionary.Properties.Resources.Openness_api_exception_occurred, MessageBoxButton.OK, MessageBoxImage.Error);
            }

            return false;
        }

        /// <summary>
        /// Load the selected modules
        /// </summary>
        /// <param name="baseModules"></param>
        /// <param name="modulesAndOptions">Selected module to be loaded</param>
        private void LoadModulesAndOptions(IList<TiaPortalModulesAndOptions> baseModules, IList<TiaPortalModulesAndOptions> modulesAndOptions)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(App) + " - " + nameof(LoadModulesAndOptions) };
            try
            {
                WriteTraceLogProxy(processInfo.ProcessMessage);
                var moduleProvider = Container.Resolve<IModuleProvider>();
                bool configModuleProvider = false;


                if (baseModules != null || modulesAndOptions != null && moduleProvider != null)
                {
                    foreach (var module in baseModules)
                    {
                        var thisAssembly = Assembly.LoadFrom(module.Location);
                        moduleProvider.AddModule(thisAssembly);
                        configModuleProvider = true;
                    }

                    foreach (var module in modulesAndOptions)
                    {
                        var thisAssembly = Assembly.LoadFrom(module.Location);
                        moduleProvider.AddModule(thisAssembly);
                        configModuleProvider = true;
                    }

                    if (configModuleProvider)
                    {
                        moduleProvider.ConfigureServices(Settings.Default.SelectedEngineeringVersion, Settings.Default.SelectedOpennessApiVersion);
                    }
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
        /// Get an application setting by name
        /// </summary>
        /// <param name="settingName">Name of the setting</param>
        /// <returns>Value of the named setting</returns>
        public string GetSettingByName(string settingName)
        {
            return Settings.Default[settingName].ToString();
        }

        #endregion // methods

        #region trace

        /// <summary>
        /// Execute writing trace log in different thread.
        /// </summary>
        /// <param name="traceLog"></param>
        private void WriteTraceLogProxy(string traceLog)
        {
            Current.Dispatcher.Invoke(delegate
            {
                _traceLogService.Write(traceLog);
            });
        }

        /// <summary>
        /// Execute writing trace log in different thread for all inner exceptions
        /// </summary>
        /// <param name="exception"></param>
        protected virtual void WriteTraceLogProxy(Exception exception)
        {
            if (!string.IsNullOrEmpty(exception.Message))
            {
                Application.Current.Dispatcher.Invoke(delegate
                {
                    _traceLogService.Write(exception.Message);
                });

            }
            if (exception.InnerException != null && !string.IsNullOrEmpty(exception.InnerException.Message))
            {
                WriteTraceLogProxy(exception.InnerException);
            }
        }


        #endregion // trace
    }
}
