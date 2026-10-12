using Prism.Events;
using Prism.Ioc;
using Prism.Mvvm;
using System.Windows;
using TiaPortalOpennessAdapter.Contracts;
using TiaPortalOpennessAdapterContracts;
using TiaPortalOpennessInfrastructure.Contracts;

namespace MultiuserProjectModule.ViewModels
{
    public class LocalSessionViewModel : BindableBase
    {
        #region fields

        private readonly ITraceLogService _traceLogService;

        #endregion

        #region ctor

        public LocalSessionViewModel(IEventAggregator eventAggregator, ITraceLogService traceLogService, ISettingsService settingsService, IModuleProvider moduleProvider, IContainerProvider containerProvider, IOpennessDemoModel opennessDemoModel)
        {
            _traceLogService = traceLogService;
            OpennessDemoModel = opennessDemoModel;

            //SelectedIndexChangedProcessesCommand = new DelegateCommand<object>(SelectionIndexChangedProcesses);
        }

        #endregion

        #region properties

        public IOpennessDemoModel OpennessDemoModel { get; }

        #endregion

        #region commands

        //public DelegateCommand<object> SelectedIndexChangedProcessesCommand { get; }

        #endregion // commands

        #region command implementation

        //private void SelectionIndexChangedProcesses(object obj)
        //{
        //    var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(LocalSessionViewModel) + " - " + nameof(SelectionIndexChangedProcesses) };
        //    WriteTraceLogProxy(processInfo.ProcessMessage);
        //}

        #endregion // command implementation

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
