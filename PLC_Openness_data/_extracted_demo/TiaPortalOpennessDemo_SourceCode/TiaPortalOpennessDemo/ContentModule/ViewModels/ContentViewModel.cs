using Prism.Events;
using Prism.Mvvm;
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Windows;
using System.Windows.Controls;
using TiaPortalOpennessAdapter.Contracts;
using TiaPortalOpennessAdapterContracts;
using TiaPortalOpennessCore.Events.Content;
using TiaPortalOpennessCore.Events.Global;
using TiaPortalOpennessCore.Events.Project;
using TiaPortalOpennessInfrastructure.Constants;
using TiaPortalOpennessInfrastructure.Contracts;
using TiaPortalOpennessInfrastructure.Utils;


namespace ContentModule.ViewModels
{
    /// <summary>
    /// Project content
    /// </summary>
    public class ContentViewModel : BindableBase
    {
        #region fields

        private readonly ITraceLogService _traceLogService;
        private readonly ISettingsService _settingsService;
        private readonly IModuleProvider _moduleProvider;
        private readonly IOpennessDemoModel _opennessDemoModel;

        private ITiaPortalServiceProvider _tiaPortalServiceProvider;
        private IProjectServiceProvider _projectServiceProvider;
        private Dictionary<string, string> _contentDictionary;

        #endregion // fields

        #region ctor

        /// <summary>
        /// default constructor
        /// </summary>
        /// <param name="eventAggregator"></param>
        /// <param name="traceLogService"></param>
        /// <param name="settingsService"></param>
        /// <param name="moduleProvider"></param>
        /// <param name="opennessDemoModel"></param>
        public ContentViewModel(IEventAggregator eventAggregator, ITraceLogService traceLogService, ISettingsService settingsService, IModuleProvider moduleProvider, IOpennessDemoModel opennessDemoModel)
        {
            var eventAggregator1 = eventAggregator;
            _traceLogService = traceLogService;
            _settingsService = settingsService;
            _moduleProvider = moduleProvider;
            _opennessDemoModel = opennessDemoModel;

            ContentDictionary = new Dictionary<string, string>();

            eventAggregator1.GetEvent<ServiceProviderInitializeEvent>().Subscribe(InitServiceProvider);

            eventAggregator1.GetEvent<LoadContentEvent>().Subscribe(LoadContent);
            eventAggregator1.GetEvent<ResetContentEvent>().Subscribe(ResetContent);
        }

        /// <summary>
        /// Constructor for design time only.
        /// </summary>
        /// <param name="contentDictionary"></param>
        [DesignOnly(true)]
        internal ContentViewModel(Dictionary<string, string> contentDictionary)
        {
            try
            {
                ContentDictionary = contentDictionary;

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
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ContentViewModel) + " - " + nameof(InitServiceProvider) };
            var version = _settingsService.GetSelectedOpennessApiVersion();
            WriteTraceLogProxy(processInfo.ProcessMessage);

            _tiaPortalServiceProvider = _moduleProvider.GetService(typeof(ITiaPortalServiceProvider)) as ITiaPortalServiceProvider;
            if (_tiaPortalServiceProvider != null)
            {
                _tiaPortalServiceProvider.Initialize(_opennessDemoModel, _traceLogService);
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
        /// Dictionary with type name and value
        /// </summary>
        public Dictionary<string, string> ContentDictionary
        {
            get => _contentDictionary;
            set
            {
                SetProperty(ref _contentDictionary, value);
                if (_contentDictionary != value)
                {
                    RaisePropertyChanged("ContentDictionary");
                }
            }
        }

        #endregion // properties

        #region methods

        private void LoadContent(TreeViewItem obj)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ContentViewModel) + " - " + nameof(LoadContent) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                if (obj?.Header != null && obj.Tag != null)
                {
                    ContentDictionary = _projectServiceProvider.ReadProperties((string)obj.Header, (Guid)obj.Tag);
                }
                else
                {
                    ContentDictionary = new Dictionary<string, string>();
                }

            }
            catch (Exception e)
            {
                Console.WriteLine(e);
            }
        }

        private void ResetContent()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ContentViewModel) + " - " + nameof(ResetContent) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            LoadContent(null);
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
