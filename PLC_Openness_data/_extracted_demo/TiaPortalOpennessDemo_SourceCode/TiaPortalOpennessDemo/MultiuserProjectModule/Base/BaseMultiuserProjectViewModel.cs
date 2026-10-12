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
using TiaPortalOpennessAdapterContracts;
using TiaPortalOpennessCore.Events.Content;
using TiaPortalOpennessCore.Events.Global;
using TiaPortalOpennessCore.Events.Project;
using TiaPortalOpennessCore.Events.Session;
using TiaPortalOpennessCore.Events.Shell;
using TiaPortalOpennessCore.Events.TiaPortal;
using TiaPortalOpennessCore.Utils;
using TiaPortalOpennessInfrastructure.Constants;
using TiaPortalOpennessInfrastructure.Contracts;
using TiaPortalOpennessInfrastructure.Utils;
using Application = System.Windows.Application;
using TreeView = System.Windows.Controls.TreeView;

namespace MultiuserProjectModule.Base
{
    public class BaseMultiuserProjectViewModel : BindableBase, INavigationAware
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
        internal IPlcSoftwareService PlcSoftwareService;
        internal IHmiSoftwareService HmiSoftwareService;

        internal string ProcessId;
        internal string TreeTypeName;

        protected bool LogicalTreeView = false;
        #endregion // fields 

        #region ctor

        public BaseMultiuserProjectViewModel(IEventAggregator eventAggregator, ITraceLogService traceLogService, ISettingsService settingsService, IModuleProvider moduleProvider, IContainerProvider containerProvider, IOpennessDemoModel opennessDemoModel)
        {
            _eventAggregator = eventAggregator;
            _traceLogService = traceLogService;
            SettingsService = settingsService;
            _moduleProvider = moduleProvider;

            _containerProvider = containerProvider;
            _opennessDemoModel = opennessDemoModel;

            _eventAggregator.GetEvent<ServiceProviderInitializeEvent>().Subscribe(InitServiceProvider);

            _eventAggregator.GetEvent<OpenTopologyEditorEvent>().Subscribe(OpenTopologyEditor, ThreadOption.UIThread, false, i => i.NavigationTarget == NavigationNames.LogicalLocalSessionView || i.NavigationTarget == NavigationNames.PhysicalLocalSessionView);
            _eventAggregator.GetEvent<OpenNetworkEditorEvent>().Subscribe(OpenNetworkEditor, ThreadOption.UIThread, false, i => i.NavigationTarget == NavigationNames.LogicalLocalSessionView || i.NavigationTarget == NavigationNames.PhysicalLocalSessionView);

            _eventAggregator.GetEvent<DisconnectTiaPortalEvent>().Subscribe(DisconnectTiaPortal);
        }

        private void DisconnectTiaPortal(IOpennessDemoNavigationContext obj)
        {
            ProcessId = string.Empty;
            TreeTypeName = string.Empty;
        }

