using Prism.Commands;
using Prism.Events;
using Prism.Ioc;
using Prism.Mvvm;
using System;
using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using SharedResourceDictionary.Properties;
using TiaPortalModule.Views;
using TiaPortalOpennessAdapter.Contracts;
using TiaPortalOpennessAdapter.Services;
using TiaPortalOpennessAdapter.Utils;
using TiaPortalOpennessAdapterBase.Enums;
using TiaPortalOpennessAdapterContracts;
using TiaPortalOpennessCore.Events.Content;
using TiaPortalOpennessCore.Events.Global;
using TiaPortalOpennessCore.Events.Project;
using TiaPortalOpennessCore.Events.Shell;
using TiaPortalOpennessCore.Events.TiaPortal;
using TiaPortalOpennessInfrastructure.Constants;
using TiaPortalOpennessInfrastructure.Contracts;
using TiaPortalOpennessInfrastructure.Utils;

namespace TiaPortalModule.ViewModels
{
    /// <summary>
    /// Implementation of TIA Portal instance without API types
    /// </summary>
    public class TiaPortalViewModel : BindableBase
    {
        #region fields

        private readonly IEventAggregator _eventAggregator;
        private readonly IModuleProvider _moduleProvider;
        private readonly IContainerProvider _containerProvider;
        private readonly ITraceLogService _traceLogService;
        private readonly ISettingsService _settingsService;

        private IOpennessDemoModel _opennessDemoModel;
        private IOpennessDemoNavigationContext _opennessDemoNavigationContext;

        private ObservableCollection<string> _engineeringVersions = new ObservableCollection<string>();
        private ObservableCollection<string> _assemblyVersions = new ObservableCollection<string>();

        private string _selectedVersion;
        private string _currentProcessId;
        private string _selectedProcessInformation;

        private ITiaPortalServiceProvider _tiaPortalServiceProvider;
        private IProjectServiceProvider _projectServiceProvider;

        #endregion // fields

        #region ctor

        /// <summary>
        /// Constructor with initialization
        /// </summary>
        /// <param name="eventAggregator">Event aggregator to publish and subscribe events</param>
        /// <param name="moduleProvider">Module provider to get services</param>
        /// <param name="containerProvider">Container to resolve view</param>
        /// <param name="traceLogService">Trace log service</param>
        /// <param name="settingsService">Settings service to access the application settings</param>
        /// <param name="opennessDemoModel"></param>
        public TiaPortalViewModel(IEventAggregator eventAggregator, IModuleProvider moduleProvider, IContainerProvider containerProvider, ITraceLogService traceLogService, ISettingsService settingsService, IOpennessDemoModel opennessDemoModel, IOpennessDemoNavigationContext opennessDemoNavigationContext)
        {
            _eventAggregator = eventAggregator;
            _moduleProvider = moduleProvider;
            _containerProvider = containerProvider;
            _traceLogService = traceLogService;
            _settingsService = settingsService;
            _opennessDemoModel = opennessDemoModel;
            _opennessDemoNavigationContext = opennessDemoNavigationContext;

            _eventAggregator.GetEvent<ServiceProviderInitializeEvent>().Subscribe(InitServiceProvider);
            _eventAggregator.GetEvent<EditSettingsEvent>().Subscribe(EditSettings);

            _eventAggregator.GetEvent<OpenTiaPortalEvent>().Subscribe(OpenTiaPortalAsync);
            _eventAggregator.GetEvent<ConnectTiaPortalEvent>().Subscribe(ConnectTiaPortalAsync);
            _eventAggregator.GetEvent<DisconnectTiaPortalEvent>().Subscribe(DisconnectTiaPortalAsync);
            _eventAggregator.GetEvent<CloseTiaPortalEvent>().Subscribe(CloseTiaPortalAsync);

            _eventAggregator.GetEvent<TiaPortalStateEvent>().Subscribe(GetTiaPortalState);
            _eventAggregator.GetEvent<TiaPortalConnectedEvent>().Subscribe(GetTiaPortalState);
            _eventAggregator.GetEvent<TiaPortalDisconnectedEvent>().Subscribe(GetTiaPortalState);
            _eventAggregator.GetEvent<TiaPortalClosedEvent>().Subscribe(GetTiaPortalState);

            _eventAggregator.GetEvent<ExitEvent>().Subscribe(DoExit);

            SelectedIndexChangedProcessesCommand = new DelegateCommand<object>(SelectionIndexChangedProcesses);

            ConnectTiaPortalCommand = new DelegateCommand(ConnectTiaPortal).ObservesCanExecute(() => OpennessDemoModel.PortalAvailable);

            GetEngineeringVersions();
        }

