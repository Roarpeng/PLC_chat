extern alias V17_0;
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using System.Windows;
using TiaPortalOpennessAdapter.Models.V17_0;
using TiaPortalOpennessAdapter.Services;
using TiaPortalOpennessAdapterBase.Base;
using TiaPortalOpennessAdapterBase.Models;
using TiaPortalOpennessAdapterContracts;
using TiaPortalOpennessInfrastructure.Contracts;
using TiaPortalOpennessInfrastructure.Exceptions;
using TiaPortalOpennessInfrastructure.Utils;
using V17_0::Siemens.Engineering;
using V17_0::Siemens.Engineering.HW;
using V17_0::Siemens.Engineering.Multiuser;

namespace TiaPortalOpennessAdapterService.Services.V17_0
{
    public class MultiuserServiceProvider : ObservableObject, IMultiuserServiceProvider
    {
        #region fields

        private IOpennessDemoModel        _opennessDemoModel;
        private ITraceLogService          _traceLogService;
        private ITiaPortalServiceProvider _tiaPortalServiceProvider;
        private IProjectServiceProvider   _projectServiceProvider;

        private ProjectModel              _projectModel;

        #endregion // fields

        #region ctor

        public MultiuserServiceProvider(ITraceLogService traceLogService)
        {

        }

