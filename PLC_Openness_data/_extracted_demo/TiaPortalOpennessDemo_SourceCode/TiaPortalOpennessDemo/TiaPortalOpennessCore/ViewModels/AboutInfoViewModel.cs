using Prism.Commands;
using Prism.Mvvm;
using System;
using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Diagnostics;
using System.Text;
using System.Windows;
using TiaPortalOpennessAdapter.Contracts;
using TiaPortalOpennessAdapterContracts;
using TiaPortalOpennessInfrastructure.Constants;
using TiaPortalOpennessInfrastructure.Contracts;
using TiaPortalOpennessInfrastructure.Utils;

namespace TiaPortalOpennessCore.ViewModels
{
    /// <summary>
    /// AboutInfoViewModel implementation
    /// </summary>
    public class AboutInfoViewModel : BindableBase
    {
        #region fields

        private bool? _dialogResult;
        private readonly ITraceLogService _traceLogService;
        internal readonly ISettingsService SettingsService;
        private readonly IModuleProvider _moduleProvider;
        private readonly IOpennessDemoModel _opennessDemoModel;

        internal ITiaPortalServiceProvider TiaPortalServiceProvider;
        internal IProjectServiceProvider ProjectServiceProvider;
        internal IPlcSoftwareService PlcSoftwareService;
        internal IHmiSoftwareService HmiSoftwareService;
        internal IHmiTargetService HmiTargetService;
        internal IStartdriveService SinamicsService;

        private ObservableCollection<string> _systemInfo;

        private string _currentEngineeringVersion;
        private string _currentOpennessApiVersion;

        #endregion // fields

        #region ctor

        /// <summary>
        /// default constructor
        /// </summary>
        /// <param name="traceLogService"></param>
        /// <param name="settingsService"></param>
        /// <param name="moduleProvider"></param>
        /// <param name="opennessDemoModel"></param>
        public AboutInfoViewModel(ITraceLogService traceLogService, ISettingsService settingsService, IModuleProvider moduleProvider, IOpennessDemoModel opennessDemoModel) //, IProjectServiceProvider projectServiceProvider)
        {
            _traceLogService    = traceLogService;
            SettingsService     = settingsService;
            _moduleProvider     = moduleProvider;
            _opennessDemoModel  = opennessDemoModel;

            CopyInfoCommand     = new DelegateCommand(CopyInfo);
            ConfirmationCommand = new DelegateCommand(ConfirmAndCloseWindow);

            var aboutInfos      = new ObservableCollection<string>();

            InitPortalServiceProvider();
            InitProjectServiceProvider();

            GetApplicationInfos(ref aboutInfos);
            GetExampleInfos(ref aboutInfos);
            GetCopyRightInfos(ref aboutInfos);
            GetVersionInfo(ref aboutInfos);
            GetAssemblyInfos(ref aboutInfos);
            GetServiceInfos(ref aboutInfos);

            SystemInfo = aboutInfos;
        }

        /// <summary>
        /// Constructor for design time only.
        /// </summary>
        /// <param name="systemInfo"></param>
        [DesignOnly(true)]
        internal AboutInfoViewModel(ObservableCollection<string> systemInfo)
        {
            try
            {
                SystemInfo = systemInfo;

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

        private void InitPortalServiceProvider()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(AboutInfoViewModel) + " - " + nameof(InitPortalServiceProvider) };
            TiaPortalServiceProvider = _moduleProvider.GetService(typeof(ITiaPortalServiceProvider)) as ITiaPortalServiceProvider;
            if (TiaPortalServiceProvider != null)
            {
                WriteTraceLogProxy(processInfo.ProcessMessage);
                TiaPortalServiceProvider.Initialize(_opennessDemoModel, _traceLogService);
            }
            else
            {
                var version = SettingsService.GetSelectedOpennessApiVersion();
                WriteTraceLogProxy(processInfo.ProcessMessage + " - portal service provider for version - " + version + " not found!");
            }
        }

