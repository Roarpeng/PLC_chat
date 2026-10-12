using LibraryModule.Views;
using Prism.Commands;
using Prism.Events;
using Prism.Ioc;
using Prism.Mvvm;
using System;
using System.IO;
using System.Windows.Controls;
using System.Windows.Forms;
using System.Windows.Media;
using SharedResourceDictionary.Properties;
using TiaPortalOpennessAdapter.Contracts;
using TiaPortalOpennessAdapter.Models;
using TiaPortalOpennessAdapterBase.Base;
using TiaPortalOpennessAdapterBase.Enums;
using TiaPortalOpennessAdapterContracts;
using TiaPortalOpennessCore.Commands;
using TiaPortalOpennessCore.Events.Content;
using TiaPortalOpennessCore.Events.Global;
using TiaPortalOpennessCore.Events.Libraries;
using TiaPortalOpennessCore.Events.Project;
using TiaPortalOpennessCore.Events.Shell;
using TiaPortalOpennessCore.Events.TiaPortal;
using TiaPortalOpennessCore.Utils;
using TiaPortalOpennessInfrastructure.Contracts;
using TiaPortalOpennessInfrastructure.Utils;
using Application = System.Windows.Application;
using TreeView = System.Windows.Controls.TreeView;

namespace LibraryModule.ViewModels
{
    /// <summary>
    /// 
    /// </summary>
    public class ProjectLibraryViewModel : BindableBase
    {
        #region fields

        private readonly IEventAggregator _eventAggregator;
        private readonly IModuleProvider _moduleProvider;
        private readonly ITraceLogService _traceLogService;
        private readonly ISettingsService _settingsService;

        private readonly IContainerProvider _containerProvider;
        private readonly IOpennessDemoModel _opennessDemoModel;

        private IOpennessDemoNavigationContext _opennessDemoNavigationContext;

        private IPlcSoftwareService _plcSoftwareService;
        private IHmiSoftwareService _hmiSoftwareService;
        private IHmiTargetService _hmiTargetService;
        private IStartdriveService _startdriveService;

        private ILibraryServiceProvider _libraryServiceProvider;

        private TreeViewHandler _projectLibraryTreeViewHandler;
        private TreeViewItem _selectedItem;
        private TreeViewItem _selectedSourceElement;
        private TreeViewItem _copyDestination;
        private TreeView _treeView;

        private ITiaPortalServiceProvider _tiaPortalServiceProvider;
        private IProjectServiceProvider _projectServiceProvider;
        private IMultiuserServiceProvider _multiuserServiceProvider;

        private string _copySourceInformation;

        private bool _canCreateGroup;
        private bool _canEditGroup;
        private bool _canShowCopyDialog;
        private bool _canExportVersion;
        private bool _copyLibElement;
        private bool _canCopy;
        private bool _isMasterCopy;

        #endregion // fields

        #region ctor

        /// <summary>
        /// 
        /// </summary>
        /// <param name="eventAggregator"></param>
        /// <param name="moduleProvider"></param>
        /// <param name="traceLogService"></param>
        /// <param name="settingsService"></param>
        /// <param name="containerProvider"></param>
        /// <param name="opennessDemoModel"></param>
        /// <param name="opennessDemoNavigationContext"></param>
        public ProjectLibraryViewModel(IEventAggregator eventAggregator, IModuleProvider moduleProvider, ITraceLogService traceLogService, ISettingsService settingsService, IContainerProvider containerProvider, IOpennessDemoModel opennessDemoModel, IOpennessDemoNavigationContext opennessDemoNavigationContext)
        {
            _eventAggregator = eventAggregator;
            _moduleProvider = moduleProvider;
            _traceLogService = traceLogService;
            _settingsService = settingsService;
            _containerProvider = containerProvider;
            _opennessDemoModel = opennessDemoModel;
            _opennessDemoNavigationContext = opennessDemoNavigationContext;

            _eventAggregator.GetEvent<SetNavigationPathEvent>().Subscribe(SetNavigationContext);
            _eventAggregator.GetEvent<ServiceProviderInitializeEvent>().Subscribe(InitServiceProvider);

            _eventAggregator.GetEvent<ProjectOpenedEvent>().Subscribe(LoadLibraryAsync);
            _eventAggregator.GetEvent<SelectedProjectItemChangedEvent>().Subscribe(SelectedProjectTargetChanged);
            _eventAggregator.GetEvent<RefreshLibraryEvent>().Subscribe(RefreshLibrary, ThreadOption.UIThread, false, globalLibrary => globalLibrary == false);
            _eventAggregator.GetEvent<ResetContentEvent>().Subscribe(ResetContent);
            _eventAggregator.GetEvent<CloseProjectEvent>().Subscribe(SetState);
            _eventAggregator.GetEvent<DisconnectTiaPortalEvent>().Subscribe(SetState);

            CreateGroupCommand = new DelegateCommand(CreateGroup);
            EditGroupCommand = new DelegateCommand(EditGroup);
            ShowCopyDialogCommand = new DelegateCommand(ShowCopyDialog);
            ExportVersionCommand = new DelegateCommand(ExportVersion);
            ExecuteCopyCommand = new DelegateCommand(ExecuteCopy).ObservesCanExecute(() => CanCopy);
            CancelCopyCommand = new DelegateCommand(CancelCopy);
        }

