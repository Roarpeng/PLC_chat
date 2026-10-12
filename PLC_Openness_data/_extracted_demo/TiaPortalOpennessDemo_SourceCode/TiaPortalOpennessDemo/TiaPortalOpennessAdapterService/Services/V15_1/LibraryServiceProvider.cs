extern alias V15_1;
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using System.Windows;
using TiaPortalOpennessAdapter.Services;
using TiaPortalOpennessAdapterBase.Base;
using TiaPortalOpennessAdapterBase.Enums;
using TiaPortalOpennessAdapterBase.Models;
using TiaPortalOpennessAdapterContracts;
using TiaPortalOpennessInfrastructure.Contracts;
using TiaPortalOpennessInfrastructure.Exceptions;
using TiaPortalOpennessInfrastructure.Utils;
using V15_1::Siemens.Engineering;
using V15_1::Siemens.Engineering.Library;
using V15_1::Siemens.Engineering.Library.MasterCopies;
using V15_1::Siemens.Engineering.Library.Types;

namespace TiaPortalOpennessAdapterService.Services.V15_1
{
    /// <summary>
    /// Implementation of library service
    /// </summary>
    public class LibraryServiceProvider : ObservableObject, ILibraryServiceProvider
    {
        #region fields

        private IOpennessDemoModel        _opennessDemoModel;
        private ITraceLogService          _traceLogService;
        private ITiaPortalServiceProvider _tiaPortalServiceProvider;

        private IPlcSoftwareService       _plcSoftwareService;
        private IHmiSoftwareService       _hmiSoftwareService;
        private IHmiTargetService         _hmiTargetService;

        private ProjectModel              _projectModel;

        private ProjectLibrary            _projectLibrary;
        private GlobalLibraryComposition  _globalLibraries;

        private LibraryContent            _projectLibraryCollection;
        private LibraryContent            _globalLibraryCollection;

        private IList<GlobalLibraryInfo>  _availableLibraryInfos;
        private IList<LibraryInfo>        _globalLibraryInfos;

        #endregion // fields

        #region ctor

        /// <summary>
        /// Constructor with initialization
        /// </summary>
        /// <param name="traceLogService"></param>
        public LibraryServiceProvider(ITraceLogService traceLogService)
        {
            _traceLogService = traceLogService;
        }

        /// <summary>
        /// Constructor with initialization
        /// </summary>
        /// <param name="opennessDemoModel"></param>
        /// <param name="traceLogService"></param>
        /// <param name="tiaPortalServiceProvider"></param>
        /// <param name="projectServiceProvider"></param>
        /// <param name="multiuserServiceProvider"></param>
        /// <param name="plcSoftwareService"></param>
        /// <param name="hmiSoftwareService"></param>
        /// <param name="hmiTargetService"></param>
        /// <param name="startdriveService"></param>
        public void Initialize(IOpennessDemoModel opennessDemoModel, ITraceLogService traceLogService,
            ITiaPortalServiceProvider tiaPortalServiceProvider, IProjectServiceProvider projectServiceProvider,
            IMultiuserServiceProvider multiuserServiceProvider,
            IPlcSoftwareService plcSoftwareService, IHmiSoftwareService hmiSoftwareService,
            IHmiTargetService hmiTargetService, IStartdriveService startdriveService)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(LibraryServiceProvider) + " - " + nameof(Initialize) };

