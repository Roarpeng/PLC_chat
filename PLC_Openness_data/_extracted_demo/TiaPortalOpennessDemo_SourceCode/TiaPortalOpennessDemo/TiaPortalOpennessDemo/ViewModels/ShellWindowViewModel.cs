using System;
using Prism.Events;
using Prism.Mvvm;
using System.Collections.ObjectModel;
using System.Linq;
using System.Threading;
using TiaPortalOpennessCore.Events.Global;
using TiaPortalOpennessCore.Events.Shell;
using TiaPortalOpennessInfrastructure.Contracts;
using TiaPortalOpennessInfrastructure.Utils;
using Application = System.Windows.Application;

namespace TiaPortalOpennessDemo.ViewModels
{
    /// <summary>
    /// The shell window view model.
    /// </summary>
    public class ShellWindowViewModel : BindableBase
    {
        #region fields

        private static int                   _processCounter;
        private bool                         _isBusy;
        private string                       _processInfo;
        private readonly ITraceLogService    _traceLogService;
        private readonly IEventAggregator    _eventAggregator;
        private string                       _title;
        private ObservableCollection<string> _traceLog;
        private ProcessInformation           _processInformation;

        #endregion // fields

        #region ctor

        /// <summary>
        /// The default constructor set the title of the shell view.
        /// </summary>
        public ShellWindowViewModel(ITraceLogService traceLogService, IEventAggregator eventAggregator)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ShellWindowViewModel) + " - " + nameof(ShellWindowViewModel) };
            Title                 = "TIA Portal Openness Demo";
            _processCounter       = 0;
            _processInformation   = new ProcessInformation();
            _traceLog             = new ObservableCollection<string>();

            _traceLogService      = traceLogService;
            _traceLogService.List = TraceLog;
            _eventAggregator      = eventAggregator;

            WriteTraceLogProxy(processInfo.ProcessMessage);
        }

        #endregion // ctor

        #region properties

        /// <summary>
        /// Process information for progress bar
        /// </summary>
        public string ProcessInfo
        {
            get => _processInfo;
            set => SetProperty(ref _processInfo, value);
        }

        /// <summary>
        /// Busy indicator flag, used from progress bar
        /// </summary>
        public bool IsBusy
        {
            get => _isBusy;
            set => SetProperty(ref _isBusy, value);
        }

        /// <summary>
        /// The title of the shell view
        /// </summary>
        public string Title
        {
            get => _title;
            set => SetProperty(ref _title, value);
        }

        /// <summary>
        /// List for trace log information
        /// </summary>
        public ObservableCollection<string> TraceLog
        {
            get => _traceLog;
            set => SetProperty(ref _traceLog, value);
        }

        /// <summary>
        /// Process information
        /// </summary>
        public ProcessInformation ProcessInformation
        {
            get => _processInformation;
            set
            {
                SetProperty(ref _processInformation, value);
                RaisePropertyChanged(nameof(ProcessInformation));
            }
        }

        #endregion // properties

        #region methods

        public void InitEnvironment(bool baseServiceLoaded)
        {
            _eventAggregator.GetEvent<InitEnvironmentEvent>().Publish(baseServiceLoaded);
        }

        private void IamDone(ProcessInfo processInfo)
        {
            WriteTraceLogProxy(nameof(ShellWindowViewModel) + " - " + nameof(IamDone) + " -> " + processInfo.ProcessMessage);

            var tempList = ProcessInformation.ProcessInfos.ToList();

            foreach (var item in ProcessInformation.ProcessInfos)
            {
                if (item.ProcessMessageId == processInfo.ProcessMessageId)
                {
                    tempList.Remove(item);
                }
            }

            ProcessInformation.ProcessInfos.Clear();
            ProcessInformation.ProcessInfos = tempList.ToList();

            Interlocked.Decrement(ref _processCounter);

            if (_processCounter == 0)
            {
                IsBusy = false;
                ProcessInfo = string.Empty;
            }
        }

        private void IamBusy(ProcessInfo processInfo)
        {
            WriteTraceLogProxy(nameof(ShellWindowViewModel) + " - " + nameof(IamBusy) + " -> " + processInfo.ProcessMessage);

            IsBusy = true;
            ProcessInformation.Add(processInfo);
            Interlocked.Increment(ref _processCounter);

            ProcessInfo = processInfo.ProcessMessage;
        }

        /// <summary>
        /// Initialization of the event subscription
        /// </summary>
        public void InitEvents()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ShellWindowViewModel) + " - " + nameof(InitEvents) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            _eventAggregator.GetEvent<BusyEvent>().Subscribe(IamBusy);
            _eventAggregator.GetEvent<DoneEvent>().Subscribe(IamDone);
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
