extern alias V15_0;
using System;
using System.Collections.Generic;
using System.IO;
using System.Threading.Tasks;
using System.Windows;
using TiaPortalOpennessAdapter.Models.V15_0;
using TiaPortalOpennessAdapterBase.Base;
using TiaPortalOpennessAdapterBase.Models;
using TiaPortalOpennessAdapterContracts;
using TiaPortalOpennessInfrastructure.Contracts;
using TiaPortalOpennessInfrastructure.Exceptions;
using TiaPortalOpennessInfrastructure.Utils;
using V15_0::Siemens.Engineering;

namespace TiaPortalOpennessAdapterService.Services.V15_0
{
    /// <summary>
    /// Implementation of multi user service
    /// </summary>
    public class MultiuserServiceProvider : ObservableObject, IMultiuserServiceProvider
    {
        #region fields

        private ITraceLogService          _traceLogService;
        private ITiaPortalServiceProvider _tiaPortalServiceProvider;

        #endregion // fields

        #region ctor

        public MultiuserServiceProvider(ITraceLogService traceLogService)
        {
            _traceLogService = traceLogService;
        }

        public void Initialize(IOpennessDemoModel opennessDemoModel, ITraceLogService traceLogService, ITiaPortalServiceProvider tiaPortalServiceProvider, IProjectServiceProvider projectServiceProvider)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(MultiuserServiceProvider) + " - " + nameof(Initialize) };
            try
            {
                _traceLogService          = traceLogService;
                _tiaPortalServiceProvider = tiaPortalServiceProvider;
                EngineeringProjectModel   = _tiaPortalServiceProvider.GetOpennessEngineeringModel() as EngineeringProjectModel;
                ContentDictionary         = new Dictionary<string, string>();

                WriteTraceLogProxy(processInfo.ProcessMessage);
            }
            catch (EngineeringException engineeringException)
            {
                throw OpennessApiExceptionHandler.CatchedEngineeringException(engineeringException);
            }
            catch (NonRecoverableException nonRecoverableException)
            {
                throw OpennessApiExceptionHandler.CatchedNonRecoverableException(nonRecoverableException);
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

        #endregion // ctor

        #region properties

        /// <summary>
        /// Tia portal instance
        /// </summary>
        public TiaPortal TiaPortal
        {
            get;
            set;
        }

        /// <summary>
        /// Engineering project model
        /// </summary>
        public EngineeringProjectModel EngineeringProjectModel
        {
            get;
            set;
        }

        /// <summary>
        /// Dictionary for attribute and values 
        /// </summary>
        public Dictionary<string, string> ContentDictionary
        {
            get;
            set;
        }

        #endregion // properties

        #region methods

        #region local Session

        public Task<string> OpenLocalSessionAsync(string projectPath)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(MultiuserServiceProvider) + " - " + nameof(OpenLocalSessionAsync) };
            try
            {
                WriteTraceLogProxy(processInfo.ProcessMessage + " - is not implemented!");
                throw new NotImplementedException();
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

        public Task<bool> SaveLocalSessionAsync()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(MultiuserServiceProvider) + " - " + nameof(SaveLocalSessionAsync) };
            try
            {
                WriteTraceLogProxy(processInfo.ProcessMessage + " - is not implemented!");
                throw new NotImplementedException();
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

        private FileInfo GetMultiuserProjectFileInfo(FileInfo alsFileInfo, bool fallbackToAmc = true)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(MultiuserServiceProvider) + " - " + nameof(GetMultiuserProjectFileInfo) };
            try
            {
                WriteTraceLogProxy(processInfo.ProcessMessage + " - is not implemented!");
                throw new NotImplementedException();
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

        public Task<Tree> LoadLocalSessionTreeStructureAsync(bool loadLogicalFirst)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(MultiuserServiceProvider) + " - " + nameof(LoadLocalSessionTreeStructureAsync) };
            try
            {
                WriteTraceLogProxy(processInfo.ProcessMessage + " - is not implemented!");
                throw new NotImplementedException();
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

        public Task<bool> CloseLocalSessionAsync()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(MultiuserServiceProvider) + " - " + nameof(CloseLocalSessionAsync) };
            try
            {
                WriteTraceLogProxy(processInfo.ProcessMessage + " - is not implemented!");
                throw new NotImplementedException();
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

        public object GetCurrentSession()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(MultiuserServiceProvider) + " - " + nameof(GetCurrentSession) };
            try
            {
                WriteTraceLogProxy(processInfo.ProcessMessage + " - is not implemented!");
                throw new NotImplementedException();
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

        #endregion // local Session

        #region editor

        public void ShowEditor(string viewName)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(MultiuserServiceProvider) + " - " + nameof(ShowEditor) };
            try
            {
                WriteTraceLogProxy(processInfo.ProcessMessage + " - is not implemented!");
                throw new NotImplementedException();
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

        public void OpenEditor(string header, Guid tag, bool logical)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(MultiuserServiceProvider) + " - " + nameof(OpenEditor) };
            try
            {
                WriteTraceLogProxy(processInfo.ProcessMessage + " - is not implemented!");
                throw new NotImplementedException();
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

        private ProjectItem GetProjectItem(string header, Guid tag, bool logical)
        {
            ProjectItem projectItem = null;

            return projectItem;
        }

        #endregion // editor

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
