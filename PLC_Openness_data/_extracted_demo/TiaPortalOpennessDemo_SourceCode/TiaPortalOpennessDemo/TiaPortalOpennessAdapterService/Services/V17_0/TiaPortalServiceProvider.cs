extern alias V17_0;
using System;
using System.Collections.Generic;
using System.IO;
using System.Threading.Tasks;
using System.Windows;
using TiaPortalOpennessAdapter.Models.V17_0;
using TiaPortalOpennessAdapter.Services;
using TiaPortalOpennessAdapterBase.Models;
using TiaPortalOpennessAdapterContracts;
using TiaPortalOpennessAdapterService.Utils;
using TiaPortalOpennessInfrastructure.Contracts;
using TiaPortalOpennessInfrastructure.Exceptions;
using TiaPortalOpennessInfrastructure.Utils;
using V17_0::Siemens.Engineering;

namespace TiaPortalOpennessAdapterService.Services.V17_0
{
    /// <summary>
    /// Implementation of the TiaPortal service provider
    /// </summary>
    public class TiaPortalServiceProvider : ObservableObject, ITiaPortalServiceProvider
    {
        #region fields

        private IOpennessDemoModel _opennessDemoModel;
        private ITraceLogService _traceLogService;
        private IList<TiaPortalProcess> _tiaPortalProcessList;

        #endregion // fields

        #region ctor

        /// <summary>
        /// Default constructor.
        /// </summary>
        public TiaPortalServiceProvider(ITraceLogService traceLogService)
        {
            _tiaPortalProcessList = new List<TiaPortalProcess>();
            EngineeringProjectModel = new EngineeringProjectModel();
        }

        /// <summary>
        /// Initialize the provider with meta data and helper services.
        /// </summary>
        /// <param name="opennessDemoModel">the openness demo model</param>
        /// <param name="traceLogService">the trace log service</param>
        public void Initialize(IOpennessDemoModel opennessDemoModel, ITraceLogService traceLogService)
        {
            _opennessDemoModel = opennessDemoModel;
            _traceLogService = traceLogService;
        }

        #endregion // ctor

        #region properties

        /// <summary>
        /// The current engineering project model.
        /// It gives access to version specific types.
        /// </summary>
        public EngineeringProjectModel EngineeringProjectModel
        {
            get;
            set;
        }

        /// <summary>
        /// The current TiaPortal process.
        /// </summary>
        public TiaPortalProcess CurrentTiaPortalProcess
        {
            get;
            set;
        }

        /// <summary>
        /// The current openness demo model.
        /// It gives access to meta information.
        /// </summary>
        public IOpennessDemoModel OpennessDemoModel
        {
            get => _opennessDemoModel;
            set => SetProperty(ref _opennessDemoModel, value);
        }

        /// <summary>
        /// The current TiaPortal instance
        /// </summary>
        public TiaPortal TiaPortal
        {
            get;
            set;
        }

        /// <summary>
        /// Indicates whether the TiaPortal instance is disposed.
        /// </summary>
        public bool TiaPortalIsDisposed
        {
            get;
            set;
        }

        #endregion // properties

        #region methods

