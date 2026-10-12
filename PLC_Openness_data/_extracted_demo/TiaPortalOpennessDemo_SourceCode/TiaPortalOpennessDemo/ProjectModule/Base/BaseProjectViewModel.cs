using LibraryModule.ViewModels;
using LibraryModule.Views;
using Prism.Events;
using Prism.Ioc;
using Prism.Mvvm;
using Prism.Regions;
using ProjectModule.ViewModels;
using ProjectModule.Views;
using System;
using System.Collections.Generic;
using System.IO;
using System.Windows.Controls;
using System.Windows.Forms;
using System.Windows.Media;
using SharedResourceDictionary.Properties;
using TiaPortalOpennessAdapter.Contracts;
using TiaPortalOpennessAdapterBase.Base;
using TiaPortalOpennessAdapterBase.Enums;
using TiaPortalOpennessAdapterContracts;
using TiaPortalOpennessCore.Events.Content;
using TiaPortalOpennessCore.Events.Global;
using TiaPortalOpennessCore.Events.Project;
using TiaPortalOpennessCore.Events.Shell;
using TiaPortalOpennessCore.Events.TiaPortal;
using TiaPortalOpennessCore.Utils;
using TiaPortalOpennessInfrastructure.Constants;
using TiaPortalOpennessInfrastructure.Contracts;
using TiaPortalOpennessInfrastructure.Utils;
using Application = System.Windows.Application;
using MessageBox = System.Windows.Forms.MessageBox;
using TreeView = System.Windows.Controls.TreeView;

namespace ProjectModule.Base
{
    /// <summary>
    /// Base implementation for logical und physical project tree view
    /// </summary>
    public class BaseProjectViewModel : BindableBase, INavigationAware
    {
        #region fields

        private readonly IEventAggregator _eventAggregator;
        private readonly ITraceLogService _traceLogService;
        internal readonly ISettingsService SettingsService;
        private readonly IModuleProvider _moduleProvider;
        private readonly IContainerProvider _containerProvider;

        private readonly IOpennessDemoModel _opennessDemoModel;
        private TreeView _treeView;
        private TreeViewHandler _projectTreeHandler;
        private TreeViewItem _selectedItem;

        internal ITiaPortalServiceProvider TiaPortalServiceProvider;
        internal IProjectServiceProvider ProjectServiceProvider;
        internal IMultiuserServiceProvider MultiuserServiceProvider;
        internal ILibraryServiceProvider LibraryServiceProvider;
        internal IPlcSoftwareService PlcSoftwareService;
        internal IHmiSoftwareService HmiSoftwareService;
        internal IHmiTargetService HmiTargetService;
        internal IStartdriveService SinamicsService;

        internal string ProcessId;
        internal string TreeTypeName;


        protected bool LogicalTreeView = false;
        public string TreeTypeInfo = string.Empty;

        #endregion // fields

        #region ctor

        /// <summary>
        /// default constructor
        /// </summary>
        /// <param name="eventAggregator"></param>
        /// <param name="traceLogService"></param>
        /// <param name="settingsService"></param>
        /// <param name="moduleProvider"></param>
        /// <param name="containerProvider"></param>
        /// <param name="opennessDemoModel"></param>
        public BaseProjectViewModel(IEventAggregator eventAggregator, ITraceLogService traceLogService, ISettingsService settingsService, IModuleProvider moduleProvider, IContainerProvider containerProvider, IOpennessDemoModel opennessDemoModel)
        {
            _eventAggregator = eventAggregator;
            _traceLogService = traceLogService;
            SettingsService = settingsService;
            _moduleProvider = moduleProvider;

            _containerProvider = containerProvider;
            _opennessDemoModel = opennessDemoModel;

            _eventAggregator.GetEvent<ServiceProviderInitializeEvent>().Subscribe(InitServiceProvider);

            _eventAggregator.GetEvent<OpenTopologyEditorEvent>().Subscribe(OpenTopologyEditor, ThreadOption.UIThread, false, i => i.NavigationTarget == NavigationNames.LogicalProjectView || i.NavigationTarget == NavigationNames.PhysicalProjectView);
            _eventAggregator.GetEvent<OpenNetworkEditorEvent>().Subscribe(OpenNetworkEditor, ThreadOption.UIThread, false, i => i.NavigationTarget == NavigationNames.LogicalProjectView || i.NavigationTarget == NavigationNames.PhysicalProjectView);

            _eventAggregator.GetEvent<DisconnectTiaPortalEvent>().Subscribe(DisconnectTiaPortal);
        }