        protected virtual void InitServiceProvider()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseMultiuserProjectViewModel) + " - " + nameof(InitServiceProvider) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                TiaPortalServiceProvider = _moduleProvider.GetService(typeof(ITiaPortalServiceProvider)) as ITiaPortalServiceProvider;
                if (TiaPortalServiceProvider != null)
                {
                    WriteTraceLogProxy(processInfo.ProcessMessage + " -> Init " + nameof(ITiaPortalServiceProvider));
                    TiaPortalServiceProvider.Initialize(_opennessDemoModel, _traceLogService);
                }
                else
                {
                    var version = SettingsService.GetSelectedOpennessApiVersion();
                    WriteTraceLogProxy(processInfo.ProcessMessage + " -> portal service provider for version - " + version + " not found!");
                }

                ProjectServiceProvider = _moduleProvider.GetService(typeof(IProjectServiceProvider)) as IProjectServiceProvider;
                if (ProjectServiceProvider != null)
                {
                    WriteTraceLogProxy(processInfo.ProcessMessage + " -> Init " + nameof(IPlcSoftwareService));
                    PlcSoftwareService = _moduleProvider.GetService(typeof(IPlcSoftwareService)) as IPlcSoftwareService;
                    WriteTraceLogProxy(processInfo.ProcessMessage + " -> Init " + nameof(IHmiSoftwareService));
                    HmiSoftwareService = _moduleProvider.GetService(typeof(IHmiSoftwareService)) as IHmiSoftwareService;
                    WriteTraceLogProxy(processInfo.ProcessMessage + " -> " + nameof(IHmiTargetService));
                    var hmiTargetService = _moduleProvider.GetService(typeof(IHmiTargetService)) as IHmiTargetService;
                    WriteTraceLogProxy(processInfo.ProcessMessage + " -> " + nameof(IStartdriveService));
                    var sinamicsService = _moduleProvider.GetService(typeof(IStartdriveService)) as IStartdriveService;


                    if (PlcSoftwareService != null && HmiSoftwareService != null)
                    {
                        ProjectServiceProvider.Initialize(_opennessDemoModel, _traceLogService, SettingsService, TiaPortalServiceProvider, PlcSoftwareService, HmiSoftwareService, hmiTargetService, sinamicsService);
                    }
                    else
                    {
                        var version = SettingsService.GetSelectedOpennessApiVersion();
                        WriteTraceLogProxy(processInfo.ProcessMessage + " -> plc-software service or hmi-software service for version - " + version + " not found!");
                    }
                }
                else
                {
                    var version = SettingsService.GetSelectedOpennessApiVersion();
                    WriteTraceLogProxy(processInfo.ProcessMessage + " -> project service provider for version - " + version + " not found!");
                }

                MultiuserServiceProvider = _moduleProvider.GetService(typeof(IMultiuserServiceProvider)) as IMultiuserServiceProvider;
                if (MultiuserServiceProvider != null)
                {
                    WriteTraceLogProxy(processInfo.ProcessMessage + " -> Init " + nameof(IMultiuserServiceProvider));
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
        /// Type info for tree item
        /// </summary>
        public string TreeTypeInfo = string.Empty;

        /// <summary>
        /// the tree view 
        /// </summary>
        public TreeView TreeView
        {
            get => _treeView;
            set => SetProperty(ref _treeView, value);
        }

        /// <summary>
        /// tree view handler
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

        protected virtual void OpenLocalSession(IOpennessDemoNavigationContext navigationContext)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseMultiuserProjectViewModel) + " - " + nameof(OpenLocalSession) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                OpenFileDialog fileSearch = new OpenFileDialog();

                fileSearch.InitialDirectory = SettingsService.GetLocalSessionPath();
                fileSearch.Filter = @"Siemens TIA Portal project|*.als*";
                fileSearch.FilterIndex = 2;
                fileSearch.RestoreDirectory = true;
                var result = fileSearch.ShowDialog();

                if (DialogResult.OK != result)
                {
                    WriteTraceLogProxy(processInfo.ProcessMessage + " -> open local session canceled!");
                    return;

                }
                string selectedProject = fileSearch.FileName;
                OpenLocalSessionAsync(navigationContext.ShowLogicalTree, selectedProject);
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, Resources.Openness_api_exception_occurred, MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        protected virtual async void OpenLocalSessionAsync(bool loadLogicalTree, string projectPath)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseMultiuserProjectViewModel) + " - " + nameof(OpenLocalSessionAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                IamBusy(processInfo);
                var result = MultiuserServiceProvider.OpenLocalSessionAsync(projectPath);
                await result;
                IamDone(processInfo);

                _opennessDemoModel.ProjectModel.ProjectName = ProjectServiceProvider.GetCurrentProjectName();
                _opennessDemoModel.ProjectModel.TargetDirectory = ProjectServiceProvider.GetCurrentProjectPath();
                _opennessDemoModel.ProjectModel.ProjectOpened = true;
                _opennessDemoModel.LocalSessionOpened = true;

                WriteTraceLogProxy(processInfo.ProcessMessage + " -> " + nameof(TiaPortalStateEvent));
                _eventAggregator.GetEvent<TiaPortalStateEvent>().Publish();
                WriteTraceLogProxy(processInfo.ProcessMessage + " -> " + nameof(ProjectOpenedEvent));
                _eventAggregator.GetEvent<ProjectOpenedEvent>().Publish();
                LoadProjectAsync(loadLogicalTree);
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
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseMultiuserProjectViewModel) + " - " + nameof(LoadProjectAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                IamBusy(processInfo);
                var tree = ProjectServiceProvider.LoadLocalSessionTreeStructureAsync(loadLogicalTree);
                await tree;

                CreateTreeView();

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

        protected virtual async void SaveLocalSessionAsync(IOpennessDemoNavigationContext navigationContext)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseMultiuserProjectViewModel) + " - " + nameof(SaveLocalSessionAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                IamBusy(processInfo);
                var result = MultiuserServiceProvider.SaveLocalSessionAsync();
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

        protected virtual async void CloseLocalSessionAsync(IOpennessDemoNavigationContext navigationContext)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseMultiuserProjectViewModel) + " - " + nameof(CloseLocalSessionAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                IamBusy(processInfo);
                var result = MultiuserServiceProvider.CloseLocalSessionAsync();
                await result;
                IamDone(processInfo);

                _opennessDemoModel.ProjectModel.ProjectName = string.Empty;
                _opennessDemoModel.ProjectModel.TargetDirectory = null;
                _opennessDemoModel.ProjectModel.ProjectOpened = false;
                _opennessDemoModel.LocalSessionOpened = false;


                WriteTraceLogProxy(processInfo.ProcessMessage + " -> " + nameof(LocalSessionClosedEvent));
                _eventAggregator.GetEvent<LocalSessionClosedEvent>().Publish();
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

        protected virtual async void CloseMultiuserProjectAsync(bool loadLogicalTree)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseMultiuserProjectViewModel) + " - " + nameof(CloseMultiuserProjectAsync) };
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
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, Resources.Openness_api_exception_occurred, MessageBoxButtons.OK, MessageBoxIcon.Error);
                IamDone(processInfo);
            }
        }

        protected virtual void CreateTreeView()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseMultiuserProjectViewModel) + " - " + nameof(CreateTreeView) };
            WriteTraceLogProxy(processInfo.ProcessMessage);
        }

        protected virtual void TraverseTree(int expandLevel, TreeItem treeItem, TreeViewItem subTreeView, int itemLevel)
        {
            try
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
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, Resources.Openness_api_exception_occurred, MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        protected virtual void IamBusy(ProcessInfo processInfo)
        {
            _eventAggregator.GetEvent<BusyEvent>().Publish(processInfo);
        }

        protected virtual void IamDone(ProcessInfo processInfo)
        {
            _eventAggregator.GetEvent<DoneEvent>().Publish(processInfo);
        }

        protected virtual void MultiuserProjectTreeViewItemSelectedChangedCallback(DependencyPropertyEventArgs obj)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseMultiuserProjectViewModel) + " - " + nameof(MultiuserProjectTreeViewItemSelectedChangedCallback) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                ProjectTreeViewHandler.SelectedItem = obj.DependencyPropertyChangedEventArgs.NewValue as TreeViewItem;
                SelectedItem = ProjectTreeViewHandler.SelectedItem;

                if (SelectedItem != null && SelectedItem.Header != null && SelectedItem.Tag != null)
                {
                    LoadContent(SelectedItem);

                    _opennessDemoModel.SelectedTreeType = ProjectServiceProvider.GetTypeInformation((string)SelectedItem.Header, (Guid)SelectedItem.Tag, LogicalTreeView);

                    _opennessDemoModel.IsCompilable = ProjectServiceProvider.CheckIfCompilable((string)SelectedItem.Header, (Guid)SelectedItem.Tag, LogicalTreeView);
                    _opennessDemoModel.CanExportExecute = ProjectServiceProvider.CheckIfCanExportExecute((string)SelectedItem.Header, (Guid)SelectedItem.Tag, LogicalTreeView);
                    _opennessDemoModel.CanImportElement = ProjectServiceProvider.CheckIfCanImportElement((string)SelectedItem.Header, (Guid)SelectedItem.Tag, LogicalTreeView);
                    _opennessDemoModel.CanImportStructure = ProjectServiceProvider.CheckIfCanImportStructure((string)SelectedItem.Header, (Guid)SelectedItem.Tag, LogicalTreeView);

                    _opennessDemoModel.CanAddExternalSource = ProjectServiceProvider.CheckIfCanAddExternalSource((string)SelectedItem.Header, (Guid)SelectedItem.Tag, LogicalTreeView);
                    _opennessDemoModel.CanGenerateBlockFromSource = ProjectServiceProvider.CheckIfCanGenerateBlockFromSource((string)SelectedItem.Header, (Guid)SelectedItem.Tag, LogicalTreeView);
                    _opennessDemoModel.CanGenerateSourceFromBlock = ProjectServiceProvider.CheckIfCanGenerateSourceFromBlock((string)SelectedItem.Header, (Guid)SelectedItem.Tag, LogicalTreeView);

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

        #region import/export

        protected virtual async void CaxImportAsync(IOpennessDemoNavigationContext navigationContext)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseMultiuserProjectViewModel) + " - " + nameof(CaxImportAsync) };
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
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseMultiuserProjectViewModel) + " - " + nameof(CaxExportAsync) };
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
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseMultiuserProjectViewModel) + " - " + nameof(ImportElementAsync) };
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
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseMultiuserProjectViewModel) + " - " + nameof(ImportStructureAsync) };
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
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseMultiuserProjectViewModel) + " - " + nameof(ExportStructureAsync) };
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
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseMultiuserProjectViewModel) + " - " + nameof(AddExternalSource) };
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
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseMultiuserProjectViewModel) + " - " + nameof(GenerateBlockFromSource) };
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
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseMultiuserProjectViewModel) + " - " + nameof(GenerateSourceFromBlock) };
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
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseMultiuserProjectViewModel) + " - " + nameof(OpenEditor) };
            WriteTraceLogProxy(processInfo.ProcessMessage);
        }

        protected virtual void OpenTopologyEditor(IOpennessDemoNavigationContext navigationContext)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseMultiuserProjectViewModel) + " - " + nameof(OpenTopologyEditor) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                MultiuserServiceProvider.ShowEditor("Topology");
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
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseMultiuserProjectViewModel) + " - " + nameof(OpenNetworkEditor) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                MultiuserServiceProvider.ShowEditor("Network");
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
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseMultiuserProjectViewModel) + " - " + nameof(LoadContent) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                WriteTraceLogProxy(processInfo.ProcessMessage + " -> " + nameof(LoadContentEvent));
                _eventAggregator.GetEvent<LoadContentEvent>().Publish(obj);
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, Resources.Openness_api_exception_occurred, MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        protected virtual void RefreshContent(IOpennessDemoNavigationContext navigationContext)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseMultiuserProjectViewModel) + " - " + nameof(RefreshContent) };
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
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseMultiuserProjectViewModel) + " - " + nameof(ResetContent) };
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
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseMultiuserProjectViewModel) + " - " + nameof(SelectedCopySourceChanged) };
            WriteTraceLogProxy(processInfo.ProcessMessage);
        }

        protected virtual void DoCompile(IOpennessDemoNavigationContext navigationContext)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseMultiuserProjectViewModel) + " - " + nameof(DoCompile) };
            WriteTraceLogProxy(processInfo.ProcessMessage);
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
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseMultiuserProjectViewModel) + " - " + nameof(OnNavigatedTo) };
            WriteTraceLogProxy(processInfo.ProcessMessage);
        }

        /// <summary>
        /// Is this the target?
        /// </summary>
        /// <param name="navigationContext"></param>
        /// <returns></returns>
        public virtual bool IsNavigationTarget(NavigationContext navigationContext)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseMultiuserProjectViewModel) + " - " + nameof(IsNavigationTarget) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            return true;
        }

        /// <summary>
        /// Navigate from where?
        /// </summary>
        /// <param name="navigationContext"></param>
        public virtual void OnNavigatedFrom(NavigationContext navigationContext)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(BaseMultiuserProjectViewModel) + " - " + nameof(OnNavigatedFrom) };
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