        /// <summary>
        /// Open a new TiaPortal instance.
        /// </summary>
        /// <returns>Task</returns>
        public async Task<int> OpenTiaPortalAsync()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(TiaPortalServiceProvider) + " - " + nameof(OpenTiaPortalAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var task = Task.Run(() =>
                {
                    // Retrieve the TiaPortal start mode be string
                    var startMode = EnumService.GetEnumValue<TiaPortalMode>(OpennessDemoModel.TiaPortalStartMode.ToString());
                    TiaPortal = new TiaPortal(startMode);

                    OpennessDemoModel.TiaPortalDisposed = false;
                    OpennessDemoModel.CurrentProcessId = GetCurrentProcessId();
                    OpennessDemoModel.PortalOpened = OpennessDemoModel.CurrentProcessId != -1;

                    return OpennessDemoModel.CurrentProcessId;
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
        /// Create a new project.
        /// </summary>
        /// <param name="opennessDemoModel">the current openness demo model</param>
        /// <returns>Task</returns>
        public async Task<string> CreateProjectAsync(IOpennessDemoModel opennessDemoModel)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(TiaPortalServiceProvider) + " - " + nameof(CreateProjectAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var task = Task.Run(() =>
                {
                    var newProject = TiaPortal.Projects.Create(opennessDemoModel.ProjectModel.TargetDirectory, opennessDemoModel.ProjectModel.ProjectName);

                    if (newProject == null) return string.Empty;

                    opennessDemoModel.ProjectModel.ProjectName = newProject.Name;
                    opennessDemoModel.ProjectModel.TargetDirectory = newProject.Path.Directory;
                    opennessDemoModel.ProjectModel.ProjectOpened = true;

                    WriteTraceLogProxy(processInfo.ProcessMessage + " - new project: " + newProject.Path.FullName + " - project name: " + newProject.Name);
                    return newProject.Name;
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
        /// Connect to TiaPortal Process instance
        /// </summary>
        /// <param name="processId">process id to be connected</param>
        /// <returns>Task</returns>
        public async Task<bool> ConnectTiaPortalAsync(int processId)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(TiaPortalServiceProvider) + " - " + nameof(ConnectTiaPortalAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var task = Task.Run(() =>
                {
                    var tia = TiaPortal.GetProcess(processId, 5000).Attach();
                    if (tia == null) return false;

                    TiaPortal?.Dispose();
                    TiaPortalIsDisposed = true;

                    TiaPortal = tia;
                    TiaPortalIsDisposed = false;

                    OpennessDemoModel.TiaPortalDisposed = false;
                    OpennessDemoModel.LocalSessionOpened = TiaPortal.LocalSessions.Count > 0;
                    OpennessDemoModel.CountLocalSessions = TiaPortal.LocalSessions.Count;
                    OpennessDemoModel.CountProjects = TiaPortal.Projects.Count;
                    OpennessDemoModel.CountProjectServer = TiaPortal.ProjectServers.Count;
                    OpennessDemoModel.CountSettingsFolders = TiaPortal.SettingsFolders.Count;
                    OpennessDemoModel.CountGlobalLibraries = TiaPortal.GlobalLibraries.Count;
                    OpennessDemoModel.CurrentProcessId = GetCurrentProcessId();
                    OpennessDemoModel.PortalOpened = OpennessDemoModel.CurrentProcessId != -1;
                    OpennessDemoModel.ProjectModel.ProjectOpened = TiaPortal.Projects.Count > 0 || TiaPortal.LocalSessions.Count > 0;

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
        /// Disconnect the current TiaPortal instance.
        /// </summary>
        /// <returns>Task</returns>
        public async Task<int> DisconnectTiaPortalAsync()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(TiaPortalServiceProvider) + " - " + nameof(DisconnectTiaPortalAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var task = Task.Run(() =>
                {
                    if (GetCurrentProcessId() != -1)
                    {
                        TiaPortal?.Dispose();
                        TiaPortalIsDisposed = true;

                        OpennessDemoModel.TiaPortalDisposed = true;
                        OpennessDemoModel.CurrentProcessId = -1;
                        OpennessDemoModel.PortalOpened = false;
                        OpennessDemoModel.ProjectModel.ProjectOpened = false;
                    }

                    return OpennessDemoModel.CurrentProcessId;
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
        /// Close the current TiaPortal instance.
        /// </summary>
        /// <returns>Task</returns>
        public Task CloseTiaPortal()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(TiaPortalServiceProvider) + " - " + nameof(CloseTiaPortal) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var task = Task.Run(() =>
                {
                    TiaPortal.GetCurrentProcess().Dispose();
                    TiaPortalIsDisposed = true;

                    OpennessDemoModel.TiaPortalDisposed = true;
                    OpennessDemoModel.CurrentProcessId = -1;
                    OpennessDemoModel.PortalOpened = false;
                    OpennessDemoModel.ProjectModel.ProjectOpened = false;
                });

                return task;
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
        /// Retrieve the current process id.
        /// </summary>
        /// <returns>current process id</returns>
        public int GetCurrentProcessId()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(TiaPortalServiceProvider) + " - " + nameof(GetCurrentProcessId) };

            try
            {
                CurrentTiaPortalProcess = TiaPortal?.GetCurrentProcess();
                WriteTraceLogProxy(processInfo.ProcessMessage + " - " + CurrentTiaPortalProcess?.Id);

                return CurrentTiaPortalProcess?.Id ?? -1;
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
        /// Retrieve all available TiaPortal processes (process id) and assign the start mode to each process id.
        /// </summary>
        /// <returns>list of process id's</returns>
        public IList<string> GetTiaPortalProcesses()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(TiaPortalServiceProvider) + " - " + nameof(GetTiaPortalProcesses) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                IList<string> processIds = null;

                _tiaPortalProcessList = TiaPortal.GetProcesses();

                if (_tiaPortalProcessList.Count > 0)
                {
                    processIds = new List<string>();
                    foreach (var item in _tiaPortalProcessList)
                    {
                        var tiaPortalMode = item.Mode == 0 ? " Without UI" : " With UI";
                        if (item.ProjectPath == null)
                        {
                            processIds.Add(string.Format("ID {0} {1} ", item.Id, tiaPortalMode));
                        }
                        else
                        {
                            if (item.ProjectPath.Extension.Contains(".ap"))
                            {
                                processIds.Add(string.Format("ID {0} {1} SU", item.Id, tiaPortalMode));
                            }
                            else
                            {
                                processIds.Add(string.Format("ID {0} {1} MU", item.Id, tiaPortalMode));
                            }
                        }
                    }
                }

                return processIds;
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

        public IList<string> GetTiaPortalProjectInformation()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(TiaPortalServiceProvider) + " - " + nameof(GetTiaPortalProjectInformation) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                IList<string> projectInfos = null;

                _tiaPortalProcessList = TiaPortal.GetProcesses();

                if (_tiaPortalProcessList.Count > 0)
                {
                    projectInfos = new List<string>();
                    foreach (var process in _tiaPortalProcessList)
                    {
                        var tiaPortalMode = process.Mode == 0 ? " Without UI" : " With UI";
                        if (process.ProjectPath == null)
                        {
                            projectInfos.Add(string.Format("ID {0} {1} {2} {3} ", process.Id, tiaPortalMode, string.Empty, string.Empty));
                        }
                        else
                        {
                            if (process.ProjectPath.Extension.StartsWith(".ap", StringComparison.OrdinalIgnoreCase))
                            {
                                var projectName = process.ProjectPath.FullName;
                                projectInfos.Add(string.Format("ID {0} {1} {2} {3}", process.Id, Path.GetFileName(projectName), tiaPortalMode, " single-user "));
                            }
                            else
                            {
                                var projectName = process.ProjectPath.ToLocalSessionFileInfo(false)?.FullName;
                                projectInfos.Add(string.Format("ID {0} {1} {2} {3}", process.Id, Path.GetFileName(projectName), tiaPortalMode, " multi-user "));
                            }
                        }
                    }
                }

                return projectInfos;
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
        /// Retrieve the current project.
        /// </summary>
        /// <returns>the current project</returns>
        public object GetProject()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(TiaPortalServiceProvider) + " - " + nameof(GetProject) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                return OpennessDemoModel.GetProject();
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
        /// Retrieve the current openness engineering model.
        /// </summary>
        /// <returns>the current openness engineering model</returns>
        public object GetOpennessEngineeringModel()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(TiaPortalServiceProvider) + " - " + nameof(GetOpennessEngineeringModel) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            return EngineeringProjectModel;
        }

        /// <summary>
        /// Retrieve the current TiaPortal instance.
        /// </summary>
        /// <returns>TiaPortal instance</returns>
        public object GetTiaPortal()
        {
            return TiaPortal;
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