        /// <summary>
        /// Initialize all service provider
        /// </summary>
        protected virtual void InitServiceProvider()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseProjectViewModel) + " - " + nameof(InitServiceProvider) };
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

            InitPortalServiceProvider();

            InitProjectServiceProvider();

            InitMultiUserServiceProvider();

            InitLibraryServiceProvider();
        }

        private void InitPortalServiceProvider()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseProjectViewModel) + " - " + nameof(InitPortalServiceProvider) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                TiaPortalServiceProvider = _moduleProvider.GetService(typeof(ITiaPortalServiceProvider)) as ITiaPortalServiceProvider;
                if (TiaPortalServiceProvider != null)
                {
                    TiaPortalServiceProvider.Initialize(_opennessDemoModel, _traceLogService);
                }
                else
                {
                    var version = SettingsService.GetSelectedOpennessApiVersion();
                    WriteTraceLogProxy(processInfo.ProcessMessage + " -> portal service provider for version - " + version + " not found!");
                }
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, Resources.Openness_api_exception_occurred, MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        private void InitProjectServiceProvider()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseProjectViewModel) + " - " + nameof(InitProjectServiceProvider) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                ProjectServiceProvider = _moduleProvider.GetService(typeof(IProjectServiceProvider)) as IProjectServiceProvider;
                if (ProjectServiceProvider != null)
                {
                    ProjectServiceProvider.Initialize(_opennessDemoModel, _traceLogService, SettingsService, TiaPortalServiceProvider, PlcSoftwareService, HmiSoftwareService, HmiTargetService, SinamicsService);
                }
                else
                {
                    var version = SettingsService.GetSelectedOpennessApiVersion();
                    WriteTraceLogProxy(processInfo.ProcessMessage + " -> project service provider for version - " + version + " not found!");
                }
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, Resources.Openness_api_exception_occurred, MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        private void InitMultiUserServiceProvider()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseProjectViewModel) + " - " + nameof(InitMultiUserServiceProvider) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                MultiuserServiceProvider = _moduleProvider.GetService(typeof(IMultiuserServiceProvider)) as IMultiuserServiceProvider;
                if (MultiuserServiceProvider != null)
                {
                    MultiuserServiceProvider.Initialize(_opennessDemoModel, _traceLogService, TiaPortalServiceProvider, ProjectServiceProvider);
                }
                else
                {
                    var version = SettingsService.GetSelectedOpennessApiVersion();
                    WriteTraceLogProxy(processInfo.ProcessMessage + " -> multi user service provider for version - " + version + " not found!");
                }
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, Resources.Openness_api_exception_occurred, MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        private void InitLibraryServiceProvider()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseProjectViewModel) + " - " + nameof(InitLibraryServiceProvider) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                LibraryServiceProvider = _moduleProvider.GetService(typeof(ILibraryServiceProvider)) as ILibraryServiceProvider;
                if (LibraryServiceProvider != null)
                {
                    LibraryServiceProvider.Initialize(_opennessDemoModel, _traceLogService, TiaPortalServiceProvider, ProjectServiceProvider, MultiuserServiceProvider, PlcSoftwareService, HmiSoftwareService, HmiTargetService, SinamicsService);
                }
                else
                {
                    var version = SettingsService.GetSelectedOpennessApiVersion();
                    WriteTraceLogProxy(processInfo.ProcessMessage + " -> library service provider for version - " + version + " not found!");
                }
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, Resources.Openness_api_exception_occurred, MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        #endregion // ctor

        #region properties

        /// <summary>
        /// Selected tree item
        /// </summary>
        public TreeViewItem SelectedItem
        {
            get => _selectedItem;
            set
            {
                SetProperty(ref _selectedItem, value);
                RaisePropertyChanged();
            }
        }

        /// <summary>
        /// The tree view
        /// </summary>
        public TreeView TreeView
        {
            get => _treeView;
            set => SetProperty(ref _treeView, value);
        }

        /// <summary>
        /// Tree view handler
        /// </summary>
        public TreeViewHandler ProjectTreeViewHandler
        {
            get => _projectTreeHandler;
            set
            {
                SetProperty(ref _projectTreeHandler, value);
                RaisePropertyChanged();
            }
        }

        #endregion // properties

        #region methods
        private void DisconnectTiaPortal(IOpennessDemoNavigationContext obj)
        {
            ProcessId = string.Empty;
            TreeTypeName = string.Empty;
        }

        #region project

        protected virtual async void CreateNewProjectAsync(IOpennessDemoNavigationContext navigationContext)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseProjectViewModel) + " - " + nameof(CreateNewProjectAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var createNewProjectView = _containerProvider.Resolve<CreateNewTiaPortalProjectView>();
                createNewProjectView.ShowDialog();
                var dialogResult = createNewProjectView.DialogResult;

                if (dialogResult != null && (bool)dialogResult)
                {
                    _opennessDemoModel.ProjectModel.ProjectName = createNewProjectView.ProjectName.Text;
                    _opennessDemoModel.ProjectModel.TargetDirectory = new DirectoryInfo(createNewProjectView.Path.Text);

                    if (ProjectServiceProvider != null)
                    {
                        IamBusy(processInfo);

                        var innerTask = ProjectServiceProvider.CreateNewProjectAsync(_opennessDemoModel);
                        await innerTask;

                        WriteTraceLogProxy(processInfo.ProcessMessage + "->" + nameof(TiaPortalStateEvent));
                        _eventAggregator.GetEvent<TiaPortalStateEvent>().Publish();
                        WriteTraceLogProxy(processInfo.ProcessMessage + "->" + nameof(ProjectOpenedEvent));
                        _eventAggregator.GetEvent<ProjectOpenedEvent>().Publish();
                        WriteTraceLogProxy(processInfo.ProcessMessage + "->" + nameof(NavigationRequestEvent));
                        _eventAggregator.GetEvent<NavigationRequestEvent>().Publish(navigationContext.NavigationTarget);

                        IamDone(processInfo);
                    }
                }
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, Resources.Openness_api_exception_occurred, MessageBoxButtons.OK, MessageBoxIcon.Error);
                IamDone(processInfo);
            }
        }

        protected virtual void OpenProject(IOpennessDemoNavigationContext navigationContext)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseProjectViewModel) + " - " + nameof(OpenProject) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                OpenFileDialog fileSearch = new OpenFileDialog();

                fileSearch.InitialDirectory = SettingsService.GetProjectPath();
                fileSearch.Filter = @"Siemens TIA Portal project|*.ap*";
                fileSearch.FilterIndex = 2;
                fileSearch.RestoreDirectory = true;
                var result = fileSearch.ShowDialog();

                if (DialogResult.OK != result)
                {
                    WriteTraceLogProxy(processInfo.ProcessMessage + " -> open project canceled!");
                    return;
                }

                string selectedProject = fileSearch.FileName;
                OpenProjectAsync(navigationContext, selectedProject);
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, Resources.Openness_api_exception_occurred, MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        protected virtual async void OpenProjectAsync(IOpennessDemoNavigationContext navigationContext, string projectPath)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseProjectViewModel) + " - " + nameof(OpenProjectAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                if (ProjectServiceProvider != null)
                {
                    IamBusy(processInfo);

                    var result = ProjectServiceProvider.OpenProjectAsync(projectPath);
                    await result;

                    _opennessDemoModel.ProjectModel.ProjectName = ProjectServiceProvider.GetCurrentProjectName();
                    _opennessDemoModel.ProjectModel.TargetDirectory = ProjectServiceProvider.GetCurrentProjectPath();
                    _opennessDemoModel.ProjectModel.ProjectOpened = true;

                    WriteTraceLogProxy(processInfo.ProcessMessage + "->" + nameof(TiaPortalStateEvent));
                    _eventAggregator.GetEvent<TiaPortalStateEvent>().Publish();
                    WriteTraceLogProxy(processInfo.ProcessMessage + "->" + nameof(ProjectOpenedEvent));
                    _eventAggregator.GetEvent<ProjectOpenedEvent>().Publish();

                    LoadTreeDataAsync(navigationContext.ShowLogicalTree);

                    _eventAggregator.GetEvent<NavigationRequestEvent>().Publish(navigationContext.NavigationTarget);

                    IamDone(processInfo);
                }
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, Resources.Openness_api_exception_occurred, MessageBoxButtons.OK, MessageBoxIcon.Error);
                IamDone(processInfo);
            }
        }

        protected virtual async void LoadProjectAsync(bool loadLogicalTree)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseProjectViewModel) + " - " + nameof(LoadProjectAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                IamBusy(processInfo);

                var result = ProjectServiceProvider.LoadProjectAsync();
                await result;

                LoadTreeDataAsync(loadLogicalTree);

                WriteTraceLogProxy(processInfo.ProcessMessage + "->" + nameof(ProjectOpenedEvent));
                _eventAggregator.GetEvent<ProjectOpenedEvent>().Publish();

                IamDone(processInfo);
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, Resources.Openness_api_exception_occurred, MessageBoxButtons.OK, MessageBoxIcon.Error);
                IamDone(processInfo);
            }
        }

        protected virtual async void SaveProjectAsync(IOpennessDemoNavigationContext navigationContext)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseProjectViewModel) + " - " + nameof(SaveProjectAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                IamBusy(processInfo);

                var result = ProjectServiceProvider.SaveProjectAsync();
                await result;

                if (!result.Result)
                {
                    WriteTraceLogProxy(processInfo.ProcessMessage + " -> current project could be saved!");
                }

                LoadProjectAsync(navigationContext.ShowLogicalTree);

                IamDone(processInfo);
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, Resources.Openness_api_exception_occurred, MessageBoxButtons.OK, MessageBoxIcon.Error);
                IamDone(processInfo);
            }

        }

        protected virtual async void CloseProjectAsync(IOpennessDemoNavigationContext navigationContext)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseProjectViewModel) + " - " + nameof(CloseProjectAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                IamBusy(processInfo);
                var result = ProjectServiceProvider.CloseProjectAsync();
                await result;
                IamDone(processInfo);

                _opennessDemoModel.ProjectModel.ProjectName = string.Empty;
                _opennessDemoModel.ProjectModel.TargetDirectory = null;
                _opennessDemoModel.ProjectModel.ProjectOpened = false;

                WriteTraceLogProxy(processInfo.ProcessMessage + " -> " + nameof(ProjectClosedEvent));
                _eventAggregator.GetEvent<ProjectClosedEvent>().Publish();
                WriteTraceLogProxy(processInfo.ProcessMessage + " -> " + nameof(ResetContentEvent));
                _eventAggregator.GetEvent<ResetContentEvent>().Publish();
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, Resources.Openness_api_exception_occurred, MessageBoxButtons.OK, MessageBoxIcon.Error);
                IamDone(processInfo);
            }
        }

        #endregion // project

        #region tree structure

        protected virtual async void LoadTreeDataAsync(bool loadLogicalTree)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseProjectViewModel) + " - " + nameof(LoadTreeDataAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                _eventAggregator.GetEvent<ResetContentEvent>().Publish();

                IamBusy(processInfo);

                var tree = ProjectServiceProvider.LoadTreeStructureAsync(loadLogicalTree);
                await tree;

                CreateTreeView(loadLogicalTree);

                IamDone(processInfo);
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, Resources.Openness_api_exception_occurred, MessageBoxButtons.OK, MessageBoxIcon.Error);
                IamDone(processInfo);
            }
        }

        protected virtual void CreateTreeView(bool loadLogicalTree)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseProjectViewModel) + " - " + nameof(CreateTreeView) };
            WriteTraceLogProxy(processInfo.ProcessMessage);
        }

        protected virtual void TraverseTree(int expandLevel, TreeItem treeItem, TreeViewItem subTreeView, int itemLevel)
        {
            int level = itemLevel + 1;

            foreach (var item in treeItem.Items)
            {
                item.Level = level;
                var subsubTreeView = new TreeViewItem() { Header = item.Header, Tag = item.Tag };
                if (item.Level <= expandLevel)
                {
                    subsubTreeView.IsExpanded = true;
                }
                else
                {
                    subsubTreeView.IsExpanded = false;
                }

                TraverseTree(expandLevel, item, subsubTreeView, item.Level);

                subTreeView.Items.Add(subsubTreeView);
            }
            try
            {
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, Resources.Openness_api_exception_occurred, MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        protected virtual void TreeViewItemSelectedChangedCallback(DependencyPropertyEventArgs obj)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseProjectViewModel) + " - " + nameof(TreeViewItemSelectedChangedCallback) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                ProjectTreeViewHandler.SelectedItem = obj.DependencyPropertyChangedEventArgs.NewValue as TreeViewItem;

                SelectedItem = ProjectTreeViewHandler.SelectedItem;

                if (SelectedItem != null && SelectedItem.Header != null && SelectedItem.Tag != null)
                {
                    WriteTraceLogProxy(processInfo.ProcessMessage + " -> selected tree item - " + (string)SelectedItem.Header);

                    LoadContent(SelectedItem);

                    _opennessDemoModel.SelectedTreeType = ProjectServiceProvider.GetTypeInformation((string)SelectedItem.Header, (Guid)SelectedItem.Tag, LogicalTreeView);

                    _opennessDemoModel.IsCompilable = ProjectServiceProvider.CheckIfCompilable((string)SelectedItem.Header, (Guid)SelectedItem.Tag, LogicalTreeView);
                    _opennessDemoModel.CanExportExecute = ProjectServiceProvider.CheckIfCanExportExecute((string)SelectedItem.Header, (Guid)SelectedItem.Tag, LogicalTreeView);
                    _opennessDemoModel.CanImportElement = ProjectServiceProvider.CheckIfCanImportElement((string)SelectedItem.Header, (Guid)SelectedItem.Tag, LogicalTreeView);
                    _opennessDemoModel.CanImportStructure = ProjectServiceProvider.CheckIfCanImportStructure((string)SelectedItem.Header, (Guid)SelectedItem.Tag, LogicalTreeView);

                    _opennessDemoModel.CanAddExternalSource = ProjectServiceProvider.CheckIfCanAddExternalSource((string)SelectedItem.Header, (Guid)SelectedItem.Tag, LogicalTreeView);
                    _opennessDemoModel.CanGenerateBlockFromSource = ProjectServiceProvider.CheckIfCanGenerateBlockFromSource((string)SelectedItem.Header, (Guid)SelectedItem.Tag, LogicalTreeView);
                    _opennessDemoModel.CanGenerateSourceFromBlock = ProjectServiceProvider.CheckIfCanGenerateSourceFromBlock((string)SelectedItem.Header, (Guid)SelectedItem.Tag, LogicalTreeView);

                    //WriteTraceLogProxy(processInfo.ProcessMessage + " -> selected tree item - selected tree type = :" + _opennessDemoModel.SelectTreeType);
                    //WriteTraceLogProxy(processInfo.ProcessMessage + " -> selected tree item - is compilable = :" + _opennessDemoModel.IsCompilable);
                    //WriteTraceLogProxy(processInfo.ProcessMessage + " -> selected tree item - can export execute = :" + _opennessDemoModel.CanExportExecute);
                    //WriteTraceLogProxy(processInfo.ProcessMessage + " -> selected tree item - can import element = :" + _opennessDemoModel.CanImportElement);
                    //WriteTraceLogProxy(processInfo.ProcessMessage + " -> selected tree item - can add external source = :" + _opennessDemoModel.CanAddExternalSource);
                    //WriteTraceLogProxy(processInfo.ProcessMessage + " -> selected tree item - can generate block from source = :" + _opennessDemoModel.CanGenerateBlockFromSource);
                    //WriteTraceLogProxy(processInfo.ProcessMessage + " -> selected tree item - can generate source from block = :" + _opennessDemoModel.CanGenerateSourceFromBlock);

                    //var deviceItem = ProjectServiceProvider.GetTreeItemObject((string)SelectedItem.Header, (Guid)SelectedItem.Tag, LogicalTreeView);
                    //if (deviceItem != null)
                    //{
                    //    WriteTraceLogProxy(processInfo.ProcessMessage + deviceItem.GetType().FullName);
                    //}
                }
                WriteTraceLogProxy(processInfo.ProcessMessage + " -> " + nameof(SelectedProjectItemChangedEvent));
                _eventAggregator.GetEvent<SelectedProjectItemChangedEvent>().Publish(SelectedItem);
                WriteTraceLogProxy(processInfo.ProcessMessage + " -> " + nameof(TiaPortalStateEvent));
                _eventAggregator.GetEvent<TiaPortalStateEvent>().Publish();
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, Resources.Openness_api_exception_occurred, MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        #endregion // tree structure

        #region group

        protected virtual void CreateNewGroup(IOpennessDemoNavigationContext navigationContext)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseProjectViewModel) + " - " + nameof(CreateNewGroup) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var newGroupName = string.Empty;
                var canCreate = false;

                while (!canCreate)
                {
                    newGroupName = GetNewGroupName(newGroupName);

                    if (!string.IsNullOrEmpty(newGroupName))
                    {
                        canCreate = true;
                        foreach (TreeViewItem item in SelectedItem.Items)
                        {
                            if ((string)item.Header == newGroupName)
                            {
                                MessageBox.Show($"A group with the name '{newGroupName}' already exists, enter a unique name.", "Group name already exists", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                                canCreate = false;
                                break;
                            }
                        }
                    }
                    else
                    {
                        break;
                    }
                }

                if (canCreate)
                {
                    IamBusy(processInfo);

                    ProjectServiceProvider.CreateNewGroup(newGroupName, (string)SelectedItem.Header, (Guid)SelectedItem.Tag, true);

                    RefreshContent(navigationContext);

                    IamDone(processInfo);
                }
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, Resources.Openness_api_exception_occurred, MessageBoxButtons.OK, MessageBoxIcon.Error);
                IamDone(processInfo);
            }

        }

        protected virtual string GetNewGroupName(string newGroupName)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseProjectViewModel) + " - " + nameof(GetNewGroupName) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            string result = string.Empty;

            var groupEditorView = _containerProvider.Resolve<GroupEditorView>();
            var groupEditorViewModel = groupEditorView.DataContext as GroupEditorViewModel;
            if (groupEditorViewModel != null)
            {
                groupEditorViewModel.GroupName = newGroupName;
                groupEditorViewModel.Title = "Create new Group";

                groupEditorView.ShowDialog();

                var dialogResult = groupEditorView.DialogResult;

                if (dialogResult != null && (bool)dialogResult)
                {
                    result = groupEditorViewModel.GroupName;
                }
            }

            return result;
        }

        #endregion // group

        #region import/export

        protected virtual async void CaxImportAsync(IOpennessDemoNavigationContext navigationContext)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseProjectViewModel) + " - " + nameof(CaxImportAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var caxImportView = _containerProvider.Resolve<CaxImportView>();

                if (!(caxImportView.DataContext is CaxImportViewModel caxImportViewModel))
                {
                    throw new ArgumentNullException(processInfo.ProcessMessage + " -> CaxImportViewModel is null!");
                }

                caxImportView.ShowDialog();
                var dialogResult = caxImportView.DialogResult;

                if (dialogResult != null && (bool)dialogResult)
                {
                    var caxImportFileInfo = caxImportViewModel.CaxImportFileInfo;
                    var caxImportOption = caxImportViewModel.SelectedCaxImportOptionInfo;

                    IamBusy(processInfo);

                    var result = ProjectServiceProvider.CaxImportAsync(caxImportFileInfo, caxImportOption.OptionType);
                    await result;

                    RefreshContent(navigationContext);

                    IamDone(processInfo);
                }
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, Resources.Openness_api_exception_occurred, MessageBoxButtons.OK, MessageBoxIcon.Error);
                IamDone(processInfo);
            }
        }

        protected virtual async void CaxExportAsync(IOpennessDemoNavigationContext navigationContext)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseProjectViewModel) + " - " + nameof(CaxExportAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                IamBusy(processInfo);

                var result = ProjectServiceProvider.CaxExportAsync();
                await result;

                IamDone(processInfo);
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, Resources.Openness_api_exception_occurred, MessageBoxButtons.OK, MessageBoxIcon.Error);
                IamDone(processInfo);
            }
        }

        protected virtual async void ImportElementAsync(IOpennessDemoNavigationContext navigationContext)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseProjectViewModel) + " - " + nameof(ImportElementAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var fileSearch = new OpenFileDialog();
                fileSearch.InitialDirectory = SettingsService.GetExportPath();
                fileSearch.Filter = "xml File|*.xml|SCL|*.scl|DB|*.db|AWL|*.awl|UDT|*.udt|All files(*.*)|*.*";
                fileSearch.FilterIndex = 1;
                fileSearch.RestoreDirectory = true;
                fileSearch.Multiselect = true;

                var dialogResult = fileSearch.ShowDialog();

                if (dialogResult == DialogResult.OK)
                {
                    if (fileSearch.FileNames != null && fileSearch.FileNames.Length > 0)
                    {
                        IList<FileInfo> fileInfos = new List<FileInfo>();

                        foreach (var fileName in fileSearch.FileNames)
                        {
                            fileInfos.Add(new FileInfo(fileName));
                        }
                        IamBusy(processInfo);

                        var result = ProjectServiceProvider.ImportElementAsync(fileInfos, true, (string)SelectedItem.Header, (Guid)SelectedItem.Tag, LogicalTreeView);
                        await result;

                        RefreshContent(navigationContext);

                        IamDone(processInfo);
                    }
                }
                else
                {
                    WriteTraceLogProxy(processInfo.ProcessMessage + " -> import element cancelled");
                }
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, Resources.Openness_api_exception_occurred, MessageBoxButtons.OK, MessageBoxIcon.Error);
                IamDone(processInfo);
            }
        }

        protected virtual async void ImportStructureAsync(IOpennessDemoNavigationContext navigationContext)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseProjectViewModel) + " - " + nameof(ImportStructureAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var folderBrowser = new FolderBrowserDialog();
                folderBrowser.SelectedPath = SettingsService.GetExportPath();

                if (folderBrowser.ShowDialog() == DialogResult.OK && Directory.Exists(folderBrowser.SelectedPath))
                {
                    IamBusy(processInfo);

                    var result = ProjectServiceProvider.ImportStructureAsync(folderBrowser.SelectedPath, (string)SelectedItem.Header, (Guid)SelectedItem.Tag, LogicalTreeView);
                    await result;

                    RefreshContent(navigationContext);

                    IamDone(processInfo);
                }
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, Resources.Openness_api_exception_occurred, MessageBoxButtons.OK, MessageBoxIcon.Error);
                IamDone(processInfo);
            }
        }

        protected virtual async void ExportStructureAsync(IOpennessDemoNavigationContext navigationContext)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseProjectViewModel) + " - " + nameof(ExportStructureAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                IamBusy(processInfo);

                var result = ProjectServiceProvider.ExportStructureAsync((string)SelectedItem.Header, (Guid)SelectedItem.Tag, LogicalTreeView);
                await result;

                IamDone(processInfo);
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, Resources.Openness_api_exception_occurred, MessageBoxButtons.OK, MessageBoxIcon.Error);
                IamDone(processInfo);
            }
        }

        #endregion // import/export

        #region plc

        protected virtual async void AddExternalSource(IOpennessDemoNavigationContext navigationContext)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseProjectViewModel) + " - " + nameof(AddExternalSource) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var fileSearch = new OpenFileDialog();
                fileSearch.InitialDirectory = SettingsService.GetExportPath();
                fileSearch.Filter = "Source files (*.awl;*.scl;*.db;*.udt)|*.awl;*.scl;*.db;*.udt|SCL (*.scl)|*.scl|STL (*.awl)|*.awl|UDT (*.udt)|*.udt|DB (*.db)|*.db|All files (*.*)|*.*";
                fileSearch.FilterIndex = 1;
                fileSearch.RestoreDirectory = true;
                fileSearch.Multiselect = true;

                var dialogResult = fileSearch.ShowDialog();

                if (dialogResult == DialogResult.OK)
                {
                    if (fileSearch.FileNames != null && fileSearch.FileNames.Length > 0)
                    {
                        IList<FileInfo> fileInfos = new List<FileInfo>();

                        foreach (var fileName in fileSearch.FileNames)
                        {
                            fileInfos.Add(new FileInfo(fileName));
                        }
                        IamBusy(processInfo);

                        var result = ProjectServiceProvider.AddExternalSourceAsync(fileInfos, (string)SelectedItem.Header, (Guid)SelectedItem.Tag, LogicalTreeView);
                        await result;

                        RefreshContent(navigationContext);

                        IamDone(processInfo);
                    }
                }
                else
                {
                    WriteTraceLogProxy(processInfo.ProcessMessage + " -> add external source cancelled");
                }
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, Resources.Openness_api_exception_occurred, MessageBoxButtons.OK, MessageBoxIcon.Error);
                IamDone(processInfo);
            }
        }

        protected virtual async void GenerateBlockFromSource(IOpennessDemoNavigationContext navigationContext)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseProjectViewModel) + " - " + nameof(GenerateBlockFromSource) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                IamBusy(processInfo);

                var result = ProjectServiceProvider.GenerateBlockFromSourceAsync((string)SelectedItem.Header, (Guid)SelectedItem.Tag, LogicalTreeView);
                await result;

                RefreshContent(navigationContext);

                IamDone(processInfo);
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, Resources.Openness_api_exception_occurred, MessageBoxButtons.OK, MessageBoxIcon.Error);
                IamDone(processInfo);
            }
        }

        protected virtual void GenerateSourceFromBlock(IOpennessDemoNavigationContext navigationContext)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseProjectViewModel) + " - " + nameof(GenerateSourceFromBlock) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var fileSearch = new SaveFileDialog();
                fileSearch.InitialDirectory = SettingsService.GetExportPath();
                fileSearch.Filter = "SCL (*.scl)|*.scl|STL (*.awl)|*.awl|UDT (*.udt)|*.udt|DB (*.db)|*.db";
                fileSearch.RestoreDirectory = true;
                fileSearch.FileOk += async delegate
                {
                    var destinationFileInfo = new FileInfo(fileSearch.FileName);

                    IamBusy(processInfo);

                    var result = ProjectServiceProvider.GenerateSourceFromBlockAsync(destinationFileInfo, (string)SelectedItem.Header, (Guid)SelectedItem.Tag, LogicalTreeView);
                    await result;

                    RefreshContent(navigationContext);

                    IamDone(processInfo);
                };

                fileSearch.ShowDialog();
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, Resources.Openness_api_exception_occurred, MessageBoxButtons.OK, MessageBoxIcon.Error);
                IamDone(processInfo);
            }
        }

        #endregion // plc

        #region edito

        protected virtual void OpenEditor(IOpennessDemoNavigationContext navigationContext)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseProjectViewModel) + " - " + nameof(OpenEditor) };
            WriteTraceLogProxy(processInfo.ProcessMessage);
        }

        protected virtual void OpenTopologyEditor(IOpennessDemoNavigationContext navigationContext)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseProjectViewModel) + " - " + nameof(OpenTopologyEditor) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                ProjectServiceProvider.ShowEditor("Topology");
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, Resources.Openness_api_exception_occurred, MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        protected virtual void OpenNetworkEditor(IOpennessDemoNavigationContext navigationContext)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseProjectViewModel) + " - " + nameof(OpenNetworkEditor) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                ProjectServiceProvider.ShowEditor("Network");
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, Resources.Openness_api_exception_occurred, MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        #endregion // editor

        #region content

        protected virtual void LoadContent(TreeViewItem obj)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseProjectViewModel) + " - " + nameof(LoadContent) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            WriteTraceLogProxy(processInfo.ProcessMessage + " -> " + nameof(LoadContentEvent));
            _eventAggregator.GetEvent<LoadContentEvent>().Publish(obj);
        }

        protected virtual void RefreshContent(IOpennessDemoNavigationContext navigationContext)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseProjectViewModel) + " - " + nameof(RefreshContent) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                ResetContent();

                LoadProjectAsync(navigationContext.ShowLogicalTree);
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, Resources.Openness_api_exception_occurred, MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        protected virtual void ResetContent()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseProjectViewModel) + " - " + nameof(ResetContent) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                if (TreeView != null)
                {
                    TreeView.Items.Clear();
                }
                if (ProjectTreeViewHandler != null)
                {
                    ProjectTreeViewHandler.View.Clear();
                    ProjectTreeViewHandler.SelectedItem = null;
                    _opennessDemoModel.SelectedTreeType = TreeTypeInformation.IsOther;
                }

                _opennessDemoModel.IsCompilable = false;
                _opennessDemoModel.CanExportExecute = false;
                _opennessDemoModel.CanImportElement = false;
                _opennessDemoModel.CanImportStructure = false;

                _opennessDemoModel.CanAddExternalSource = false;
                _opennessDemoModel.CanGenerateBlockFromSource = false;
                _opennessDemoModel.CanGenerateSourceFromBlock = false;

                WriteTraceLogProxy(processInfo.ProcessMessage + " -> " + nameof(TiaPortalStateEvent));
                _eventAggregator.GetEvent<TiaPortalStateEvent>().Publish();
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, Resources.Openness_api_exception_occurred, MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        #endregion // content

        protected virtual void SelectedCopySourceChanged(ILibraryContext libraryModel)// object selectedCopySourceItem)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseProjectViewModel) + " - " + nameof(SelectedCopySourceChanged) };
            WriteTraceLogProxy(processInfo.ProcessMessage);
        }

        protected virtual void DoCompile(IOpennessDemoNavigationContext navigationContext)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseProjectViewModel) + " - " + nameof(DoCompile) };
            WriteTraceLogProxy(processInfo.ProcessMessage);
        }

        protected virtual void IamBusy(ProcessInfo processInfo)
        {
            _eventAggregator.GetEvent<BusyEvent>().Publish(processInfo);
        }

        protected virtual void IamDone(ProcessInfo processInfo)
        {
            _eventAggregator.GetEvent<DoneEvent>().Publish(processInfo);
        }

        /// <summary>
        /// Mark the available destinations
        /// </summary>
        /// <param name="treeViewItem"></param>
        /// <param name="projectItem"></param>
        protected virtual void SetBackground(TreeViewItem treeViewItem, ProjectItem projectItem)
        {
            try
            {
                foreach (TreeViewItem sourceItem in treeViewItem.Items)
                {
                    if ((Guid)sourceItem.Tag == projectItem.Tag)
                    {
                        sourceItem.Background = Brushes.LightGreen;
                    }

                    SetBackground(sourceItem, projectItem);
                }
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, Resources.Openness_api_exception_occurred, MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }


        #endregion // methods

        #region INavigationAware implementation

        /// <summary>
        /// Navigate to target
        /// </summary>
        /// <param name="navigationContext"></param>
        public virtual void OnNavigatedTo(NavigationContext navigationContext)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseProjectViewModel) + " - " + nameof(OnNavigatedTo) };
            WriteTraceLogProxy(processInfo.ProcessMessage);
        }

        /// <summary>
        /// Is this the target?
        /// </summary>
        /// <param name="navigationContext"></param>
        /// <returns></returns>
        public virtual bool IsNavigationTarget(NavigationContext navigationContext)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseProjectViewModel) + " - " + nameof(IsNavigationTarget) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            return true;
        }

        /// <summary>
        /// Navigate from where?
        /// </summary>
        /// <param name="navigationContext"></param>
        public virtual void OnNavigatedFrom(NavigationContext navigationContext)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseProjectViewModel) + " - " + nameof(OnNavigatedFrom) };
            WriteTraceLogProxy(processInfo.ProcessMessage);
        }

        #endregion // INavigationAware implementation

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

        /// <summary>
        /// Execute writing trace log in different thread for all inner exceptions
        /// </summary>
        /// <param name="exception"></param>
        protected virtual void WriteTraceLogProxy(Exception exception)
        {
            if (!string.IsNullOrEmpty(exception.Message))
            {
                Application.Current.Dispatcher.Invoke(delegate
                {
                    _traceLogService.Write(exception.Message);
                });

            }
            if (exception.InnerException != null && !string.IsNullOrEmpty(exception.InnerException.Message))
            {
                WriteTraceLogProxy(exception.InnerException);
            }
        }

        #endregion // trace
    }
}