        private void InitProjectServiceProvider()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(AboutInfoViewModel) + " - " + nameof(InitProjectServiceProvider) };
            ProjectServiceProvider = _moduleProvider.GetService(typeof(IProjectServiceProvider)) as IProjectServiceProvider;
            if (ProjectServiceProvider != null)
            {
                WriteTraceLogProxy(processInfo.ProcessMessage);

                if (PlcSoftwareService == null)
                {
                    PlcSoftwareService = _moduleProvider.GetService(typeof(IPlcSoftwareService)) as IPlcSoftwareService;
                }

                if (HmiSoftwareService == null)
                {
                    HmiSoftwareService = _moduleProvider.GetService(typeof(IHmiSoftwareService)) as IHmiSoftwareService;
                }

                if (HmiTargetService == null)
                {
                    HmiTargetService = _moduleProvider.GetService(typeof(IHmiTargetService)) as IHmiTargetService;
                }

                if (SinamicsService == null)
                {
                    SinamicsService = _moduleProvider.GetService(typeof(IStartdriveService)) as IStartdriveService;
                }

                ProjectServiceProvider.Initialize(_opennessDemoModel, _traceLogService, SettingsService, TiaPortalServiceProvider, PlcSoftwareService, HmiSoftwareService, HmiTargetService, SinamicsService);
            }
            else
            {
                var version = SettingsService.GetSelectedOpennessApiVersion();
                WriteTraceLogProxy(processInfo.ProcessMessage + " - project service provider for version - " + version + " not found!");
            }
        }

        #endregion // ctor

        #region commands

        /// <summary>
        /// Copies the system information to the clipboard
        /// </summary>
        public DelegateCommand CopyInfoCommand { get; }

        /// <summary>
        /// Command to confirm the selection.
        /// </summary>
        public DelegateCommand ConfirmationCommand { get; }

        #endregion // commands

        #region command implementations

        private void CopyInfo()
        {
            StringBuilder clipBoardStringBuilder = new StringBuilder();

            clipBoardStringBuilder.AppendLine("Application Info:");
            foreach (var item in SystemInfo)
            {
                clipBoardStringBuilder.AppendLine(item);
            }

            clipBoardStringBuilder.AppendLine("\nTrace Log:");
            foreach (var traceInfo in _traceLogService.List)
            {
                clipBoardStringBuilder.AppendLine(traceInfo);
            }

            Clipboard.SetText(clipBoardStringBuilder.ToString());

            MessageBox.Show("Copy Application info to clipboard succeed.", "Copy info", MessageBoxButton.OK, MessageBoxImage.Information);
        }

        private void ConfirmAndCloseWindow()
        {
            DialogResult = true;

            Close?.Invoke();
        }


        #endregion // command implementations

        #region actions

        /// <summary>
        /// Action for window close.
        /// </summary>
        public Action Close { get; set; }

        #endregion // actions

        #region properties

        /// <summary>
        /// Determine if the call is at design time.
        /// </summary>
        public static bool IsDesignTime => (LicenseManager.UsageMode == LicenseUsageMode.Designtime);

        /// <summary>
        /// List for system information
        /// </summary>
        public ObservableCollection<string> SystemInfo
        {
            get => _systemInfo;
            set => SetProperty(ref _systemInfo, value);
        }

        /// <summary>
        /// The current engineering version
        /// </summary>
        public string CurrentEngineeringVersion
        {
            get => _currentEngineeringVersion;
            set => SetProperty(ref _currentEngineeringVersion, value);
        }

        /// <summary>
        /// The current openness api version
        /// </summary>
        public string CurrentOpennessApiVersion
        {
            get => _currentOpennessApiVersion;
            set => SetProperty(ref _currentOpennessApiVersion, value);
        }

        /// <summary>
        /// The result of the dialog.
        /// </summary>
        public bool? DialogResult
        {
            get => _dialogResult;
            set => SetProperty(ref _dialogResult, value);
        }

        /// <summary>
        /// Dialog title
        /// </summary>
        public string Title => "About TIA Portal Openness Demo";

        #endregion // properties

        #region methods
        private void GetApplicationInfos(ref ObservableCollection<string> aboutInfo)
        {
            var assemblyName = Process.GetCurrentProcess().MainModule?.ModuleName;
            var assemblyVersion = Process.GetCurrentProcess().MainModule?.FileVersionInfo.FileVersion;

            aboutInfo.Add(assemblyName);
            aboutInfo.Add(assemblyVersion);
        }

        private void GetExampleInfos(ref ObservableCollection<string> aboutInfo)
        {
            if (ProjectServiceProvider != null)
            {
                var projectName = ProjectServiceProvider.GetCurrentProjectName();
                var projectPath = ProjectServiceProvider.GetCurrentProjectPath();

                if (!string.IsNullOrEmpty(projectName) && projectPath != null)
                {
                    aboutInfo.Add("\n" + projectName);
                    aboutInfo.Add(projectPath?.FullName);
                }
            }

            aboutInfo.Add("https://support.industry.siemens.com/");
        }

        private void GetCopyRightInfos(ref ObservableCollection<string> aboutInfo)
        {
            aboutInfo.Add("\nCopyright © Siemens AG, 2022, and licensor.");
            aboutInfo.Add("All rights reserved. Portions include Open Source Software.");
            aboutInfo.Add("See ReadMe_OSS for details.");
        }

        private void GetVersionInfo(ref ObservableCollection<string> aboutInfo)
        {
            var engineeringVersion = SettingsService.GetSelectedEngineeringVersion();
            var opennessApiVersion = SettingsService.GetSelectedOpennessApiVersion();

            aboutInfo.Add("\nCurrent engineering version:" + "\t" + engineeringVersion);
            aboutInfo.Add("Current openness api version:" + "\t" + opennessApiVersion);
        }

        private void GetAssemblyInfos(ref ObservableCollection<string> aboutInfo)
        {
            if (_moduleProvider?.OpennessAssemblies.Count > 0)
            {
                aboutInfo.Add("\nModule expansions:");
                foreach (var assembly in _moduleProvider.OpennessAssemblies)
                {

                    aboutInfo.Add("\t" + assembly.GetName());
                }
            }
        }

        private void GetServiceInfos(ref ObservableCollection<string> aboutInfo)
        {
            if (_moduleProvider?.OpennessServices.Count > 0)
            {
                aboutInfo.Add("\nServices:");
                foreach (var service in _moduleProvider.OpennessServices)
                {
                    aboutInfo.Add("\t" + service.GetType().Name);
                }
            }
        }

        #endregion // methods

        #region trace

        /// <summary>
        /// Execute writing trace log in different thread.
        /// </summary>
        /// <param name="traceLog"></param>
        protected virtual void WriteTraceLogProxy(string traceLog)
        {
            Application.Current.Dispatcher.Invoke(delegate
            {
                _traceLogService.Write(traceLog);
            });
        }

        #endregion // trace

    }
}
