using Prism.Events;
using Prism.Mvvm;
using Prism.Regions;
using System;
using System.Windows;
using TiaPortalOpennessCore.Events.Content;
using TiaPortalOpennessInfrastructure.Contracts;
using TiaPortalOpennessInfrastructure.Utils;

namespace ProjectModule.ViewModels
{
    /// <summary>
    /// This empty view model acts as navigation target if no data context is available.
    /// </summary>
    public class EmptyProjectTreeViewModel : BindableBase, INavigationAware
    {
        #region fields

        private readonly IEventAggregator _eventAggregator;
        private readonly ITraceLogService _traceLogService;

        #endregion // fields

        #region ctor

        /// <summary>
        /// Constructor with initialization
        /// </summary>
        /// <param name="eventAggregator"></param>
        /// <param name="traceLogService"></param>
        public EmptyProjectTreeViewModel(IEventAggregator eventAggregator, ITraceLogService traceLogService)
        {
            _eventAggregator = eventAggregator;
            _traceLogService = traceLogService;
        }

        #endregion // ctor

        #region properties

        #endregion // properties

        #region methods

        #endregion // methods

        #region INavigationAware

        /// <summary>
        /// Navigate to target
        /// </summary>
        /// <param name="navigationContext"></param>
        public void OnNavigatedTo(NavigationContext navigationContext)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(EmptyProjectTreeViewModel) + " - " + nameof(OnNavigatedTo) };
            WriteTraceLogProxy(processInfo.ProcessMessage + " - " + navigationContext.Uri);

            _eventAggregator.GetEvent<ResetContentEvent>().Publish();
        }

        /// <summary>
        /// Is this the target?
        /// </summary>
        /// <param name="navigationContext"></param>
        /// <returns></returns>
        public bool IsNavigationTarget(NavigationContext navigationContext)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(EmptyProjectTreeViewModel) + " - " + nameof(IsNavigationTarget) };
            WriteTraceLogProxy(processInfo.ProcessMessage + " - " + navigationContext.Uri);

            return true;
        }

        /// <summary>
        /// Navigate from where?
        /// </summary>
        /// <param name="navigationContext"></param>
        public void OnNavigatedFrom(NavigationContext navigationContext)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(EmptyProjectTreeViewModel) + " - " + nameof(OnNavigatedFrom) };
            WriteTraceLogProxy(processInfo.ProcessMessage + " - " + navigationContext.Uri);
        }

        #endregion // INavigationAware

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