        /// <summary>
        /// Constructor for design time only.
        /// </summary>
        /// <param name="selectedTiaPortalMode">Sample data</param>
        /// <param name="currentProcessId">Sample data</param>
        /// <param name="opennessDemoModel">Sample data</param>
        [DesignOnly(true)]
        internal TiaPortalViewModel(TiaPortalStartMode selectedTiaPortalMode, string currentProcessId, IOpennessDemoModel opennessDemoModel)
        {
            try
            {
                _currentProcessId = currentProcessId;
                OpennessDemoModel = opennessDemoModel;

                if (!IsDesignTime)
                {
                    throw new InvalidOperationException(ExceptionInfo.StrDesignTimeOnlyConstructorException);
                }
            }
            catch (Exception ex)
            {
                MessageBox.Show($"{ex.Message}{Environment.NewLine}{Environment.NewLine}Details:{Environment.NewLine}{ex}", "TIA Portal Openness Demo", MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }

        private void InitServiceProvider()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(TiaPortalViewModel) + " - " + nameof(InitServiceProvider) };
            var version = _settingsService.GetSelectedOpennessApiVersion();
            WriteTraceLogProxy(processInfo.ProcessMessage);

            _tiaPortalServiceProvider = _moduleProvider.GetService(typeof(ITiaPortalServiceProvider)) as ITiaPortalServiceProvider;
            if (_tiaPortalServiceProvider != null)
            {
                _tiaPortalServiceProvider.Initialize(_opennessDemoModel, _traceLogService);
                _opennessDemoModel.TiaPortalServiceProvider = _tiaPortalServiceProvider;

                var tiaPortalMode = _settingsService.GetTiaPortalMode();
                _opennessDemoModel.TiaPortalStartMode = EnumService.GetEnumValue<TiaPortalStartMode>(tiaPortalMode);
            }
            else
            {
                WriteTraceLogProxy(processInfo.ProcessMessage + " -> portal service provider for version - " + version + " not found!");
            }
            _projectServiceProvider = _moduleProvider.GetService(typeof(IProjectServiceProvider)) as IProjectServiceProvider;
            if (_projectServiceProvider != null)
            {
                WriteTraceLogProxy(processInfo.ProcessMessage + " -> " + nameof(IPlcSoftwareService));
                var plcSoftwareService = _moduleProvider.GetService(typeof(IPlcSoftwareService)) as IPlcSoftwareService;
                WriteTraceLogProxy(processInfo.ProcessMessage + " -> " + nameof(IHmiSoftwareService));
                var hmiSoftwareService = _moduleProvider.GetService(typeof(IHmiSoftwareService)) as IHmiSoftwareService;
                WriteTraceLogProxy(processInfo.ProcessMessage + " -> " + nameof(IHmiTargetService));
                var hmiTargetService = _moduleProvider.GetService(typeof(IHmiTargetService)) as IHmiTargetService;
                WriteTraceLogProxy(processInfo.ProcessMessage + " -> " + nameof(IStartdriveService));
                var sinamicsService = _moduleProvider.GetService(typeof(IStartdriveService)) as IStartdriveService;

                _projectServiceProvider.Initialize(_opennessDemoModel, _traceLogService, _settingsService, _tiaPortalServiceProvider, plcSoftwareService, hmiSoftwareService, hmiTargetService, sinamicsService);
            }
            else
            {
                WriteTraceLogProxy(processInfo.ProcessMessage + " -> project service provider for version - " + version + " not found!");
            }
        }

        #endregion // ctor

        #region properties

        /// <summary>
        /// Determine if the call is at design time.
        /// </summary>
        public static bool IsDesignTime => (LicenseManager.UsageMode == LicenseUsageMode.Designtime);