        /// <summary>
        /// Initialization of the service provider
        /// </summary>
        /// <param name="opennessDemoModel"></param>
        /// <param name="traceLogService"></param>
        /// <param name="tiaPortalServiceProvider"></param>
        /// <param name="projectServiceProvider"></param>
        public void Initialize(IOpennessDemoModel opennessDemoModel, ITraceLogService traceLogService, ITiaPortalServiceProvider tiaPortalServiceProvider, IProjectServiceProvider projectServiceProvider)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(MultiuserServiceProvider) + " - " + nameof(Initialize) };
            try
            {
                _traceLogService          = traceLogService;
                _opennessDemoModel        = opennessDemoModel;
                _tiaPortalServiceProvider = tiaPortalServiceProvider;
                _projectServiceProvider   = projectServiceProvider;
                _projectModel             = _tiaPortalServiceProvider.GetProject() as ProjectModel;
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
        /// Current local session
        /// </summary>
        public LocalSession CurrentSession
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

        /// <summary>
        /// Open a local session
        /// </summary>
        /// <param name="projectPath"></param>
        /// <returns></returns>
        public async Task<string> OpenLocalSessionAsync(string projectPath)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(MultiuserServiceProvider) + " - " + nameof(OpenLocalSessionAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var task = Task.Run(async () =>
                {
                    if (!_opennessDemoModel.PortalOpened)
                    {
                        Task<int> portalTask = _tiaPortalServiceProvider.OpenTiaPortalAsync();
                        await portalTask;
                    }

                    string result = string.Empty;
                    var tiaPortal = _tiaPortalServiceProvider.GetTiaPortal() as TiaPortal;

                    if (tiaPortal != null && !CheckProject(tiaPortal, new FileInfo(projectPath)))
                    {
                        var localSession = tiaPortal.LocalSessions.Open(new FileInfo(projectPath));

                        if (localSession != null)
                        {
                            CurrentSession = localSession;

                            _opennessDemoModel.CountProjects = localSession.Project != null ? 1 : 0;
                            result = _opennessDemoModel.ProjectModel.ProjectName;
                        }
                    }

                    return result;
                });
                await task;

                return task.Result;
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

        /// <summary>
        /// Save local session
        /// </summary>
        /// <returns></returns>
        public async Task<bool> SaveLocalSessionAsync()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(MultiuserServiceProvider) + " - " + nameof(SaveLocalSessionAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var task = Task.Run(() =>
                {
                    CurrentSession.Save();

                    return true;
                });
                await task;

                return task.Result;
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

        private bool CheckProject(TiaPortal tiaPortal, FileInfo amcFileInfo)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(MultiuserServiceProvider) + " - " + nameof(CheckProject) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                bool found = false;
                var fileInfo = GetMultiuserProjectFileInfo(amcFileInfo);

                foreach (var process in TiaPortal.GetProcesses())
                {
                    if (process.ProjectPath?.FullName == fileInfo.FullName)
                    {
                        found = true;
                        break;
                    }
                }

                return found;
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

        private FileInfo GetMultiuserProjectFileInfo(FileInfo alsFileInfo, bool fallbackToAmc = true)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(MultiuserServiceProvider) + " - " + nameof(GetMultiuserProjectFileInfo) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                if (alsFileInfo == null) throw new ArgumentNullException(nameof(alsFileInfo));
                if (!alsFileInfo.Extension.StartsWith(".als", StringComparison.OrdinalIgnoreCase)) throw new NotSupportedException("The file type is not supported.");

                var localSessionFileInfo = alsFileInfo.Directory?.EnumerateDirectories("LS").FirstOrDefault()?.GetFiles().FirstOrDefault();
                return localSessionFileInfo ?? (fallbackToAmc ? alsFileInfo : null);
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

        /// <summary>
        /// Load tree structure for local session
        /// </summary>
        /// <param name="loadLogicalFirst"></param>
        /// <returns></returns>
        public async Task<Tree> LoadLocalSessionTreeStructureAsync(bool loadLogicalFirst)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(MultiuserServiceProvider) + " - " + nameof(LoadLocalSessionTreeStructureAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var task = Task.Run(() => _projectServiceProvider.LoadLocalSessionTreeStructureAsync(loadLogicalFirst));
                await task;

                return task.Result;
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

        /// <summary>
        /// Close local session
        /// </summary>
        /// <returns></returns>
        public async Task<bool> CloseLocalSessionAsync()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(MultiuserServiceProvider) + " - " + nameof(CloseLocalSessionAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var task = Task.Run(() =>
                {
                    TiaPortal = _tiaPortalServiceProvider.GetTiaPortal() as TiaPortal;
                    if (TiaPortal == null) return true;

                    if (_opennessDemoModel.LocalSessionOpened && TiaPortal?.LocalSessions.Count > 0)
                    {
                        var localSession = TiaPortal.LocalSessions.FirstOrDefault();
                        localSession?.Close();
                    }

                    _opennessDemoModel.CountProjects = 0;
                    //_logicalProjectTree?.ProjectItems.Clear();
                    //_physicalProjectTree?.ProjectItems.Clear();
                    _projectModel?.LogicalTree?.Items.Clear();
                    _projectModel?.PhysicalTree?.Items.Clear();

                    return true;
                });
                await task;

                return task.Result;
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

        /// <summary>
        /// Retrieve current local session
        /// </summary>
        /// <returns></returns>
        public object GetCurrentSession()
        {
            return CurrentSession;
        }

        #endregion // local Session

        #region editor

        /// <summary>
        /// Show editor as network or topology view
        /// </summary>
        /// <param name="viewName"></param>
        public void ShowEditor(string viewName)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(MultiuserServiceProvider) + " - " + nameof(ShowEditor) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var viewType = EnumService.GetEnumValue<View>(viewName);

                var tiaPortal = _tiaPortalServiceProvider.GetTiaPortal() as TiaPortal;

                if (tiaPortal != null && tiaPortal.LocalSessions?.FirstOrDefault()?.Project != null)
                {
                    tiaPortal.LocalSessions?.FirstOrDefault()?.Project.ShowHwEditor(viewType);
                }
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

        /// <summary>
        /// Show device in hardware editor
        /// </summary>
        /// <param name="header"></param>
        /// <param name="tag"></param>
        /// <param name="logical"></param>
        public void OpenEditor(string header, Guid tag, bool logical)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(MultiuserServiceProvider) + " - " + nameof(OpenEditor) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                //var projectItem = GetProjectItem(header, tag, logical);
                _projectServiceProvider.OpenEditor(header, tag, logical);

                //if (projectItem != null)
                //{
                //    if (projectItem.DeviceItem is Device projectItemDevice)
                //    {
                //        projectItemDevice.ShowInEditor(View.Device);
                //    }
                //    else
                //    {
                //        var type = projectItem.DeviceItem.GetType();
                //        var methodInfo = type.GetMethod("ShowInEditor");

                //        if (methodInfo == null && type.BaseType != null)
                //        {
                //            methodInfo = type.BaseType.GetMethod("ShowInEditor");

                //        }

                //        if (methodInfo != null)
                //        {
                //            methodInfo.Invoke(projectItem.DeviceItem, null);
                //        }
                //    }
                //}
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