            try
            {
                _opennessDemoModel        = opennessDemoModel;
                _traceLogService          = traceLogService;
                _tiaPortalServiceProvider = tiaPortalServiceProvider;

                _projectModel             = _tiaPortalServiceProvider.GetProject() as ProjectModel;
                GlobalLibraryInfos        = new List<LibraryInfo>();

                _plcSoftwareService       = plcSoftwareService;
                _hmiSoftwareService       = hmiSoftwareService;
                _hmiTargetService         = hmiTargetService;

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
        /// Meta information for library state
        /// </summary>
        public IList<LibraryInfo> GlobalLibraryInfos
        {
            get => _globalLibraryInfos;
            set => SetProperty(ref _globalLibraryInfos, value);
        }

        #endregion // properties

        #region methods

        /// <summary>
        /// Open project library
        /// </summary>
        /// <param name="globalLibrary"></param>
        /// <returns></returns>
        public async Task<int> OpenLibraryAsync(bool globalLibrary)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(LibraryServiceProvider) + " - " + nameof(OpenLibraryAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var task = Task.Run(() =>
                {
                    if (globalLibrary)
                    {
                        LoadGlobalLibrary();
                    }
                    else
                    {
                        LoadProjectLibrary();
                    }

                    return 1;
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
        /// Open global library
        /// </summary>
        /// <param name="path"></param>
        /// <param name="userLibrary"></param>
        /// <returns></returns>
        public async Task<bool> OpenGlobalLibraryAsync(FileInfo path, bool userLibrary)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(LibraryServiceProvider) + " - " + nameof(OpenGlobalLibraryAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var task = Task.Run(() =>
                {
                    LoadGlobalLibrary();

                    bool result = false;
                    var fileInfo = (from x in _availableLibraryInfos
                                    where x.Path.FullName == path.FullName
                                    select x).FirstOrDefault();

                    if (fileInfo != null)
                    {
                        var tiaPortal = _tiaPortalServiceProvider.GetTiaPortal() as TiaPortal;
                        if (tiaPortal != null)
                        {
                            var globalLibrary = tiaPortal.GlobalLibraries.Open(fileInfo);
                            result = globalLibrary != null;
                        }
                    }

                    if (userLibrary)
                    {
                        var tiaPortal = _tiaPortalServiceProvider.GetTiaPortal() as TiaPortal;
                        if (tiaPortal != null)
                        {
                            var library = tiaPortal.GlobalLibraries.Open(path, OpenMode.ReadWrite);
                            result = library != null;
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
        /// Create new global library
        /// </summary>
        /// <param name="targetInfo"></param>
        /// <param name="libraryName"></param>
        /// <returns></returns>
        public async Task<bool> CreateNewGlobalLibraryAsync(DirectoryInfo targetInfo, string libraryName)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(LibraryServiceProvider) + " - " + nameof(CreateNewGlobalLibraryAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var task = Task.Run(() =>
                {
                    var tiaPortal = _tiaPortalServiceProvider.GetTiaPortal() as TiaPortal;
                    if (tiaPortal != null)
                    {
                        var library = tiaPortal.GlobalLibraries.Create<UserGlobalLibrary>(targetInfo, libraryName);
                        WriteTraceLogProxy(processInfo.ProcessMessage + " - path: " + targetInfo.FullName + " - library: " + libraryName);
                        return library != null;
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
        /// Save global library
        /// </summary>
        /// <param name="header"></param>
        /// <param name="tag"></param>
        /// <param name="global"></param>
        /// <returns></returns>
        public async Task<bool> SaveGlobalLibraryAsync(string header, Guid tag, bool global)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(LibraryServiceProvider) + " - " + nameof(SaveGlobalLibraryAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var task = Task.Run(() =>
                {
                    var library = GetLibrary(header, tag, global);

                    if (library != null && library is UserGlobalLibrary userGlobalLibrary)
                    {
                        userGlobalLibrary.Save();
                    }

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
        /// Update project library from global library
        /// </summary>
        /// <param name="header">global library name</param>
        /// <param name="tag">global library identifier</param>
        /// <returns></returns>
       public async Task<bool> UpdateProjectLibraryAsync(string header, Guid tag)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(LibraryServiceProvider) + " - " + nameof(UpdateProjectLibraryAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var task = Task.Run(() =>
                {
                    var globalLibrary = GetLibrary(header, tag, true);

                    if (globalLibrary != null && _projectLibrary != null && globalLibrary.TypeFolder != null)
                    {
                        globalLibrary.UpdateLibrary(new[] { globalLibrary.TypeFolder }, _projectLibrary);
                    }

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
        /// Close global library
        /// </summary>
        /// <param name="header"></param>
        /// <param name="tag"></param>
        /// <param name="global"></param>
        /// <returns></returns>
        public async Task<bool> CloseGlobalLibraryAsync(string header, Guid tag, bool global)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(LibraryServiceProvider) + " - " + nameof(CloseGlobalLibraryAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var task = Task.Run(() =>
                {
                    var library = GetLibrary(header, tag, global);

                    if (library != null && library is UserGlobalLibrary userGlobalLibrary)
                    {
                        userGlobalLibrary.Close();
                    }

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
        /// Retrieve project library tree
        /// </summary>
        /// <returns></returns>
        public Tree GetProjectLibraryTree()
        {
            try
            {
                return _projectModel.ProjectLibraryTree;
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
        /// Retrieve global library tree
        /// </summary>
        /// <returns></returns>
        public Tree GetGlobalLibraryTree()
        {
            try
            {
                return _projectModel.GlobalLibraryTree;
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
        /// Retrieve global library info
        /// </summary>
        /// <returns></returns>
        public IList<LibraryInfo> GetGlobalLibraryInfos()
        {
            try
            {
                LoadGlobalLibrary();

                return GlobalLibraryInfos;
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
        /// Retrieve type information
        /// </summary>
        /// <param name="header">selected item name</param>
        /// <param name="tag">selected item identifier</param>
        /// <param name="global">it is an item from global library?</param>
        /// <returns></returns>
        public TreeTypeInformation GetTypeInformation(string header, Guid tag, bool global)
        {
            try
            {
                if (global)
                {
                    var treeTypeInfo = (from item in _globalLibraryCollection.LibraryItems
                                        where item.Header == header && item.Tag == tag
                                        select item.TypeInfo).FirstOrDefault();
                    return treeTypeInfo;
                }
                else
                {
                    var treeTypeInfo = (from item in _projectLibraryCollection.LibraryItems
                                        where item.Header == header && item.Tag == tag
                                        select item.TypeInfo).FirstOrDefault();
                    return treeTypeInfo;
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
        /// Retrieve library item
        /// </summary>
        /// <param name="header">item name</param>
        /// <param name="tag">item identifier</param>
        /// <param name="global">it is an item from global library?</param>
        /// <returns></returns>
        public LibraryItem GetLibraryItem(string header, Guid tag, bool global)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(LibraryServiceProvider) + " - " + nameof(GetLibraryItem) };

            try
            {
                LibraryItem libraryItem;

                if (global)
                {
                    libraryItem = (from item in _globalLibraryCollection.LibraryItems
                                   where item.Header == header && item.Tag == tag
                                   select item).FirstOrDefault();
                }
                else
                {
                    libraryItem = (from item in _projectLibraryCollection.LibraryItems
                                   where item.Header == header && item.Tag == tag
                                   select item).FirstOrDefault();
                }

                if (libraryItem != null)
                {
                    WriteTraceLogProxy(processInfo.ProcessMessage + " - header: " + libraryItem.Header + ", type info: " + libraryItem.TypeInfo);
                }

                return libraryItem;
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
        /// Edit group name
        /// </summary>
        /// <param name="groupName">group name</param>
        /// <param name="parentGroup">parent group name</param>
        /// <param name="tag">group identifier</param>
        /// <param name="global">edit in global library?</param>
        /// <param name="createNewGroup">true == create a new group, false == edit existing group name</param>
        public void EditGroup(string groupName, string parentGroup, Guid tag, bool global, bool createNewGroup)
        {
            try
            {
                LibraryItem parentItem;

                if (global)
                {
                    parentItem = (from library in _globalLibraryCollection.LibraryItems
                                  where library.Header == parentGroup && library.Tag == tag
                                  select library).FirstOrDefault();
                }
                else
                {
                    parentItem = (from library in _projectLibraryCollection.LibraryItems
                                  where library.Header == parentGroup && library.Tag == tag
                                  select library).FirstOrDefault();
                }

                if (parentItem != null)
                {
                    if (parentItem.TypeInfo == TreeTypeInformation.IsFolderGroup)
                    {
                        EditMasterCopyGroup((MasterCopyFolder)parentItem.Item, groupName, createNewGroup);
                    }

                    if (parentItem.TypeInfo == TreeTypeInformation.IsTypeGroup)
                    {
                        EditTypeGroup((LibraryTypeFolder)parentItem.Item, groupName, createNewGroup);
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

        /// <summary>
        /// Indicates whether the library has been changed
        /// </summary>
        /// <param name="header">item name</param>
        /// <param name="tag">item identifier</param>
        /// <param name="global">true == item is from global library, false == item is from project library</param>
        /// <returns></returns>
        public bool LibraryHasBeenChanged(string header, Guid tag, bool global)
        {
            try
            {
                bool result = false;
                if (global)
                {
                    var libraryItem = (from library in _globalLibraryCollection.LibraryItems
                                       where library.Header == header && library.Tag == tag
                                       select library.Item as GlobalLibrary).FirstOrDefault();

                    result = libraryItem != null && libraryItem.IsModified;
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

        /// <summary>
        /// Export version
        /// </summary>
        /// <param name="header">item name</param>
        /// <param name="tag">item identifier</param>
        /// <param name="global">true == item is from global library, false == item is from project library</param>
        /// <param name="path">export path</param>
        /// <param name="options">export option</param>
        /// <returns></returns>
        public bool ExportVersion(string header, Guid tag, bool global, FileInfo path, int options)
        {
            bool result = false;

            var exportOption = EnumService.GetEnumValue<ExportOptions>("None");
            var exportWithDefaults = EnumService.GetEnumValue<ExportOptions>("WithDefaults");
            var exportReadOnly = EnumService.GetEnumValue<ExportOptions>("WithReadOnly");

            if (options == 1)
            {
                exportOption = exportWithDefaults;
            }
            else if (options == 2)
            {
                exportOption = exportReadOnly;
            }
            else if (options == 3)
            {
                exportOption = exportWithDefaults | exportReadOnly;
            }

            if (global)
            {
                var typeVersion = (from version in _globalLibraryCollection.LibraryItems
                                   where version.Header == header && version.Tag == tag
                                   select version.Item as LibraryTypeVersion).FirstOrDefault();

                if (typeVersion != null)
                {
                    typeVersion.Export(path, exportOption);
                    result = true;
                }
            }
            else
            {
                var typeVersion = (from version in _projectLibraryCollection.LibraryItems
                                   where version.Header == header && version.Tag == tag
                                   select version.Item as LibraryTypeVersion).FirstOrDefault();

                if (typeVersion != null)
                {
                    typeVersion.Export(path, exportOption);
                    result = true;
                }
            }

            return result;
        }

        /// <summary>
        /// Copy library version to project
        /// </summary>
        /// <param name="targetObject"></param>
        /// <param name="header">item name+</param>
        /// <param name="tag">item identifier</param>
        /// <param name="global">true == item is from global library, false == item is from project library</param>
        /// <returns></returns>
        public bool CopyLibraryVersionToProject(object targetObject, string header, Guid tag, bool global)
        {
            try
            {
                bool result = false;

                var libraryTypeVersion = (from version in _projectLibraryCollection.LibraryItems
                                          where version.Header == header && version.Tag == tag
                                          select version.Item as LibraryTypeVersion).FirstOrDefault();

                if (libraryTypeVersion != null)
                {
                    _plcSoftwareService?.CopyLibraryVersionToProject(targetObject, libraryTypeVersion);

                    _hmiTargetService?.CopyLibraryVersionToProject(targetObject, libraryTypeVersion);

                    result = true;
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

        /// <summary>
        /// Create new copy from master copy
        /// </summary>
        /// <param name="targetObject"></param>
        /// <param name="header"></param>
        /// <param name="tag"></param>
        /// <param name="global"></param>
        public void CreateCopyFromMasterCopy(object targetObject, string header, Guid tag, bool global)
        {
            var libraryItem = GetLibraryItem(header, tag, global);
            var contentType = GetTypeOfMasterCopy(libraryItem);

            if (contentType != null)
            {
                if (_plcSoftwareService != null && _plcSoftwareService.IsKnownObject(contentType))
                {
                    _plcSoftwareService.CreateCopyFromMasterCopy(targetObject, libraryItem.Item);
                }

                if (_hmiSoftwareService != null && _hmiSoftwareService.IsKnownObject(contentType))
                {
                    _hmiSoftwareService.CreateCopyFromMasterCopy(targetObject, libraryItem.Item);
                }

                if (_hmiTargetService != null && _hmiTargetService.IsKnownObject(contentType))
                {
                    _hmiTargetService.CreateCopyFromMasterCopy(targetObject, libraryItem.Item);
                }
            }
        }
       
        /// <summary>
        /// Indicates if the source is a known type
        /// </summary>
        /// <param name="header"></param>
        /// <param name="tag"></param>
        /// <param name="global"></param>
        /// <returns></returns>
        public bool CopySourceIsKnownType(string header, Guid tag, bool global)
        {
            var libraryItem = GetLibraryItem(header, tag, global);
            var contentType = GetTypeOfMasterCopy(libraryItem);

            if (contentType != null)
            {
                return _plcSoftwareService != null && _plcSoftwareService.IsKnownObject(contentType) ||
                       _hmiSoftwareService != null && _hmiSoftwareService.IsKnownObject(contentType) ||
                       _hmiTargetService != null && _hmiTargetService.IsKnownObject(contentType);
            }

            return false;
        }

        private Type GetTypeOfMasterCopy(LibraryItem item)
        {
            try
            {
                if (item.Item is MasterCopy masterCopy)
                {
                    if (masterCopy.ContentDescriptions.Count == 1)
                    {
                        return masterCopy.ContentDescriptions.First().ContentType;
                    }

                    throw new InvalidOperationException("This kind of master copy is not supported.");
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

        private void LoadProjectLibrary()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(LibraryServiceProvider) + " - " + nameof(LoadProjectLibrary) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var tiaPortal = _tiaPortalServiceProvider.GetTiaPortal() as TiaPortal;

                if (tiaPortal?.Projects.Count > 0)
                {
                    var project = tiaPortal.Projects.FirstOrDefault();
                    _projectLibrary = project?.ProjectLibrary;
                }

                if (_projectLibrary != null)
                {
                    LoadProjectLibraryTree(_projectLibrary);
                }
                else
                {
                    _opennessDemoModel.ProjectModel.ProjectLibraryTree = null;
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

        private void LoadGlobalLibrary()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(LibraryServiceProvider) + " - " + nameof(LoadGlobalLibrary) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var tiaPortal = _tiaPortalServiceProvider.GetTiaPortal() as TiaPortal;
                if (tiaPortal != null)
                {
                    if (tiaPortal.GlobalLibraries != null)
                    {
                        _globalLibraries = tiaPortal.GlobalLibraries;
                        LoadGlobalLibraryTree(_globalLibraries);

                        _availableLibraryInfos = tiaPortal.GlobalLibraries.GetGlobalLibraryInfos();

                        if (_availableLibraryInfos != null && _availableLibraryInfos.Count > 0)
                        {
                            GlobalLibraryInfos.Clear();
                            foreach (var availableLibraryInfo in _availableLibraryInfos)
                            {
                                if (availableLibraryInfo.Path.Extension.Contains("as"))
                                {
                                    GlobalLibraryInfos.Add(new LibraryInfo() { LibraryName = availableLibraryInfo.Name, FileInfo = availableLibraryInfo.Path, IsOpen = availableLibraryInfo.IsOpen });
                                }
                            }
                        }
                    }
                    else
                    {
                        _opennessDemoModel.ProjectModel.GlobalLibraryTree = null;
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

        private void LoadProjectLibraryTree(ProjectLibrary library)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(LibraryServiceProvider) + " - " + nameof(LoadProjectLibraryTree) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var projectLibraryItem = new LibraryItem();

                var projectLibraryTree = new Tree();
                projectLibraryTree.ExpandSubTree = false;

                var projectLibraryTreeItem = new TreeItem();
                projectLibraryTreeItem.Header = "Project library";
                projectLibraryTreeItem.Tag = Guid.NewGuid();

                var guid = Guid.NewGuid();
                var libraryTypeSystemItem = new TreeItem();
                libraryTypeSystemItem.Header = library.TypeFolder.Name;
                libraryTypeSystemItem.Tag = guid;
                libraryTypeSystemItem.Status = "";
                projectLibraryItem.LibraryItems.Add(new LibraryItem() { Header = library.TypeFolder.Name, Tag = guid, Item = library.TypeFolder, TypeInfo = TreeTypeInformation.IsTypeGroup });
                projectLibraryTreeItem.Items.Add(libraryTypeSystemItem);

                GetLibraryTypes(library.TypeFolder, libraryTypeSystemItem, projectLibraryItem);

                // type sub tree
                foreach (var folder in library.TypeFolder.Folders)
                {
                    LoadLibraryTypeFolderTree(folder, libraryTypeSystemItem, projectLibraryItem);
                }

                guid = Guid.NewGuid();
                var masterCopySystemItem = new TreeItem();
                masterCopySystemItem.Header = library.MasterCopyFolder.Name;
                masterCopySystemItem.Tag = guid;
                projectLibraryItem.LibraryItems.Add(new LibraryItem() { Header = library.MasterCopyFolder.Name, Tag = guid, Item = library.MasterCopyFolder, TypeInfo = TreeTypeInformation.IsFolderGroup });
                projectLibraryTreeItem.Items.Add(masterCopySystemItem);

                GetMasterCopies(library.MasterCopyFolder, masterCopySystemItem, projectLibraryItem);

                // master copy sub tree
                foreach (var folder in library.MasterCopyFolder.Folders)
                {
                    LoadMasterCopyTree(folder, masterCopySystemItem, projectLibraryItem);
                }

                projectLibraryTree.Items.Add(projectLibraryTreeItem);
                _projectModel.ProjectLibraryTree = projectLibraryTree;

                _projectLibraryCollection = new LibraryContent();
                _projectLibraryCollection.LibraryItems = projectLibraryItem.LibraryItems;
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

        private void LoadGlobalLibraryTree(GlobalLibraryComposition libraryComposition)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(LibraryServiceProvider) + " - " + nameof(LoadGlobalLibraryTree) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var globalLibraryItem = new LibraryItem();

                var globalLibraryTree = new Tree();
                globalLibraryTree.ExpandSubTree = false;

                foreach (var library in libraryComposition)
                {
                    var globalLibraryTreeItem = new TreeItem();
                    globalLibraryTreeItem.Header = library.Name;
                    globalLibraryTreeItem.Path = library.Path;
                    globalLibraryTreeItem.Tag = Guid.NewGuid();
                    globalLibraryTreeItem.TypeInfo = library.Path.Extension.Contains("al")
                        ? TreeTypeInformation.IsUserLib
                        : TreeTypeInformation.IsSysLib;
                    globalLibraryItem.LibraryItems.Add(new LibraryItem() { Header = globalLibraryTreeItem.Header, Tag = globalLibraryTreeItem.Tag, Item = library, TypeInfo = globalLibraryTreeItem.TypeInfo });

                    //if (library.TypeFolder != null)
                    //{
                    //    guid = Guid.NewGuid();
                    //    var libraryTypeSystemItem = new TreeItem();
                    //    libraryTypeSystemItem.Header = library.TypeFolder.Name;
                    //    libraryTypeSystemItem.Tag = guid;
                    //    libraryTypeSystemItem.Status = ((LibraryTypeFolder)library.TypeFolder).Status.ToString();
                    //    globalLibraryItem.LibraryItems.Add(new LibraryItem() { Header = library.TypeFolder.Name, Tag = guid, Item = library.TypeFolder, TypeInfo = TreeTypeInformation.IsTypeGroup });
                    //    globalLibraryTreeItem.Items.Add(libraryTypeSystemItem);

                    //    GetLibraryTypes(library.TypeFolder, libraryTypeSystemItem, globalLibraryItem);

                    //    // type sub tree
                    //    foreach (var folder in library.TypeFolder.Folders)
                    //    {
                    //        LoadLibraryTypeFolderTree(folder, libraryTypeSystemItem, globalLibraryItem);
                    //    }
                    //}

                    Guid guid;
                    if (library.MasterCopyFolder != null)
                    {
                        guid = Guid.NewGuid();
                        var masterCopySystemItem = new TreeItem();
                        masterCopySystemItem.Header = library.MasterCopyFolder.Name;
                        masterCopySystemItem.Tag = guid;
                        globalLibraryItem.LibraryItems.Add(new LibraryItem() { Header = library.MasterCopyFolder.Name, Tag = guid, Item = library.MasterCopyFolder, TypeInfo = TreeTypeInformation.IsFolderGroup });
                        globalLibraryTreeItem.Items.Add(masterCopySystemItem);

                        GetMasterCopies(library.MasterCopyFolder, masterCopySystemItem, globalLibraryItem);

                        // master copy sub tree
                        foreach (var folder in library.MasterCopyFolder.Folders)
                        {
                            LoadMasterCopyTree(folder, masterCopySystemItem, globalLibraryItem);
                        }
                    }

                    if (library.Comment != null)
                    {
                        guid = Guid.NewGuid();
                        var libraryTypeSystemItem = new TreeItem();
                        libraryTypeSystemItem.Header = "Common data";
                        libraryTypeSystemItem.Tag = guid;
                        libraryTypeSystemItem.Status = null;
                        globalLibraryItem.LibraryItems.Add(new LibraryItem() { Header = libraryTypeSystemItem.Header, Tag = guid, Item = library.TypeFolder, TypeInfo = TreeTypeInformation.IsOther });
                        globalLibraryTreeItem.Items.Add(libraryTypeSystemItem);

                        foreach (var item in library.Comment.Items)
                        {
                            LoadCommonData(item, libraryTypeSystemItem, globalLibraryItem);
                        }
                    }

                    globalLibraryTree.Items.Add(globalLibraryTreeItem);

                }

                _projectModel.GlobalLibraryTree = globalLibraryTree;

                _globalLibraryCollection = new LibraryContent();
                _globalLibraryCollection.LibraryItems = globalLibraryItem.LibraryItems;
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

        private void LoadMasterCopyTree(MasterCopyFolder masterCopyFolder, TreeItem masterCopytreeItem, LibraryItem libraryItem)
        {
            try
            {
                var guid = Guid.NewGuid();
                var masterCopyItem = new TreeItem() { Header = masterCopyFolder.Name, Tag = guid };
                libraryItem.LibraryItems.Add(new LibraryItem() { Header = masterCopyFolder.Name, Tag = guid, Item = masterCopyFolder, TypeInfo = TreeTypeInformation.IsFolderGroup });
                masterCopytreeItem.Items.Add(masterCopyItem);

                GetMasterCopies(masterCopyFolder, masterCopyItem, libraryItem);

                foreach (var folder in masterCopyFolder.Folders)
                {
                    LoadMasterCopyTree(folder, masterCopyItem, libraryItem);
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

        private void GetMasterCopies(MasterCopyFolder masterCopyFolder, TreeItem treeItem, LibraryItem libraryItem)
        {
            try
            {
                var orderedTypeFolderList = masterCopyFolder.MasterCopies.OrderBy(f => f.Name);
                foreach (var masterCopy in orderedTypeFolderList)
                {
                    var guid = Guid.NewGuid();
                    var masterCopyItem = new TreeItem() { Header = masterCopy.Name, Tag = guid };
                    libraryItem.LibraryItems.Add(new LibraryItem() { Header = masterCopy.Name, Tag = guid, Item = masterCopy, TypeInfo = TreeTypeInformation.IsMasterCopy });

                    treeItem.Items.Add(masterCopyItem);

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

        private void LoadLibraryTypeFolderTree(LibraryTypeFolder libraryTypeFolder, TreeItem libraryTypeTreeItem, LibraryItem libraryItem)
        {
            try
            {
                var guid = Guid.NewGuid();
                var libraryTypeItem = new TreeItem() { Header = libraryTypeFolder.Name, Tag = guid };
                libraryItem.LibraryItems.Add(new LibraryItem() { Header = libraryTypeFolder.Name, Tag = guid, Item = libraryTypeFolder, TypeInfo = TreeTypeInformation.IsTypeGroup });
                libraryTypeTreeItem.Items.Add(libraryTypeItem);

                GetLibraryTypes(libraryTypeFolder, libraryTypeItem, libraryItem);

                foreach (var folder in libraryTypeFolder.Folders)
                {
                    LoadLibraryTypeFolderTree(folder, libraryTypeItem, libraryItem);
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

        private void GetLibraryTypes(LibraryTypeFolder libraryTypeFolder, TreeItem treeItem, LibraryItem libraryItem)
        {
            try
            {
                var orderedTypeFolderList = libraryTypeFolder.Types.OrderBy(f => f.Name);
                foreach (var libraryType in orderedTypeFolderList)
                {
                    try
                    {
                        var guid = Guid.NewGuid();
                        var libraryTypeItem = new TreeItem() { Header = libraryType.Name, Tag = guid };
                        libraryItem.LibraryItems.Add(new LibraryItem() { Header = libraryType.Name, Tag = guid, Item = libraryType, TypeInfo = TreeTypeInformation.IsType });

                        var orderedVersions = libraryType.Versions.OrderByDescending(f => f.VersionNumber);
                        foreach (var version in orderedVersions)
                        {
                            var inWork = (from x in libraryType.Versions
                                          where x.State != LibraryTypeVersionState.Committed && x.VersionNumber == version.VersionNumber
                                          select x).FirstOrDefault();

                            string state;
                                
                            state = inWork != null ? " [in work]" : string.Empty;

                            string versionInfo = "V " + version.VersionNumber + state;
                            guid = Guid.NewGuid();
                            var libraryTypeVersionItem = new TreeItem() { Header = versionInfo, Tag = guid };
                            libraryItem.LibraryItems.Add(new LibraryItem() { Header = versionInfo, Tag = guid, Item = version, TypeInfo = TreeTypeInformation.IsTypeVersion });
                            libraryTypeItem.Items.Add(libraryTypeVersionItem);
                        }

                        treeItem.Items.Add(libraryTypeItem);
                    }
                    catch (EngineeringNotSupportedException e)
                    {
                        Console.WriteLine(e);
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

        private void LoadCommonData(MultilingualTextItem commonDataItem, TreeItem libraryLanguageSettingsItem, LibraryItem globalLibraryItem)
        {
            try
            {
                var guid = Guid.NewGuid();
                var libraryCommonDataItem = new TreeItem() { Header = "Logs", Tag = guid };
                globalLibraryItem.LibraryItems.Add(new LibraryItem() { Header = libraryCommonDataItem.Header, Tag = guid, Item = commonDataItem, TypeInfo = TreeTypeInformation.IsOther });

                foreach (var text in commonDataItem.Text)
                {
                    guid = Guid.NewGuid();
                    var commonLogItem = new TreeItem() { Header = text.ToString(), Tag = guid };
                    globalLibraryItem.LibraryItems.Add(new LibraryItem() { Header = text.ToString(), Tag = guid, Item = text, TypeInfo = TreeTypeInformation.IsOther });
                    libraryCommonDataItem.Items.Add(commonLogItem);
                }

                libraryLanguageSettingsItem.Items.Add(libraryCommonDataItem);
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

        private ILibrary GetLibrary(string header, Guid tag, bool global)
        {
            try
            {
                if (global)
                {
                    var libraryItem = (from library in _globalLibraryCollection.LibraryItems
                                       where library.Header == header && library.Tag == tag
                                       select library.Item as ILibrary).FirstOrDefault();

                    return libraryItem;
                }
                else
                {
                    var libraryItem = (from library in _projectLibraryCollection.LibraryItems
                                       where library.Header == header && library.Tag == tag
                                       select library.Item as ILibrary).FirstOrDefault();

                    return libraryItem;
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

        private void EditTypeGroup(LibraryTypeFolder parent, string groupNameCommit, bool createNewGroup)
        {
            try
            {
                if (createNewGroup)
                {
                    parent.Folders.Create(groupNameCommit);
                }
                else
                {
                    if (parent != null)
                    {
                        ((LibraryTypeUserFolder)parent).Name = groupNameCommit;
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

        private void EditMasterCopyGroup(MasterCopyFolder parent, string groupNameCommit, bool createNewGroup)
        {
            if (createNewGroup)
            {
                parent.Folders.Create(groupNameCommit);
            }
            else
            {
                if (parent != null)
                {
                    ((MasterCopyUserFolder)parent).Name = groupNameCommit;

                }
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