        /// <summary>
        /// The versions of the TIA Portal instance
        /// </summary>
        public ObservableCollection<string> EngineeringVersions
        {
            get => _engineeringVersions;
            set
            {
                _engineeringVersions = value;
                RaisePropertyChanged(nameof(EngineeringVersions));
            }
        }

        /// <summary>
        /// The versions of the openness API 
        /// </summary>
        public ObservableCollection<string> AssemblyVersions
        {
            get => _assemblyVersions;
            set
            {
                _assemblyVersions = value;
                RaisePropertyChanged(nameof(AssemblyVersions));
            }
        }

        /// <summary>
        /// Singleton instance for application meta data
        /// </summary>
        public IOpennessDemoModel OpennessDemoModel
        {
            get => _opennessDemoModel;
            set
            {
                SetProperty(ref _opennessDemoModel, value);
                RaisePropertyChanged(nameof(OpennessDemoModel));
            }
        }

        /// <summary>
        /// The selected version of TIA Portal instance
        /// </summary>
        public string SelectedVersion
        {
            get => _selectedVersion;
            set
            {
                _selectedVersion = value;
                SelectedAssembly = null;
                GetAssemblyVersions();
            }
        }

        /// <summary>
        /// The selected version of openness api
        /// </summary>
        public string SelectedAssembly
        {
            get;
            set;
        }

        /// <summary>
        /// The Id of the current TIA Portal process instance
        /// </summary>
        public string CurrentProcessId
        {
            get => _currentProcessId;
            set => SetProperty(ref _currentProcessId, value);
        }

        public string SelectedProcessInformation
        {
            get => _selectedProcessInformation;
            set => SetProperty(ref _selectedProcessInformation, value);
        }

        #endregion // properties

        #region commands

        /// <summary>
        /// Selection changed command for process id collection
        /// </summary>
        public DelegateCommand<object> SelectedIndexChangedProcessesCommand { get; }

        public DelegateCommand ConnectTiaPortalCommand { get; }

        #endregion // commands

        #region command implementations

        /// <summary>
        /// Handle selection change actions from UI
        /// </summary>
        /// <param name="sender"></param>
        private void SelectionIndexChangedProcesses(object sender)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(TiaPortalViewModel) + " - " + nameof(SelectionIndexChangedProcesses) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            if (sender is ListBox listBox && OpennessDemoModel != null)
            {
                OpennessDemoModel.SelectedProcessIndex = listBox.SelectedIndex;
                OpennessDemoModel.SelectedProcessId = listBox.SelectedIndex > -1 ? listBox.SelectedItem?.ToString() : string.Empty;
            }

            ConnectTiaPortalCommand.RaiseCanExecuteChanged();

            WriteTraceLogProxy(processInfo.ProcessMessage + " -> " + nameof(SelectedProcessIdChangedEvent));
            _eventAggregator.GetEvent<SelectedProcessIdChangedEvent>().Publish();
        }

        private void ConnectTiaPortal()
        {
            _eventAggregator.GetEvent<ConnectProjectEvent>().Publish();
        }

        #endregion // command implementations

        #region methods