        private void SetNavigationContext(IOpennessDemoNavigationContext navigationContext)
        {
            _opennessDemoNavigationContext = navigationContext;
        }

        private void InitServiceProvider()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ProjectLibraryViewModel) + " - " + nameof(InitServiceProvider) };
            var version = _settingsService.GetSelectedOpennessApiVersion();
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                WriteTraceLogProxy(processInfo.ProcessMessage + " -> " + nameof(IPlcSoftwareService));
                _plcSoftwareService = _moduleProvider.GetService(typeof(IPlcSoftwareService)) as IPlcSoftwareService;
                WriteTraceLogProxy(processInfo.ProcessMessage + " -> " + nameof(IHmiSoftwareService));
                _hmiSoftwareService = _moduleProvider.GetService(typeof(IHmiSoftwareService)) as IHmiSoftwareService;
                WriteTraceLogProxy(processInfo.ProcessMessage + " -> " + nameof(IHmiTargetService));
                _hmiTargetService = _moduleProvider.GetService(typeof(IHmiTargetService)) as IHmiTargetService;
                WriteTraceLogProxy(processInfo.ProcessMessage + " -> " + nameof(IStartdriveService));
                _startdriveService = _moduleProvider.GetService(typeof(IStartdriveService)) as IStartdriveService;

                WriteTraceLogProxy(processInfo.ProcessMessage + " -> " + nameof(ITiaPortalServiceProvider));
                _tiaPortalServiceProvider = _moduleProvider.GetService(typeof(ITiaPortalServiceProvider)) as ITiaPortalServiceProvider;
                if (_tiaPortalServiceProvider != null)
                {
                    _tiaPortalServiceProvider.Initialize(_opennessDemoModel, _traceLogService);
                }
                else
                {
                    WriteTraceLogProxy(processInfo.ProcessMessage + " -> portal service provider for version - " + version + " not found!");
                }

                WriteTraceLogProxy(processInfo.ProcessMessage + " -> " + nameof(IProjectServiceProvider));
                _projectServiceProvider = _moduleProvider.GetService(typeof(IProjectServiceProvider)) as IProjectServiceProvider;
                if (_projectServiceProvider != null)
                {

                    _projectServiceProvider.Initialize(_opennessDemoModel, _traceLogService, _settingsService, _tiaPortalServiceProvider, _plcSoftwareService, _hmiSoftwareService, _hmiTargetService, _startdriveService);
                }
                else
                {
                    WriteTraceLogProxy(processInfo.ProcessMessage + " -> project service provider for version - " + version + " not found!");
                }

                WriteTraceLogProxy(processInfo.ProcessMessage + " -> " + nameof(IMultiuserServiceProvider));
                _multiuserServiceProvider = _moduleProvider.GetService(typeof(IMultiuserServiceProvider)) as IMultiuserServiceProvider;
                if (_multiuserServiceProvider != null)
                {
                    _multiuserServiceProvider.Initialize(_opennessDemoModel, _traceLogService, _tiaPortalServiceProvider, _projectServiceProvider);
                }
                else
                {
                    WriteTraceLogProxy(processInfo.ProcessMessage + " -> multi user service provider for version - " + version + " not found!");
                }

                WriteTraceLogProxy(processInfo.ProcessMessage + " -> " + nameof(ILibraryServiceProvider));
                _libraryServiceProvider = _moduleProvider.GetService(typeof(ILibraryServiceProvider)) as ILibraryServiceProvider;
                if (_libraryServiceProvider != null)
                {
                    _libraryServiceProvider.Initialize(_opennessDemoModel, _traceLogService, _tiaPortalServiceProvider, _projectServiceProvider, _multiuserServiceProvider, _plcSoftwareService, _hmiSoftwareService, _hmiTargetService, _startdriveService);
                }
                else
                {
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
        /// 
        /// </summary>
        public TreeViewHandler ProjectLibraryTreeViewHandler
        {
            get => _projectLibraryTreeViewHandler;
            set
            {
                SetProperty(ref _projectLibraryTreeViewHandler, value);
                RaisePropertyChanged();
            }
        }

        /// <summary>
        /// 
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
        /// 
        /// </summary>
        public TreeViewItem SelectedSourceElement
        {
            get => _selectedSourceElement;
            set
            {
                SetProperty(ref _selectedSourceElement, value);
                RaisePropertyChanged();
            }
        }

        /// <summary>
        /// 
        /// </summary>
        public TreeViewItem CopyDestination
        {
            get => _copyDestination;
            set
            {
                SetProperty(ref _copyDestination, value);
                RaisePropertyChanged();
            }
        }

        /// <summary>
        /// 
        /// </summary>
        public TreeView TreeView
        {
            get => _treeView;
            set => SetProperty(ref _treeView, value);
        }

        public string CopySourceInformation
        {
            get => _copySourceInformation;
            set
            {
                SetProperty(ref _copySourceInformation, value);
                RaisePropertyChanged();
            }

        }

        /// <summary>
        /// 
        /// </summary>
        public bool CanCreateGroup
        {
            get => _canCreateGroup;
            set
            {
                SetProperty(ref _canCreateGroup, value);
                RaisePropertyChanged();
            }
        }

        /// <summary>
        /// 
        /// </summary>
        public bool CanEditGroup
        {
            get => _canEditGroup;
            set
            {
                SetProperty(ref _canEditGroup, value);
                RaisePropertyChanged();
            }
        }

        /// <summary>
        /// 
        /// </summary>
        public bool CanShowCopyDialog
        {
            get => _canShowCopyDialog;
            set
            {
                SetProperty(ref _canShowCopyDialog, value);
                RaisePropertyChanged();
            }
        }
        public bool CanCopy
        {
            get => _canCopy;
            set
            {
                SetProperty(ref _canCopy, value);
                ExecuteCopyCommand.RaiseCanExecuteChanged();
            }
        }

        /// <summary>
        /// 
        /// </summary>
        public bool CanExportVersion
        {
            get => _canExportVersion;
            set
            {
                SetProperty(ref _canExportVersion, value);
                RaisePropertyChanged();
            }
        }


        /// <summary>
        /// 
        /// </summary>
        public bool CopyLibElement
        {
            get => _copyLibElement;
            set
            {
                SetProperty(ref _copyLibElement, value);
                RaisePropertyChanged();
            }
        }

        #endregion // properties

        #region commands

        /// <summary>
        /// 
        /// </summary>
        public DelegateCommand CreateGroupCommand { get; }

        /// <summary>
        /// 
        /// </summary>
        public DelegateCommand EditGroupCommand { get; }

        /// <summary>
        /// 
        /// </summary>
        public DelegateCommand ShowCopyDialogCommand { get; }

        /// <summary>
        /// 
        /// </summary>
        public DelegateCommand ExportVersionCommand { get; }

        /// <summary>
        /// 
        /// </summary>
        public DelegateCommand ExecuteCopyCommand { get; }

        /// <summary>
        /// 
        /// </summary>
        public DelegateCommand CancelCopyCommand { get; }

        #endregion // commands

        #region command implementation

        /// <summary>
        /// 
        /// </summary>
        private void CreateGroup()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ProjectLibraryViewModel) + " - " + nameof(CreateGroup) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var newGroupName = string.Empty;
                var canCreate = false;

                while (!canCreate)
                {
                    newGroupName = CreateNewOrEditGroupName(newGroupName, true);

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

                    _libraryServiceProvider.EditGroup(newGroupName, (string)SelectedItem.Header, (Guid)SelectedItem.Tag, false, true);

                    RefreshLibrary(false);

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

        /// <summary>
        /// 
        /// </summary>
        private void EditGroup()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ProjectLibraryViewModel) + " - " + nameof(EditGroup) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var editGroupName = string.Empty;
                var canEdit = false;

                while (!canEdit)
                {
                    editGroupName = CreateNewOrEditGroupName((string)SelectedItem.Header, false);

                    if (!string.IsNullOrEmpty(editGroupName))
                    {
                        canEdit = true;
                        foreach (TreeViewItem item in SelectedItem.Items)
                        {
                            if ((string)item.Header == editGroupName)
                            {
                                MessageBox.Show($"A group with the name '{editGroupName}' already exists, enter a unique name.", "Group name already exists", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                                canEdit = false;
                                break;
                            }
                        }
                    }
                    else
                    {
                        break;
                    }
                }

                if (canEdit)
                {
                    IamBusy(processInfo);

                    _libraryServiceProvider.EditGroup(editGroupName, (string)SelectedItem.Header, (Guid)SelectedItem.Tag, false, false);

                    RefreshLibrary(false);

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

        /// <summary>
        /// 
        /// </summary>
        private void ShowCopyDialog()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ProjectLibraryViewModel) + " - " + nameof(ShowCopyDialog) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                // select source and target
                CopyLibElement = true;

                //SetLibrarySourceForCopy();
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, Resources.Openness_api_exception_occurred, MessageBoxButtons.OK, MessageBoxIcon.Error);
                IamDone(processInfo);
            }
        }

        /// <summary>
        /// 
        /// </summary>
        private void ExecuteCopy()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ProjectLibraryViewModel) + " - " + nameof(ExecuteCopy) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var targetObject = _projectServiceProvider.GetTreeItemObject((string)CopyDestination.Header, (Guid)CopyDestination.Tag, _opennessDemoModel.DisplayLogicalTreeView);

                if (targetObject != null)
                {
                    if (_isMasterCopy)
                    {
                        _libraryServiceProvider.CreateCopyFromMasterCopy(targetObject, (string)SelectedSourceElement.Header, (Guid)SelectedSourceElement.Tag, false);
                    }
                    else
                    {
                        if (!_libraryServiceProvider.CopyLibraryVersionToProject(targetObject, (string)SelectedSourceElement.Header, (Guid)SelectedSourceElement.Tag, false))
                        {
                            // ToDo info to user
                        }
                    }
                }

                WriteTraceLogProxy(processInfo.ProcessMessage + " -> " + nameof(ResetCopySourceEvent));
                _eventAggregator.GetEvent<ResetCopySourceEvent>().Publish(_opennessDemoNavigationContext);// _opennessDemoModel.DisplayLogicalTreeView);
                WriteTraceLogProxy(processInfo.ProcessMessage + " -> " + nameof(RefreshProjectEvent));
                _eventAggregator.GetEvent<RefreshProjectEvent>().Publish(_opennessDemoModel.DisplayLogicalTreeView);
                RefreshLibrary(false);
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, Resources.Openness_api_exception_occurred, MessageBoxButtons.OK, MessageBoxIcon.Error);
                IamDone(processInfo);
            }
        }

        private void CanExecuteCopy()
        {
            CanCopy = SelectedSourceElement?.Header != null && CopyDestination?.Header != null;
        }

        private void SetLibrarySourceForCopy(bool isMasterCopy)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ProjectLibraryViewModel) + " - " + nameof(SetLibrarySourceForCopy) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                TreeViewItem copySource;

                if (isMasterCopy)
                {
                    copySource = SelectedItem;

                    CanShowCopyDialog = _libraryServiceProvider.CopySourceIsKnownType((string)SelectedItem.Header, (Guid)SelectedItem.Tag, false);
                }
                else
                {
                    var parent = VisualTreeHelper.GetParent(SelectedItem);

                    if (parent != null)
                    {
                        while (!(parent is TreeViewItem || parent is TreeView))
                        {
                            if (parent != null) parent = VisualTreeHelper.GetParent(parent);
                        }
                    }

                    CanShowCopyDialog = CanExportVersion;

                    copySource = parent as TreeViewItem;
                }


                if (copySource != null)
                {
                    SelectedSourceElement = CanShowCopyDialog ? SelectedItem : null;

                    CopySourceInformation = copySource.Header + " - " + SelectedItem.Header;

                    var libraryItem = _libraryServiceProvider.GetLibraryItem((string)copySource.Header, (Guid)copySource.Tag, false);

                    if (libraryItem != null)
                    {
                        WriteTraceLogProxy(processInfo.ProcessMessage + " -> " + nameof(SelectedCopySourceChangedEvent));
                        //_eventAggregator.GetEvent<SelectedCopySourceChangedEvent>().Publish(libraryItem);
                        _eventAggregator.GetEvent<SelectedCopySourceChangedEvent>().Publish(new LibraryContext(_opennessDemoNavigationContext, libraryItem));
                    }
                }

                CanExecuteCopy();
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, Resources.Openness_api_exception_occurred, MessageBoxButtons.OK, MessageBoxIcon.Error);
                IamDone(processInfo);
            }
        }

        /// <summary>
        /// 
        /// </summary>
        private void CancelCopy()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ProjectLibraryViewModel) + " - " + nameof(CreateGroup) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            CopyLibElement = false;

            _eventAggregator.GetEvent<ResetCopySourceEvent>().Publish(_opennessDemoNavigationContext);// _opennessDemoModel.DisplayLogicalTreeView);
        }

        /// <summary>
        /// 
        /// </summary>
        private void ExportVersion()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ProjectLibraryViewModel) + " - " + nameof(ExportVersion) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var exportTypeVersionView = _containerProvider.Resolve<ExportTypeVersionView>();
                var exportTypeVersionViewModel = exportTypeVersionView.DataContext as ExportTypeVersionViewModel;
                if (exportTypeVersionViewModel != null)
                {
                    exportTypeVersionViewModel.FileName =
                        ((TreeViewItem)SelectedItem.Parent).Header + ".xml";
                    exportTypeVersionView.ShowDialog();
                    exportTypeVersionView.Activate();
                    exportTypeVersionView.FileName.Focus();
                    var dialogResult = exportTypeVersionView.DialogResult;

                    if (dialogResult != null && (bool)dialogResult)
                    {
                        var fileName = exportTypeVersionViewModel.FileName;
                        var directory = exportTypeVersionViewModel.ExportPath;

                        var fullName = Path.Combine(directory, fileName);

                        FileInfo fileFullPath = new FileInfo(fullName);

                        var exportWithDefaults = _settingsService.GetExportWithDefaults();
                        var exportReadOnly = _settingsService.GetExportReadOnly();
                        int options = 0;
                        options += exportWithDefaults ? 1 : 0;
                        options += exportReadOnly ? 2 : 0;

                        _libraryServiceProvider.ExportVersion((string)SelectedItem.Header, (Guid)SelectedItem.Tag, false, fileFullPath, options);
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

        #endregion // command implementation

        #region methods

        private async void LoadLibraryAsync()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ProjectLibraryViewModel) + " - " + nameof(LoadLibraryAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                IamBusy(processInfo);
                var projectLibrary = _libraryServiceProvider.OpenLibraryAsync(false);
                await projectLibrary;

                CreateTreeView();

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

        private void CreateTreeView()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ProjectLibraryViewModel) + " - " + nameof(CreateTreeView) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                CanCreateGroup = false;
                CanEditGroup = false;
                CanShowCopyDialog = false;
                CanExportVersion = false;

                TreeView = new TreeView();

                var libraryTree = _libraryServiceProvider.GetProjectLibraryTree();

                if (libraryTree != null)
                {
                    TreeViewItem treeView = new TreeViewItem();
                    treeView.IsExpanded = true;

                    if (_settingsService.GetTreeExpendLevel() is int expandLevel)
                    {
                        foreach (var treeItem in libraryTree.Items)
                        {
                            treeItem.Level = 0;
                            treeView.Header = treeItem.Header;
                            treeView.Tag = treeItem.Tag;

                            WriteTraceLogProxy(processInfo.ProcessMessage + " -> TraverseTree");
                            TraverseTree(expandLevel, treeItem, treeView, treeItem.Level);
                        }
                    }

                    TreeView.Items.Add(treeView);
                }

                ProjectLibraryTreeViewHandler = new TreeViewHandler(new RelayCommand<DependencyPropertyEventArgs>(TreeViewItemSelectedChangedCallback));
                WriteTraceLogProxy(processInfo.ProcessMessage + " - Refresh TreeView");

                ProjectLibraryTreeViewHandler.Refresh(TreeView);
                ProjectLibraryTreeViewHandler.SelectedItem = null;
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, Resources.Openness_api_exception_occurred, MessageBoxButtons.OK, MessageBoxIcon.Error);
                IamDone(processInfo);
            }
        }

        private void TraverseTree(int expandLevel, TreeItem treeItem, TreeViewItem subTreeView, int itemLevel)// TreeItem treeItem, TreeViewItem subTreeView)
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

        private void ResetContent()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ProjectLibraryViewModel) + " - " + nameof(ResetContent) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                if (TreeView != null)
                {
                    TreeView.Items.Clear();
                }
                if (ProjectLibraryTreeViewHandler != null)
                {
                    ProjectLibraryTreeViewHandler.View.Clear();
                }

                CopyLibElement = false;

            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, Resources.Openness_api_exception_occurred, MessageBoxButtons.OK, MessageBoxIcon.Error);
                IamDone(processInfo);
            }
        }

        private async void RefreshLibrary(bool globalLibrary)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ProjectLibraryViewModel) + " - " + nameof(RefreshLibrary) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                IamBusy(processInfo);
                var projectLibrary = _libraryServiceProvider.OpenLibraryAsync(globalLibrary);
                await projectLibrary;
                IamDone(processInfo);

                CreateTreeView();
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, Resources.Openness_api_exception_occurred, MessageBoxButtons.OK, MessageBoxIcon.Error);
                IamDone(processInfo);
            }
        }

        private void SelectedProjectTargetChanged(TreeViewItem projectTargetItem)
        {
            if (projectTargetItem != null)
            {
                CopyDestination = projectTargetItem;
            }
            CanExecuteCopy();
        }

        private string CreateNewOrEditGroupName(string newGroupName, bool newGroup)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ProjectLibraryViewModel) + " - " + nameof(CreateNewOrEditGroupName) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                string result = string.Empty;

                var groupEditorView = _containerProvider.Resolve<GroupEditorView>();
                var groupEditorViewModel = groupEditorView.DataContext as GroupEditorViewModel;
                if (groupEditorViewModel != null)
                {
                    groupEditorViewModel.GroupName = newGroupName;
                    if (newGroup)
                    {
                        groupEditorViewModel.Title = "Create new Group";
                    }
                    else
                    {
                        groupEditorViewModel.Title = "Edit Group";
                    }
                }

                groupEditorView.ShowDialog();

                var dialogResult = groupEditorView.DialogResult;

                if (dialogResult != null && (bool)dialogResult)
                {
                    result = groupEditorView.GroupName.Text;
                }

                return result;
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, Resources.Openness_api_exception_occurred, MessageBoxButtons.OK, MessageBoxIcon.Error);
                IamDone(processInfo);
            }

            return null;
        }

        protected virtual void TreeViewItemSelectedChangedCallback(DependencyPropertyEventArgs obj)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ProjectLibraryViewModel) + " - " + nameof(TreeViewItemSelectedChangedCallback) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                ProjectLibraryTreeViewHandler.SelectedItem = obj.DependencyPropertyChangedEventArgs.NewValue as TreeViewItem;

                SelectedItem = ProjectLibraryTreeViewHandler.SelectedItem;

                if (SelectedItem != null && SelectedItem.Header != null && SelectedItem.Tag != null)
                {
                    var selectedTreeType = _libraryServiceProvider.GetTypeInformation((string)SelectedItem.Header, (Guid)SelectedItem.Tag, false);



                    // Command activation/deactivation
                    CanCreateGroup = selectedTreeType == TreeTypeInformation.IsFolderGroup ||
                                     selectedTreeType == TreeTypeInformation.IsTypeGroup;

                    CanEditGroup = CanCreateGroup;


                    CanExportVersion = selectedTreeType == TreeTypeInformation.IsTypeVersion &&
                                       !(((string)SelectedItem.Header).Contains("in work") ||
                                         ((string)SelectedItem.Header).Contains("in test"));



                    //CanShowCopyDialog = CanExportVersion || selectedTreeType == TreeTypeInformation.IsMasterCopy;

                    _isMasterCopy = selectedTreeType == TreeTypeInformation.IsMasterCopy;
                    SetLibrarySourceForCopy(_isMasterCopy);
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

        protected virtual void IamBusy(ProcessInfo processInfo)
        {
            _eventAggregator.GetEvent<BusyEvent>().Publish(processInfo);
        }

        protected virtual void IamDone(ProcessInfo processInfo)
        {
            _eventAggregator.GetEvent<DoneEvent>().Publish(processInfo);
        }

        private void SetState(IOpennessDemoNavigationContext obj)
        {
            CanCreateGroup = false;
            CanEditGroup = false;
            CanShowCopyDialog = false;
            CanExportVersion = false;
        }

        #endregion // methods

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
