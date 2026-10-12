extern alias V16_0;
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Threading.Tasks;
using System.Windows;
using TiaPortalOpennessAdapter.Models.V16_0;
using TiaPortalOpennessAdapter.Services;
using TiaPortalOpennessAdapterBase.Base;
using TiaPortalOpennessAdapterBase.Enums;
using TiaPortalOpennessAdapterBase.Models;
using TiaPortalOpennessAdapterContracts;
using TiaPortalOpennessAdapterService.Services.V16_0.Utils;
using TiaPortalOpennessInfrastructure.Contracts;
using TiaPortalOpennessInfrastructure.Exceptions;
using TiaPortalOpennessInfrastructure.Utils;
using V16_0::Siemens.Engineering;
using V16_0::Siemens.Engineering.Compiler;
using V16_0::Siemens.Engineering.HW;
using V16_0::Siemens.Engineering.SW;
using V16_0::Siemens.Engineering.SW.Blocks;
using V16_0::Siemens.Engineering.SW.ExternalSources;
using V16_0::Siemens.Engineering.SW.Types;

namespace TiaPortalOpennessAdapterService.Services.V16_0
{
    public class ProjectServiceProvider : ObservableObject, IProjectServiceProvider
    {
        #region fields

        private IOpennessDemoModel _opennessDemoModel;
        private ITraceLogService _traceLogService;
        private ISettingsService _settingsService;
        private ITiaPortalServiceProvider _tiaPortalServiceProvider;
        private IPlcSoftwareService _plcSoftwareService;
        private IHmiSoftwareService _hmiSoftwareService;
        private IHmiTargetService _hmiTargetService;
        private IStartdriveService _sinamicsService;

        private ProjectModel _projectModel;

        private ProjectContent _logicalProjectTree;
        private ProjectContent _physicalProjectTree;

        private ProjectContent _plcTree;

        private CompilerResult _compilerResult;

        #endregion // fields

        #region ctor

        public ProjectServiceProvider(ITraceLogService traceLogService)
        {
            ContentDictionary = new Dictionary<string, string>();
        }

        public void Initialize(IOpennessDemoModel opennessDemoModel, ITraceLogService traceLogService,
            ISettingsService settingsService, ITiaPortalServiceProvider tiaPortalServiceProvider,
            IPlcSoftwareService plcSoftwareService, IHmiSoftwareService hmiSoftwareService,
            IHmiTargetService hmiTargetService, IStartdriveService sinamicsService)
        {
            _opennessDemoModel = opennessDemoModel;
            _traceLogService = traceLogService;
            _settingsService = settingsService;
            _tiaPortalServiceProvider = tiaPortalServiceProvider;
            _plcSoftwareService = plcSoftwareService;
            _hmiSoftwareService = hmiSoftwareService;
            _hmiTargetService = hmiTargetService;
            _sinamicsService = sinamicsService;

            if (_tiaPortalServiceProvider != null)
            {
                _projectModel = _tiaPortalServiceProvider.GetProject() as ProjectModel;
                EngineeringProjectModel = _tiaPortalServiceProvider.GetOpennessEngineeringModel() as EngineeringProjectModel;
            }
        }


        #endregion // ctor

        #region properties

        public TiaPortal TiaPortal
        {
            get;
            set;
        }

        public EngineeringProjectModel EngineeringProjectModel
        {
            get;
            set;
        }

        public Project CurrentProject { get; set; }

        public Dictionary<string, string> ContentDictionary
        {
            get;
            set;
        }

        #endregion // properties

        #region methods

        #region project