        /// <summary>
        /// Open a new TIA Portal instance asynchronous
        /// </summary>
        private async void OpenTiaPortalAsync(IOpennessDemoNavigationContext navigationContext)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(TiaPortalViewModel) + " - " + nameof(OpenTiaPortalAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var tiaPortalMode = _settingsService.GetTiaPortalMode();
                _opennessDemoModel.TiaPortalStartMode = EnumService.GetEnumValue<TiaPortalStartMode>(tiaPortalMode);

                if (_tiaPortalServiceProvider != null)
                {
                    IamBusy(processInfo);

                    var innerTask = _tiaPortalServiceProvider.OpenTiaPortalAsync();
                    await innerTask;

                    WriteTraceLogProxy(processInfo.ProcessMessage + " -> " + nameof(TiaPortalStateEvent));
                    _eventAggregator.GetEvent<TiaPortalStateEvent>().Publish();
                    WriteTraceLogProxy(processInfo.ProcessMessage + " -> " + nameof(NavigationRequestEvent));
                    _eventAggregator.GetEvent<NavigationRequestEvent>().Publish(navigationContext.NavigationTarget);
                    ConnectTiaPortalCommand.RaiseCanExecuteChanged();
                    IamDone(processInfo);
                }
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, Resources.Openness_api_exception_occurred, MessageBoxButton.OK, MessageBoxImage.Error);
                IamDone(processInfo);
            }
        }

        /// <summary>
        /// Connect to a existing TIA Portal instance asynchronous
        /// </summary>
        private async void ConnectTiaPortalAsync(IOpennessDemoNavigationContext navigationContext)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(TiaPortalViewModel) + " - " + nameof(ConnectTiaPortalAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                if (_tiaPortalServiceProvider != null && _projectServiceProvider != null)
                {
                    IamBusy(processInfo);

                    if (OpennessDemoModel.PortalOpened)
                    {
                        var portalResult = _tiaPortalServiceProvider.DisconnectTiaPortalAsync();
                        await portalResult;

                        WriteTraceLogProxy(processInfo.ProcessMessage + " -> " + nameof(TiaPortalDisconnectedEvent));
                        _eventAggregator.GetEvent<TiaPortalDisconnectedEvent>().Publish();

                        WriteTraceLogProxy(processInfo.ProcessMessage + " -> " + nameof(NavigationRequestEvent));
                        _eventAggregator.GetEvent<NavigationRequestEvent>().Publish(navigationContext.NavigationTarget);

                        WriteTraceLogProxy(processInfo.ProcessMessage + " -> " + nameof(ResetContentEvent));
                        _eventAggregator.GetEvent<ResetContentEvent>().Publish();

                        ConnectTiaPortalCommand.RaiseCanExecuteChanged();
                    }

                    var result = _tiaPortalServiceProvider.ConnectTiaPortalAsync(OpennessDemoModel.GetSelectedProcessId());
                    await result;

                    if (result.Result)
                    {
                        WriteTraceLogProxy(processInfo.ProcessMessage + " -> " + nameof(TiaPortalConnectedEvent));
                        _eventAggregator.GetEvent<TiaPortalConnectedEvent>().Publish();
                        if (!OpennessDemoModel.TiaPortalDisposed)
                        {
                            WriteTraceLogProxy(processInfo.ProcessMessage + " -> " + nameof(UpdateViewNavigationEvent));
                            _eventAggregator.GetEvent<UpdateViewNavigationEvent>().Publish(OpennessDemoModel.CountLocalSessions > 0);
                        }
                    }
                    ConnectTiaPortalCommand.RaiseCanExecuteChanged();
                    IamDone(processInfo);
                }
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, Resources.Openness_api_exception_occurred, MessageBoxButton.OK, MessageBoxImage.Error);
                IamDone(processInfo);
            }

        }

        /// <summary>
        /// Disconnect from a TIA Portal instance asynchronous
        /// </summary>
        private async void DisconnectTiaPortalAsync(IOpennessDemoNavigationContext navigationContext)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(TiaPortalViewModel) + " - " + nameof(DisconnectTiaPortalAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                if (_tiaPortalServiceProvider != null)
                {
                    IamBusy(processInfo);

                    var result = _tiaPortalServiceProvider.DisconnectTiaPortalAsync();
                    await result;

                    WriteTraceLogProxy(processInfo.ProcessMessage + " -> " + nameof(TiaPortalDisconnectedEvent));
                    _eventAggregator.GetEvent<TiaPortalDisconnectedEvent>().Publish();

                    WriteTraceLogProxy(processInfo.ProcessMessage + " -> " + nameof(NavigationRequestEvent));
                    _eventAggregator.GetEvent<NavigationRequestEvent>().Publish(navigationContext.NavigationTarget);
                    ConnectTiaPortalCommand.RaiseCanExecuteChanged();

                    WriteTraceLogProxy(processInfo.ProcessMessage + " -> " + nameof(ResetContentEvent));
                    _eventAggregator.GetEvent<ResetContentEvent>().Publish();

                    IamDone(processInfo);
                }
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, Resources.Openness_api_exception_occurred, MessageBoxButton.OK, MessageBoxImage.Error);
                IamDone(processInfo);
            }

        }

        /// <summary>
        /// Close the connected TIA Portal instance asynchronous
        /// </summary>
        private async void CloseTiaPortalAsync(IOpennessDemoNavigationContext navigationContext)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(TiaPortalViewModel) + " - " + nameof(CloseTiaPortalAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                if (_tiaPortalServiceProvider != null && _projectServiceProvider != null)
                {
                    IamBusy(processInfo);
                    var projectResult = _projectServiceProvider.CloseProjectAsync();
                    await projectResult;

                    var result = _tiaPortalServiceProvider.CloseTiaPortal();
                    await result;

                    WriteTraceLogProxy(processInfo.ProcessMessage + " -> " + nameof(TiaPortalClosedEvent));
                    _eventAggregator.GetEvent<TiaPortalClosedEvent>().Publish();

                    WriteTraceLogProxy(processInfo.ProcessMessage + " -> " + nameof(ProjectClosedEvent));
                    _eventAggregator.GetEvent<ProjectClosedEvent>().Publish();

                    WriteTraceLogProxy(processInfo.ProcessMessage + " -> " + nameof(NavigationRequestEvent));
                    _eventAggregator.GetEvent<NavigationRequestEvent>().Publish(navigationContext.NavigationTarget);

                    WriteTraceLogProxy(processInfo.ProcessMessage + " -> " + nameof(ResetContentEvent));
                    _eventAggregator.GetEvent<ResetContentEvent>().Publish();

                    IamDone(processInfo);
                }
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, Resources.Openness_api_exception_occurred, MessageBoxButton.OK, MessageBoxImage.Error);
                IamDone(processInfo);
            }
        }

        /// <summary>
        /// Get the current process Id as string of the TIA Portal instance or empty string if no instance is connected
        /// </summary>
        private void GetTiaPortalState()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(TiaPortalViewModel) + " - " + nameof(GetTiaPortalState) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            CurrentProcessId = OpennessDemoModel.CurrentProcessId > -1 ? OpennessDemoModel.CurrentProcessId.ToString() : string.Empty;
        }

        /// <summary>
        /// Get all available Versions of the TIA Portal, and select the first one as initialization if possible 
        /// </summary>
        private void GetEngineeringVersions()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(TiaPortalViewModel) + " - " + nameof(GetEngineeringVersions) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            EngineeringVersions = new ObservableCollection<string>(Resolver.GetEngineeringVersions());
            if (EngineeringVersions != null && EngineeringVersions.Count > 0)
            {
                SelectedVersion = EngineeringVersions.FirstOrDefault();
            }
        }

        /// <summary>
        /// Get all openness api versions for selected TIA Portal version
        /// </summary>
        private void GetAssemblyVersions()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(TiaPortalViewModel) + " - " + nameof(GetAssemblyVersions) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            if (string.IsNullOrEmpty(SelectedVersion)) return;
            AssemblyVersions = new ObservableCollection<string>(Resolver.GetAssemblies(SelectedVersion));
        }

        /// <summary>
        /// Publish busy event for long run processes
        /// </summary>
        /// <param name="processInfo"></param>
        private void IamBusy(ProcessInfo processInfo)
        {
            _eventAggregator.GetEvent<BusyEvent>().Publish(processInfo);
        }

        /// <summary>
        /// Publish done event 
        /// </summary>
        private void IamDone(ProcessInfo processInfo)
        {
            _eventAggregator.GetEvent<DoneEvent>().Publish(processInfo);
        }

        /// <summary>
        /// Show the settings dialog
        /// </summary>
        private void EditSettings()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(TiaPortalViewModel) + " - " + nameof(EditSettings) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            var settingsEditorView = _containerProvider.Resolve<SettingsEditorView>();

            settingsEditorView.ShowDialog();
        }

        private async void DoExit()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(TiaPortalViewModel) + " - " + nameof(CloseTiaPortalAsync) };

            if (OpennessDemoModel.PortalOpened)
            {
                IamBusy(processInfo);
                var projectResult = _projectServiceProvider.CloseProjectAsync();
                await projectResult;

                var result = _tiaPortalServiceProvider.CloseTiaPortal();
                await result;
                IamDone(processInfo);
            }
            Application.Current.Shutdown();
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

        /// <summary>
        /// Execute writing trace log in different thread for all inner exceptions
        /// </summary>
        /// <param name="exception"></param>
        private void WriteTraceLogProxy(Exception exception)
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