        public async Task<string> CreateNewProjectAsync(IOpennessDemoModel opennessDemoModel)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ProjectServiceProvider) + " - " + nameof(CreateNewProjectAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var task = Task.Run(async () =>
                {
                    if (!opennessDemoModel.PortalOpened)
                    {
                        var openPortal = _tiaPortalServiceProvider.OpenTiaPortalAsync();
                        await openPortal;
                    }

                    var closeProject = CloseProjectAsync();
                    await closeProject;

                    var createProject = _tiaPortalServiceProvider.CreateProjectAsync(_opennessDemoModel);
                    await createProject;

                    TiaPortal = _tiaPortalServiceProvider.GetTiaPortal() as TiaPortal;
                    if (TiaPortal != null)
                    {
                        Project project = TiaPortal.Projects.FirstOrDefault();
                        CurrentProject = project;
                        opennessDemoModel.CountProjects = TiaPortal.Projects.Count;
                    }

                    return createProject;
                });
                await task;

                return task.Result.Result;
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

        public async Task<string> OpenProjectAsync(string projectPath)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ProjectServiceProvider) + " - " + nameof(OpenProjectAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var task = Task.Run(async () =>
                {
                    if (!_opennessDemoModel.PortalOpened)
                    {
                        var portalTask = _tiaPortalServiceProvider.OpenTiaPortalAsync();
                        await portalTask;
                    }

                    string result = string.Empty;
                    bool loadOpenProject = false;

                    var tiaPortal = _tiaPortalServiceProvider.GetTiaPortal() as TiaPortal;
                    if (tiaPortal != null)
                    {
                        var tiaPortalProcessList = TiaPortal.GetProcesses();

                        if (tiaPortalProcessList.Count > 0)
                        {
                            foreach (var item in tiaPortalProcessList)
                            {
                                if (item.ProjectPath != null && item.ProjectPath.FullName == projectPath)
                                {
                                    loadOpenProject = true;
                                    break;
                                }
                            }
                        }

                        if (!loadOpenProject)
                        {
                            Project newProject = tiaPortal.Projects.Open(new FileInfo(projectPath));

                            if (newProject != null)
                            {
                                CurrentProject = newProject;
                                _opennessDemoModel.ProjectModel.ProjectName = newProject.Name;
                                _opennessDemoModel.ProjectModel.TargetDirectory = newProject.Path.Directory;
                                _opennessDemoModel.ProjectModel.ProjectOpened = true;
                                _opennessDemoModel.CountProjects = tiaPortal.Projects.Count;
                                result = _opennessDemoModel.ProjectModel.ProjectName;
                            }
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

        public async Task<string> LoadProjectAsync()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ProjectServiceProvider) + " - " + nameof(LoadProjectAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var task = Task.Run(() =>
                {
                    var tiaPortal = _tiaPortalServiceProvider.GetTiaPortal() as TiaPortal;

                    if (tiaPortal != null)
                    {
                        if (tiaPortal.Projects != null && tiaPortal.Projects.Count > 0)
                        {
                            Project proj = tiaPortal.Projects.FirstOrDefault();

                            CurrentProject = proj;
                            _opennessDemoModel.ProjectModel.ProjectName = proj.Name;
                            _opennessDemoModel.ProjectModel.TargetDirectory = proj.Path.Directory;
                            _opennessDemoModel.ProjectModel.ProjectOpened = true;
                        }
                    }

                    return string.Empty;
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

        public Task<string> LoadMultiuserProjectAsync()
        {
            try
            {
                throw new NotImplementedException();
            }
            catch (Exception exception)
            {
                throw OpennessApiExceptionHandler.CatchedException(exception);
            }
        }

        public async Task<bool> SaveProjectAsync()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ProjectServiceProvider) + " - " + nameof(SaveProjectAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var task = Task.Run(() =>
                {
                    if (CurrentProject != null)
                    {
                        ((Project)CurrentProject).Save();
                        return true;
                    }

                    return false;
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

        public async Task<int> CloseProjectAsync()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ProjectServiceProvider) + " - " + nameof(CloseProjectAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var task = Task.Run(() =>
                {
                    TiaPortal = _tiaPortalServiceProvider.GetTiaPortal() as TiaPortal;
                    if (TiaPortal == null) return -1;

                    if (_opennessDemoModel.ProjectModel.ProjectOpened && TiaPortal?.Projects.Count > 0)
                    {
                        var project = TiaPortal.Projects.FirstOrDefault();
                        project?.Close();
                    }

                    _logicalProjectTree?.ProjectItems.Clear();
                    _physicalProjectTree?.ProjectItems.Clear();
                    _projectModel?.LogicalTree?.Items.Clear();
                    _projectModel?.PhysicalTree?.Items.Clear();

                    return TiaPortal.GetCurrentProcess().Id;

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

        public string GetCurrentProjectName()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ProjectServiceProvider) + " - " + nameof(GetCurrentProjectName) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var tiaPortal = _tiaPortalServiceProvider.GetTiaPortal() as TiaPortal;
                if (tiaPortal != null)
                {
                    var projectName = tiaPortal.Projects.FirstOrDefault()?.Name;
                    if (!string.IsNullOrEmpty(projectName))
                    {
                        WriteTraceLogProxy(processInfo.ProcessMessage + " - " + projectName);
                        return projectName;
                    }
                }

                return string.Empty;
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

        public DirectoryInfo GetCurrentProjectPath()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ProjectServiceProvider) + " - " + nameof(GetCurrentProjectPath) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var tiaPortal = _tiaPortalServiceProvider.GetTiaPortal() as TiaPortal;
                if (tiaPortal != null)
                {
                    return tiaPortal.Projects.FirstOrDefault()?.Path.Directory;
                }

                return null;
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

        public object GetCurrentProject()
        {
            return CurrentProject;
        }

        public void CreateNewGroup(string groupName, string parentGroup, Guid tag, bool logicalTree)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ProjectServiceProvider) + " - " + nameof(CreateNewGroup) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var parentProjectItem = GetProjectItem(parentGroup, tag, logicalTree);

                if (parentProjectItem != null)
                {
                    using (var groupService = new GroupEditorService(_traceLogService))
                    {
                        groupService.CreateGroup(parentProjectItem, groupName);
                    }

                    _plcSoftwareService?.CreateGroup(parentProjectItem.DeviceItem, groupName);
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

        #endregion // project

        #region import/export

        public async Task<bool> CaxImportAsync(FileInfo importFileInfo, CaxImportOption importOption)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ProjectServiceProvider) + " - " + nameof(CaxImportAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var task = Task.Run(() =>
                {
                    if (CurrentProject != null)
                    {

                        using (var importService = new ImportService(_traceLogService))
                        {
                            importService.CaxImport((Project)CurrentProject, importFileInfo, importOption);
                        }
                        return true;
                    }

                    return false;
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

        public async Task<bool> CaxExportAsync()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ProjectServiceProvider) + " - " + nameof(CaxExportAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var task = Task.Run(() =>
                {
                    if (CurrentProject != null)
                    {
                        using (var exportService = new ExportService(_traceLogService, _settingsService))
                        {
                            exportService.CaxExport((Project)CurrentProject);
                        }

                        return true;
                    }

                    return false;
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

        public async Task<bool> ImportElementAsync(IList<FileInfo> importFileInfos, bool importWithOverride, string header, Guid tag, bool logical)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ProjectServiceProvider) + " - " + nameof(ImportElementAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var task = Task.Run(() =>
                {
                    var projectItem = GetProjectItem(header, tag, logical);

                    if (projectItem != null)
                    {
                        var importDestination = projectItem.DeviceItem;

                        if (importDestination != null)
                        {
                            var tiaPortal = _tiaPortalServiceProvider.GetTiaPortal() as TiaPortal;

                            using (var exclusiveAccess = tiaPortal?.ExclusiveAccess("Import element"))
                            {
                                foreach (var fileInfo in importFileInfos)
                                {
                                    if (!string.IsNullOrEmpty(fileInfo.Name))
                                    {
                                        if (exclusiveAccess != null)
                                        {
                                            using (var transaction = exclusiveAccess.Transaction(CurrentProject, "Import element"))
                                            {
                                                using (var importService = new ImportService(_traceLogService))
                                                {
                                                    bool? result = _plcSoftwareService?.ImportElement(importDestination, fileInfo, ImportOptions.Override);
                                                    transaction.CommitOnDispose();
                                                    if (result != null && result == true)
                                                    {
                                                        WriteTraceLogProxy(processInfo.ProcessMessage + " - " + nameof(_plcSoftwareService) + " - Import element finished succeed");
                                                    }
                                                }
                                            }

                                            using (var transaction = exclusiveAccess.Transaction(CurrentProject, "Import element"))
                                            {
                                                using (var importService = new ImportService(_traceLogService))
                                                {
                                                    bool? result = _hmiTargetService?.ImportElement(importDestination, fileInfo, ImportOptions.Override);
                                                    transaction.CommitOnDispose();
                                                    if (result != null && result == true)
                                                    {
                                                        WriteTraceLogProxy(processInfo.ProcessMessage + " - " + nameof(_hmiTargetService) + " - Import element finished succeed");
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }


                    return false;
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
        /// Import folder structure 
        /// </summary>
        /// <param name="importFolderPath"></param>
        /// <param name="header"></param>
        /// <param name="tag"></param>
        /// <param name="logical"></param>
        /// <returns></returns>
        public async Task<bool> ImportStructureAsync(string importFolderPath, string header, Guid tag, bool logical)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ProjectServiceProvider) + " - " + nameof(ExportStructureAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var task = Task.Run(() =>
                {
                    var projectItem = GetProjectItem(header, tag, logical);

                    if (projectItem != null && projectItem.DeviceItem != null)
                    {
                        var tiaPortal = _tiaPortalServiceProvider.GetTiaPortal() as TiaPortal;

                        using (var exclusiveAccess = tiaPortal?.ExclusiveAccess("Import element"))
                        {
                            if (exclusiveAccess != null)
                            {
                                if (CheckIsPlcStructureDestination(projectItem.DeviceItem))
                                {
                                    using (var transaction = exclusiveAccess.Transaction(CurrentProject, "Import structure"))
                                    {
                                        bool? result = _plcSoftwareService?.ImportStructure(projectItem.DeviceItem, importFolderPath, ImportOptions.Override);
                                        transaction.CommitOnDispose();
                                        if (result != null && result == true)
                                        {
                                            WriteTraceLogProxy(processInfo.ProcessMessage + " - " + nameof(_plcSoftwareService) + " - Import structure finished succeed");
                                        }
                                    }
                                }

                                if (CheckIsHmiTargetStructureDestination(projectItem.DeviceItem))
                                {
                                    using (var transaction = exclusiveAccess.Transaction(CurrentProject, "Import structure"))
                                    {
                                        bool? result = _hmiTargetService?.ImportStructure(projectItem.DeviceItem, importFolderPath, ImportOptions.Override);
                                        transaction.CommitOnDispose();
                                        if (result != null && result == true)
                                        {
                                            WriteTraceLogProxy(processInfo.ProcessMessage + " - " + nameof(_hmiTargetService) + " - Import structure finished succeed");
                                        }
                                    }
                                }
                            }
                        }
                    }

                    return false;
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

        public async Task<bool> ExportStructureAsync(string header, Guid tag, bool logical)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ProjectServiceProvider) + " - " + nameof(ExportStructureAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var task = Task.Run(() =>
                {
                    var projectItem = GetProjectItem(header, tag, logical);

                    if (projectItem != null)
                    {
                        var exportPath = _settingsService.GetExportPath();
                        var exportWithDefaults = _settingsService.GetExportWithDefaults();
                        var exportReadOnly = _settingsService.GetExportReadOnly();
                        var projectName = CurrentProject.Name;

                        _plcSoftwareService?.ExportStructure(projectItem.DeviceItem, exportWithDefaults, exportReadOnly, exportPath, projectName);

                        _hmiTargetService?.ExportStructure(projectItem.DeviceItem, exportWithDefaults, exportReadOnly, exportPath, projectName);
                    }

                    return false;
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

        public bool CheckIfCanImportElement(string header, Guid tag, bool logical)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ProjectServiceProvider) + " - " + nameof(CheckIfCanImportElement) };
            bool result = false;

            var projectItem = GetProjectItem(header, tag, logical);

            if (projectItem != null)
            {
                var type = projectItem.DeviceItem?.GetType();
                WriteTraceLogProxy(processInfo.ProcessMessage + " -> Type: " + type?.Name);

                var propertyInfos = type?.GetProperties();
                if (propertyInfos != null)
                {
                    foreach (var propertyInfo in propertyInfos)
                    {
                        var propertyTypes = propertyInfo.PropertyType;
                        var methodInfos = propertyTypes?.GetMethods();
                        var refMethods = new[] { "Import", "ImportScreenGlobalElements", "ImportScreenOverview" };

                        var meth = (from me in methodInfos
                                    where refMethods.Contains(me.Name) && me.GetParameters().Length == 2
                                    select me).ToList();

                        foreach (var methodInfo in meth)
                        {
                            IList<Type> parameterTypeReferenceList = new List<Type>() { typeof(FileInfo), typeof(ImportOptions) };
                            IList<Type> parameterTypeList = new List<Type>();

                            var parameters = methodInfo.GetParameters();
                            if (parameters.Length > 0)
                            {
                                foreach (var parameter in parameters)
                                {
                                    parameterTypeList.Add(parameter.ParameterType);
                                }

                                result = parameterTypeList.SequenceEqual(parameterTypeReferenceList);
                            }
                        }
                    }
                }
            }

            return result;
        }

        /// <summary>
        /// Indicates if selected tree item can be a structure import destination
        /// </summary>
        /// <param name="header"></param>
        /// <param name="tag"></param>
        /// <param name="logical"></param>
        /// <returns></returns>
        public bool CheckIfCanImportStructure(string header, Guid tag, bool logical)
        {
            bool result = false;

            var projectItem = GetProjectItem(header, tag, logical);

            if (projectItem != null)
            {
                result = CheckIsPlcStructureDestination(projectItem.DeviceItem) ||
                         CheckIsHmiTargetStructureDestination(projectItem.DeviceItem);
            }

            return result;
        }

        public bool CheckIfCanExportExecute(string header, Guid tag, bool logical)
        {
            bool result = false;

            var projectItem = GetProjectItem(header, tag, logical);

            if (projectItem != null)
            {
                result = !(projectItem.DeviceItem is Device || projectItem.DeviceItem is DeviceItem || CheckIsPlcUnitSystemGroup(projectItem.DeviceItem)) ||
                         CheckIsPlcSoftware(projectItem.DeviceItem) ||
                         CheckIsHmiSoftware(projectItem.DeviceItem) ||
                         CheckIsHmiTarget(projectItem.DeviceItem) ||
                         CheckIsVbScript(projectItem.DeviceItem);
            }
            return result;
        }

        public object GetExportableObject(ProjectItem projectItem)
        {
            if (projectItem != null)
            {
                if (CheckIsPlcSoftware(projectItem.DeviceItem) ||
                    CheckIsHmiSoftware(projectItem.DeviceItem) ||
                    CheckIsHmiTarget(projectItem.DeviceItem) ||
                    CheckIsVbScript(projectItem.DeviceItem))
                {
                    return projectItem.DeviceItem;
                }
            }

            return null;
        }

        private bool CheckIsPlcSoftware(object item)
        {
            if (_plcSoftwareService != null)
            {
                return _plcSoftwareService.IsPlcSoftware(item);
            }
            return false;
        }

        private bool CheckIsPlcUnitSystemGroup(object item)
        {
            if (_plcSoftwareService != null)
            {
                return _plcSoftwareService.IsPlcUnitSystemGroup(item);
            }
            return false;
        }

        private bool CheckIsHmiSoftware(object item)
        {
            if (_hmiSoftwareService != null)
            {
                return _hmiSoftwareService.IsHmiSoftware(item);
            }
            return false;
        }

        private bool CheckIsHmiTarget(object item)
        {
            if (_hmiTargetService != null)
            {
                return _hmiTargetService.IsHmiTarget(item);
            }
            return false;
        }

        private bool CheckIsVbScript(object item)
        {
            if (_hmiTargetService != null)
            {
                return _hmiTargetService.IsVbScript(item);
            }
            return false;
        }

        private bool CheckIsPlcStructureDestination(object item)
        {
            if (_plcSoftwareService != null)
            {
                return _plcSoftwareService.IsPlcStructureDestination(item);
            }
            return false;
        }

        private bool CheckIsHmiTargetStructureDestination(object item)
        {
            if (_hmiTargetService != null)
            {
                return _hmiTargetService.IsHmiTargetStructureDestination(item);
            }
            return false;
        }

        #endregion // import/export

        #region plc

        public async Task<bool> AddExternalSourceAsync(IList<FileInfo> sourceFileInfos, string header, Guid tag, bool logical)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ProjectServiceProvider) + " - " + nameof(AddExternalSourceAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var task = Task.Run(() =>
                {
                    var result = false;

                    var projectItem = GetProjectItem(header, tag, logical);

                    if (projectItem != null)
                    {
                        var destinationItem = projectItem.DeviceItem;

                        if (destinationItem != null)
                        {
                            var tiaPortal = _tiaPortalServiceProvider.GetTiaPortal() as TiaPortal;

                            using (var plcService = new PlcService(_traceLogService))
                            {
                                foreach (var fileInfo in sourceFileInfos)
                                {
                                    using (var exclusiveAccess = tiaPortal?.ExclusiveAccess("Import element"))
                                    {
                                        using (var transaction = exclusiveAccess?.Transaction(CurrentProject, "Import element"))
                                        {
                                            plcService.AddExternalSource(destinationItem as PlcExternalSourceGroup, fileInfo);
                                            transaction?.CommitOnDispose();
                                            result = true;
                                        }
                                    }
                                }
                            }
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

        public async Task<bool> GenerateBlockFromSourceAsync(string header, Guid tag, bool logical)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ProjectServiceProvider) + " - " + nameof(GenerateBlockFromSourceAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var task = Task.Run(() =>
                {
                    var result = false;

                    var projectItem = GetProjectItem(header, tag, logical);

                    if (projectItem != null)
                    {
                        var destinationItem = projectItem.DeviceItem;

                        if (destinationItem != null)
                        {
                            using (var plcService = new PlcService(_traceLogService))
                            {
                                plcService.GenerateBlockFromSource(destinationItem as PlcExternalSource);
                                result = true;
                            }
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

        public async Task<bool> GenerateSourceFromBlockAsync(FileInfo destinationFileInfo, string header, Guid tag, bool logical)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ProjectServiceProvider) + " - " + nameof(GenerateSourceFromBlockAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var task = Task.Run(() =>
                {
                    var result = false;
                    var withDependencies = true;

                    var projectItem = GetProjectItem(header, tag, logical);

                    if (projectItem != null)
                    {
                        var blockItem = projectItem.DeviceItem as IEngineeringInstance;
                        var blockAsSource = projectItem.DeviceItem as IEngineeringInstance;

                        if (blockItem != null)
                        {
                            do
                            {
                                blockItem = blockItem.Parent;
                            }
                            while (!(blockItem is PlcSoftware));

                            using (var plcService = new PlcService(_traceLogService))
                            {
                                plcService.GenerateSourceFromBlock(blockItem as PlcSoftware, blockAsSource, destinationFileInfo, withDependencies);
                            }
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

        public bool CheckIfCanAddExternalSource(string header, Guid tag, bool logical)
        {
            try
            {
                bool result = false;

                var projectItem = GetProjectItem(header, tag, logical);

                if (projectItem != null)
                {
                    if (projectItem.DeviceItem is PlcExternalSourceSystemGroup)
                    {
                        result = true;
                    }
                }

                return result;
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

        public bool CheckIfCanGenerateBlockFromSource(string header, Guid tag, bool logical)
        {
            try
            {
                bool result = false;

                var projectItem = GetProjectItem(header, tag, logical);

                if (projectItem != null)
                {
                    if (projectItem.DeviceItem is PlcExternalSource)
                    {
                        result = true;
                    }
                }

                return result;
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

        public bool CheckIfCanGenerateSourceFromBlock(string header, Guid tag, bool logical)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ProjectServiceProvider) + " - " + nameof(CheckIfCanGenerateSourceFromBlock) };
            try
            {
                bool result = false;

                var projectItem = GetProjectItem(header, tag, logical);

                if (projectItem != null)
                {
                    if (projectItem.DeviceItem is PlcType)
                    {
                        WriteTraceLogProxy(processInfo.ProcessMessage + " -> PlcType");
                        result = true;
                    }

                    if (projectItem.DeviceItem is PlcBlock plcBlock)
                    {
                        if (plcBlock.ProgrammingLanguage == ProgrammingLanguage.DB ||
                            plcBlock.ProgrammingLanguage == ProgrammingLanguage.SCL ||
                            plcBlock.ProgrammingLanguage == ProgrammingLanguage.STL)
                        {
                            WriteTraceLogProxy(processInfo.ProcessMessage + " -> PlcBlock");
                            result = true;
                        }
                    }
                }

                return result;
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

        #endregion // plc

        #region editor

        public void ShowEditor(string viewName)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ProjectServiceProvider) + " - " + nameof(ShowEditor) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var viewType = EnumService.GetEnumValue<View>(viewName);

                CurrentProject.ShowHwEditor(viewType);
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

        public void OpenEditor(string header, Guid tag, bool logical)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ProjectServiceProvider) + " - " + nameof(OpenEditor) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var projectItem = GetProjectItem(header, tag, logical);

                if (projectItem != null)
                {
                    if (projectItem.DeviceItem is Device projectItemDevice)
                    {
                        projectItemDevice.ShowInEditor(View.Device);
                    }
                    else
                    {
                        var type = projectItem.DeviceItem.GetType();
                        var methodInfo = type.GetMethod("ShowInEditor");

                        if (methodInfo == null && type.BaseType != null)
                        {
                            methodInfo = type.BaseType.GetMethod("ShowInEditor");

                        }

                        if (methodInfo != null)
                        {
                            methodInfo.Invoke(projectItem.DeviceItem, null);
                        }
                    }
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

        private ProjectItem GetProjectItem(string header, Guid tag, bool logical)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ProjectServiceProvider) + " - " + nameof(GetProjectItem) };
            ProjectItem projectItem = null;

            if (logical)
            {
                projectItem = (from item in _logicalProjectTree.ProjectItems
                               where item.Header == header && item.Tag == tag
                               select item).FirstOrDefault();
            }
            else
            {
                projectItem = (from item in _physicalProjectTree.ProjectItems
                               where item.Header == header && item.Tag == tag
                               select item).FirstOrDefault();
            }

            if (projectItem != null)
            {
                WriteTraceLogProxy(processInfo.ProcessMessage + " - " + projectItem.Header + ", " + projectItem.TypeInfo);
            }

            return projectItem;
        }

        #endregion // editor

        #region compile

        public void DoCompile(string header, Guid tag, bool logical)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ProjectServiceProvider) + " - " + nameof(DoCompile) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var projectItem = GetProjectItem(header, tag, logical);

                if (projectItem != null)
                {
                    var methodInfo = GetGenericMethodInfo(projectItem, typeof(ICompilable));

                    if (methodInfo != null)
                    {
                        var compiler = GetCompiler(methodInfo, projectItem);

                        if (compiler != null)
                        {
                            _compilerResult = compiler.Compile();

                            var compilerMessage = "Compiling " + projectItem.Header;
                            WriteTraceLogProxy(processInfo.ProcessMessage + " - " + compilerMessage);

                            if (_compilerResult.Messages.Count > 0)
                            {
                                if (_compilerResult.Messages != null && _compilerResult.Messages.Count > 0)
                                {
                                    GetCompilerMessages(string.Empty, string.Empty, _compilerResult.Messages);
                                }
                            }
                        }
                    }
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

        private ICompilable GetCompiler(MethodInfo methodInfo, ProjectItem projectItem)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ProjectServiceProvider) + " - " + nameof(GetCompiler) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                ICompilable compiler = null;

                compiler = methodInfo.Invoke(projectItem.DeviceItem, null) as ICompilable;

                return compiler;
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

        private void GetCompilerMessages(string rootPath, string path, CompilerResultMessageComposition messageComposition)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ProjectServiceProvider) + " - " + nameof(GetCompilerMessages) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                foreach (var message in messageComposition)
                {
                    var messagePath = message.Path?.Trim(' ');

                    if (message.Messages != null && message.Messages.Count > 0)
                    {
                        string resultPath = string.Empty;

                        if (!string.IsNullOrEmpty(path))
                        {
                            if (!string.IsNullOrEmpty(messagePath))
                            {
                                resultPath = path + ">" + messagePath;
                            }
                        }
                        else
                        {
                            rootPath = messagePath;
                            resultPath = rootPath;
                        }
                    }

                    if (!string.IsNullOrWhiteSpace(message.Description))
                    {
                        if (!string.IsNullOrWhiteSpace(path))
                        {
                            string compilerMessage;

                            if (message.Path != null && !string.IsNullOrEmpty(messagePath))
                            {
                                compilerMessage = message.State + " | Path: " + path + ">" + messagePath + " | Description: " + message.Description;
                            }
                            else
                            {
                                compilerMessage = message.State + " | Path: " + path + " | Description: " + message.Description;
                            }

                            WriteTraceLogProxy(compilerMessage);
                            path = rootPath;
                        }

                        if (string.IsNullOrWhiteSpace(path))
                        {
                            string compilerMessage;

                            if (message.Path != null && !string.IsNullOrEmpty(messagePath))
                            {
                                compilerMessage = message.State + " | Path: " + messagePath + " | Description: " + message.Description;
                            }
                            else
                            {
                                compilerMessage = message.State + " | Description: " + message.Description;
                            }

                            WriteTraceLogProxy(compilerMessage);
                            path = rootPath;
                        }
                    }
                    else
                    {
                        if (message.Path != null)
                        {
                            path = path + ">" + messagePath;
                        }
                    }

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

        public bool CheckIfCompilable(string header, Guid tag, bool logical)
        {
            bool result = false;

            var projectItem = GetProjectItem(header, tag, logical);

            if (projectItem != null)
            {
                var methodInfo = GetGenericMethodInfo(projectItem, typeof(ICompilable));

                if (methodInfo != null)
                {
                    var compiler = GetCompiler(methodInfo, projectItem);

                    if (compiler != null)
                    {
                        result = true;
                    }

                }
            }

            return result;
        }
        #endregion // compile

        #region content

        public Dictionary<string, string> ReadProperties(string header, Guid tag)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ProjectServiceProvider) + " - " + nameof(ReadProperties) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var deviceItem = (from x in _plcTree.ProjectItems
                                  where x.Header == header && x.Tag == tag
                                  select x.DeviceItem).FirstOrDefault();

                if (deviceItem != null)
                {
                    var contentDictionary = new Dictionary<string, string>();
                    var attributeInfos = ((IEngineeringObject)deviceItem).GetAttributeInfos();

                    var attributeBlacklist = ContentBlackList.AttributeInfoBlackList;

                    var referenceNames = (from a in attributeInfos
                                          join b in attributeBlacklist on a.Name equals b into r
                                          from ad in r.DefaultIfEmpty()
                                          where ad == null
                                          select a.Name).ToList();

                    foreach (var attributeName in referenceNames)
                    {
                        string propertyValue;

                        if (((IEngineeringObject)deviceItem).GetAttribute(attributeName) == null)
                        {
                            propertyValue = "empty";
                        }
                        else
                        {
                            propertyValue = ((IEngineeringObject)deviceItem).GetAttribute(attributeName).ToString();
                        }
                        if (contentDictionary.ContainsKey(attributeName) == false)
                            contentDictionary.Add(attributeName, propertyValue);
                    }
                    ContentDictionary.Clear();
                    ContentDictionary = contentDictionary;
                }

                return ContentDictionary;
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

        #endregion // content

        #region tree structure

        public Tree GetProjectTree()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ProjectServiceProvider) + " - " + nameof(GetProjectTree) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            return _projectModel.ProjectTree;
        }

        public async Task<Tree> LoadTreeStructureAsync(bool loadLogicalFirst)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ProjectServiceProvider) + " - " + nameof(LoadTreeStructureAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage + " - load logical: " + loadLogicalFirst);

            try
            {
                var task = Task.Run(() =>
                {
                    var tree = new Tree();

                    var tiaPortal = _tiaPortalServiceProvider.GetTiaPortal() as TiaPortal;
                    if (tiaPortal != null)
                    {
                        if (!_opennessDemoModel.TiaPortalDisposed)
                        {
                            Project tiaPortalProject = null;

                            if (tiaPortal.Projects != null && tiaPortal.Projects.Count > 0)
                            {
                                tiaPortalProject = tiaPortal.Projects.FirstOrDefault();
                            }

                            if (_opennessDemoModel.ProjectModel.ProjectOpened && tiaPortalProject != null)
                            {
                                if (loadLogicalFirst)
                                {
                                    TraverseLogicalTree(tiaPortalProject);
                                    tree = _projectModel.LogicalTree;
                                }
                                else
                                {
                                    TraversePhysicalTree(tiaPortalProject);
                                    tree = _projectModel.PhysicalTree;
                                }
                            }
                        }
                    }

                    return tree;
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

        public Task<Tree> LoadLocalSessionTreeStructureAsync(bool loadLogicalFirst)
        {
            try
            {
                throw new NotImplementedException();
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

        #region logical tree

        private void TraverseLogicalTree(Project project)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ProjectServiceProvider) + " - " + nameof(TraverseLogicalTree) };
            WriteTraceLogProxy(processInfo.ProcessMessage);


            Guid guid = Guid.Empty;
            var engineeringProjectItem = new ProjectItem();

            var projectTree = new Tree();
            projectTree.ExpandSubTree = false;
            var projectTreeItem = new TreeItem();

            if (project is IEngineeringObject)
            {
                projectTreeItem.Header = project.Name;
                projectTreeItem.Tag = Guid.NewGuid();
                engineeringProjectItem.ProjectItems.Add(new ProjectItem() { Header = projectTreeItem.Header, Tag = projectTreeItem.Tag, DeviceItem = project, TypeInfo = TreeTypeInformation.IsProject });

                foreach (var device in project.Devices)
                {
                    if (device.Items != null)
                    {
                        guid = Guid.NewGuid();
                        var deviceTreeItem = new TreeItem() { Header = device.Name, Tag = guid };
                        engineeringProjectItem.ProjectItems.Add(new ProjectItem() { Header = device.Name, Tag = guid, DeviceItem = device, TypeInfo = TreeTypeInformation.IsDevice });
                        GetLogicalTreeItems(device, deviceTreeItem, engineeringProjectItem);
                        projectTreeItem.Items.Add(deviceTreeItem);
                    }
                }

                foreach (var deviceGroup in project.DeviceGroups)
                {
                    GetLogicalDeviceGroup(deviceGroup, projectTreeItem, engineeringProjectItem);
                }

                if (project.UngroupedDevicesGroup != null)
                {
                    GetLogicalUngroupedDeviceGroup(project.UngroupedDevicesGroup, projectTreeItem, engineeringProjectItem);
                }
            }

            projectTree.Items.Add(projectTreeItem);
            _projectModel.LogicalTree = projectTree;

            _logicalProjectTree = new ProjectContent();
            _logicalProjectTree.ProjectItems = engineeringProjectItem.ProjectItems;
        }

        private void GetLogicalTreeItems(HardwareObject device, TreeItem subTree, ProjectItem engineeringProjectItem)
        {
            Guid guid = Guid.Empty;
            var subsubTree = new TreeItem();

            if (device != null)
            {
                foreach (var item in device.Items)
                {
                    guid = Guid.NewGuid();
                    subsubTree = new TreeItem() { Header = item.Name, Tag = guid };

                    engineeringProjectItem.ProjectItems.Add(new ProjectItem() { Header = item.Name, Tag = guid, DeviceItem = item });

                    _plcSoftwareService?.GetStructure(item, subsubTree, engineeringProjectItem, EngineeringProjectModel);

                    _hmiSoftwareService?.GetStructure(item, subsubTree, engineeringProjectItem, EngineeringProjectModel);

                    _sinamicsService?.GetStructure(item, subsubTree, engineeringProjectItem, EngineeringProjectModel);

                    GetHmiTargetStructure(item, subsubTree, engineeringProjectItem);

                    subTree.Items.Add(subsubTree);

                    GetLogicalTreeItems(item, subsubTree, engineeringProjectItem);

                }

                if (device is Device device1)
                {
                    GetLogicalUnpluggedItems(device1, subTree, engineeringProjectItem);
                }
            }
            else
            {
                subsubTree.Header = "No HardwareObject";
            }
        }

        private void GetLogicalUnpluggedItems(Device device, TreeItem treeItem, ProjectItem engineeringProjectItem)
        {
            bool foundUnpluggedDevices = false;
            Guid guid = Guid.Empty;
            guid = Guid.NewGuid();
            var deviceTreeItem = new TreeItem() { Header = "Unplugged modules", Tag = guid };
            var projectTreeItem = new ProjectItem() { Header = "Unplugged modules", Tag = guid, DeviceItem = null };

            foreach (var unpluggedItem in device.UnpluggedItems)
            {
                guid = Guid.NewGuid();
                var unpluggedDeviceTreeItem = new TreeItem() { Header = unpluggedItem.Name, Tag = guid };
                engineeringProjectItem.ProjectItems.Add(new ProjectItem() { Header = unpluggedDeviceTreeItem.Header, Tag = guid, DeviceItem = unpluggedItem, TypeInfo = TreeTypeInformation.IsUnpluggedDevice });

                GetLogicalTreeItems(unpluggedItem, unpluggedDeviceTreeItem, engineeringProjectItem);
                deviceTreeItem.Items.Add(unpluggedDeviceTreeItem);
                foundUnpluggedDevices = true;
            }

            if (foundUnpluggedDevices)
            {
                treeItem.Items.Add(deviceTreeItem);
                engineeringProjectItem.ProjectItems.Add(projectTreeItem);
            }
        }

        private void GetLogicalDeviceGroup(DeviceUserGroup deviceGroup, TreeItem treeItem, ProjectItem engineeringProjectItem)
        {
            Guid guid = Guid.Empty;
            guid = Guid.NewGuid();
            var deviceTreeItem = new TreeItem() { Header = deviceGroup.Name, Tag = guid };
            engineeringProjectItem.ProjectItems.Add(new ProjectItem() { Header = deviceGroup.Name, Tag = guid, DeviceItem = deviceGroup, TypeInfo = TreeTypeInformation.IsDeviceUserGroup });
            treeItem.Items.Add(deviceTreeItem);

            foreach (var device in deviceGroup.Devices)
            {
                if (device.Items != null)
                {
                    guid = Guid.NewGuid();
                    var devicetreeItem = new TreeItem() { Header = device.Name, Tag = guid };
                    engineeringProjectItem.ProjectItems.Add(new ProjectItem() { Header = devicetreeItem.Header, Tag = guid, DeviceItem = device, TypeInfo = TreeTypeInformation.IsDevice });
                    GetLogicalTreeItems(device, devicetreeItem, engineeringProjectItem);
                    deviceTreeItem.Items.Add(devicetreeItem);
                }
            }

            foreach (var deviceSubGroup in deviceGroup.Groups)
            {
                GetLogicalDeviceGroup(deviceSubGroup, deviceTreeItem, engineeringProjectItem);
            }
        }

        private void GetLogicalUngroupedDeviceGroup(DeviceSystemGroup deviceGroup, TreeItem treeItem, ProjectItem engineeringProjectItem)
        {
            Guid guid = Guid.Empty;
            guid = Guid.NewGuid();
            var deviceTreeItem = new TreeItem() { Header = deviceGroup.Name, Tag = guid };
            engineeringProjectItem.ProjectItems.Add(new ProjectItem() { Header = deviceGroup.Name, Tag = guid, DeviceItem = deviceGroup, TypeInfo = TreeTypeInformation.IsDeviceSystemGroup });
            treeItem.Items.Add(deviceTreeItem);

            foreach (var device in deviceGroup.Devices)
            {
                if (device.Items != null)
                {
                    guid = Guid.NewGuid();
                    var devicetreeItem = new TreeItem() { Header = device.Name, Tag = guid };
                    engineeringProjectItem.ProjectItems.Add(new ProjectItem() { Header = devicetreeItem.Header, Tag = guid, DeviceItem = device, TypeInfo = TreeTypeInformation.IsDevice });
                    GetLogicalTreeItems(device, devicetreeItem, engineeringProjectItem);
                    deviceTreeItem.Items.Add(devicetreeItem);
                }
            }
        }

        public Tree GetLogicalTree()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ProjectServiceProvider) + " - " + nameof(GetLogicalTree) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            _plcTree = _logicalProjectTree;
            return _projectModel.LogicalTree;
        }

        #endregion // logical tree

        #region physical tree

        private void TraversePhysicalTree(Project project)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ProjectServiceProvider) + " - " + nameof(TraversePhysicalTree) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            Guid guid = Guid.Empty;
            var engineeringProjectItem = new ProjectItem();

            var projectTree = new Tree();
            projectTree.ExpandSubTree = false;
            var projectTreeItem = new TreeItem();

            if (project is IEngineeringObject)
            {
                projectTreeItem.Header = project.Name;
                projectTreeItem.Tag = Guid.NewGuid();
                engineeringProjectItem.ProjectItems.Add(new ProjectItem() { Header = projectTreeItem.Header, Tag = projectTreeItem.Tag, DeviceItem = project, TypeInfo = TreeTypeInformation.IsProject });

                foreach (var device in project.Devices)
                {
                    if (device.DeviceItems != null)
                    {
                        guid = Guid.NewGuid();
                        var deviceTreeItem = new TreeItem() { Header = device.Name, Tag = guid };
                        engineeringProjectItem.ProjectItems.Add(new ProjectItem() { Header = device.Name, Tag = guid, DeviceItem = device, TypeInfo = TreeTypeInformation.IsDevice });
                        GetPhysicalTreeItems(device, deviceTreeItem, engineeringProjectItem);
                        projectTreeItem.Items.Add(deviceTreeItem);
                    }
                }

                foreach (var deviceGroup in project.DeviceGroups)
                {
                    GetPhysicalDeviceGroup(deviceGroup, projectTreeItem, engineeringProjectItem);
                }

                if (project.UngroupedDevicesGroup != null)
                {
                    GetPhysicalUngroupedDeviceGroup(project.UngroupedDevicesGroup, projectTreeItem, engineeringProjectItem);
                }
            }

            projectTree.Items.Add(projectTreeItem);
            _projectModel.PhysicalTree = projectTree;

            _physicalProjectTree = new ProjectContent();
            _physicalProjectTree.ProjectItems = engineeringProjectItem.ProjectItems;
        }

        private void GetPhysicalTreeItems(HardwareObject device, TreeItem subTree, ProjectItem engineeringProjectItem)
        {
            Guid guid = Guid.Empty;
            var subsubTree = new TreeItem();

            if ((device != null))
            {
                foreach (var deviceItem in device.DeviceItems)
                {
                    guid = Guid.NewGuid();
                    subsubTree = new TreeItem() { Header = deviceItem.Name, Tag = guid };
                    engineeringProjectItem.ProjectItems.Add(new ProjectItem() { Header = deviceItem.Name, Tag = guid, DeviceItem = deviceItem });

                    _plcSoftwareService?.GetStructure(deviceItem, subsubTree, engineeringProjectItem, EngineeringProjectModel);

                    _hmiSoftwareService?.GetStructure(deviceItem, subsubTree, engineeringProjectItem, EngineeringProjectModel);

                    GetHmiTargetStructure(deviceItem, subsubTree, engineeringProjectItem);

                    subTree.Items.Add(subsubTree);

                    GetPhysicalTreeItems(deviceItem, subsubTree, engineeringProjectItem);
                }
            }
            else
            {
                subsubTree.Header = "No HardwareObject";
            }
        }

        private void GetPhysicalDeviceGroup(DeviceUserGroup deviceGroup, TreeItem treeItem, ProjectItem engineeringProjectItem)
        {
            Guid guid = Guid.Empty;
            guid = Guid.NewGuid();
            var deviceTreeItem = new TreeItem() { Header = deviceGroup.Name, Tag = guid };
            engineeringProjectItem.ProjectItems.Add(new ProjectItem() { Header = deviceGroup.Name, Tag = guid, DeviceItem = deviceGroup });
            treeItem.Items.Add(deviceTreeItem);

            foreach (var device in deviceGroup.Devices)
            {
                if (device.Items != null)
                {
                    guid = Guid.NewGuid();
                    var devicetreeItem = new TreeItem() { Header = device.Name, Tag = guid };
                    engineeringProjectItem.ProjectItems.Add(new ProjectItem() { Header = devicetreeItem.Header, Tag = guid, DeviceItem = device });
                    GetPhysicalTreeItems(device, devicetreeItem, engineeringProjectItem);
                    deviceTreeItem.Items.Add(devicetreeItem);
                }
            }

            foreach (var deviceSubGroup in deviceGroup.Groups)
            {
                GetPhysicalDeviceGroup(deviceSubGroup, deviceTreeItem, engineeringProjectItem);
            }
        }

        private void GetPhysicalUngroupedDeviceGroup(DeviceSystemGroup deviceGroup, TreeItem treeItem, ProjectItem engineeringProjectItem)
        {
            Guid guid = Guid.Empty;
            guid = Guid.NewGuid();
            var deviceTreeItem = new TreeItem() { Header = deviceGroup.Name, Tag = guid };
            engineeringProjectItem.ProjectItems.Add(new ProjectItem() { Header = deviceGroup.Name, Tag = guid, DeviceItem = deviceGroup });
            treeItem.Items.Add(deviceTreeItem);

            foreach (var device in deviceGroup.Devices)
            {
                if (device.Items != null)
                {
                    guid = Guid.NewGuid();
                    var devicetreeItem = new TreeItem() { Header = device.Name, Tag = guid };
                    engineeringProjectItem.ProjectItems.Add(new ProjectItem() { Header = devicetreeItem.Header, Tag = guid, DeviceItem = device });
                    GetPhysicalTreeItems(device, devicetreeItem, engineeringProjectItem);
                    deviceTreeItem.Items.Add(devicetreeItem);
                }
            }
        }


        public Tree GetPhysicalTree()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ProjectServiceProvider) + " - " + nameof(GetPhysicalTree) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            _plcTree = _physicalProjectTree;
            return _projectModel.PhysicalTree;
        }

        #endregion // physical tree

        #region common

        public TreeTypeInformation GetTypeInformation(string header, Guid tag, bool logical)
        {
            if (logical)
            {
                var treeTypeInfo = (from item in _logicalProjectTree.ProjectItems
                                    where item.Header == header && item.Tag == tag
                                    select item.TypeInfo).FirstOrDefault();
                return treeTypeInfo;
            }
            else
            {
                var treeTypeInfo = (from item in _physicalProjectTree.ProjectItems
                                    where item.Header == header && item.Tag == tag
                                    select item.TypeInfo).FirstOrDefault();
                return treeTypeInfo;
            }
        }

        public object GetTreeItemObject(string header, Guid tag, bool logical)
        {
            if (logical)
            {
                var deviceItem = (from item in _logicalProjectTree.ProjectItems
                                  where item.Header == header && item.Tag == tag
                                  select item.DeviceItem).FirstOrDefault();
                return deviceItem;
            }
            else
            {
                var deviceItem = (from item in _physicalProjectTree.ProjectItems
                                  where item.Header == header && item.Tag == tag
                                  select item.DeviceItem).FirstOrDefault();
                return deviceItem;
            }
        }

        public IList<ProjectItem> GetTreeTypeItems(object itemType, bool logical)
        {
            if (itemType is LibraryItem libraryItem)
            {
                var destinationContainer = CopyDestinationMapping.GetDestinationContainer(libraryItem.Item.GetType());

                if (logical)
                {
                    if (destinationContainer != null)
                    {
                        var itemsContainer = _logicalProjectTree.ProjectItems.Where(a =>
                            destinationContainer.Any(b => b == a.DeviceItem?.GetType())).ToList();

                        return itemsContainer;
                    }
                }
                else
                {
                    if (destinationContainer != null)
                    {
                        var itemsContainer = _physicalProjectTree.ProjectItems.Where(a =>
                            destinationContainer.Any(b => b == a.DeviceItem?.GetType())).ToList();

                        return itemsContainer;
                    }
                }
            }

            return null;
        }

        #endregion // common

        #region hmi structure

        private void GetHmiTargetStructure(DeviceItem deviceItem, TreeItem treeItem, ProjectItem engineeringProjectItem)
        {
            var software = EngineeringProjectModel.CheckHmiTarget(deviceItem);
            if (software != null)
            {
                Guid guid = Guid.Empty;
                var subTreeItem = new TreeItem();
                var subEngineeringTreeItem = new ProjectItem();

                guid = Guid.NewGuid();
                subTreeItem.Header = EngineeringProjectModel.GetHmiTargetName(software);
                subTreeItem.Tag = guid;
                subEngineeringTreeItem = new ProjectItem() { Header = subTreeItem.Header, Tag = guid, DeviceItem = software };

                treeItem.Items.Add(subTreeItem);
                engineeringProjectItem.ProjectItems.Add(subEngineeringTreeItem);
            }
        }

        #endregion // hmi structure

        #endregion // tree structure

        private MethodInfo GetGenericMethodInfo(ProjectItem projectItem, Type forType)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ProjectServiceProvider) + " - " + nameof(GetGenericMethodInfo) };
            try
            {
                WriteTraceLogProxy(processInfo.ProcessMessage);

                MethodInfo genericMethodInfo = null;

                var type = projectItem.DeviceItem?.GetType();

                if (type != null)
                {
                    WriteTraceLogProxy(processInfo.ProcessMessage + " - " + projectItem.Header + ", " + type.FullName);

                    var methodInfo = type.GetMethod("GetService");

                    if (methodInfo == null && type.BaseType != null)
                    {
                        methodInfo = type.BaseType.GetMethod("GetService");

                    }

                    if (methodInfo != null)
                    {
                        try
                        {
                            genericMethodInfo = methodInfo.MakeGenericMethod(forType);
                            WriteTraceLogProxy(processInfo.ProcessMessage + " - " + projectItem.Header + ", " + genericMethodInfo.Name);
                        }
                        catch (Exception e)
                        {
                            Debug.WriteLine(e.Message);
                        }
                    }
                }

                return genericMethodInfo;
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
