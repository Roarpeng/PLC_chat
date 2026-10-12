using LibraryModule.Views;
using Prism.Commands;
using Prism.Events;
using Prism.Ioc;
using Prism.Mvvm;
using System;
using System.Collections.Generic;
using System.IO;
using System.Windows.Controls;
using System.Windows.Forms;
using SharedResourceDictionary.Properties;
using TiaPortalOpennessAdapter.Contracts;
using TiaPortalOpennessAdapterBase.Base;
using TiaPortalOpennessAdapterBase.Enums;
using TiaPortalOpennessAdapterBase.Models;
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
    public class GlobalLibraryViewModel : BindableBase
    {
        #region fields

        private readonly IEventAggregator _eventAggregator;
        private readonly ISettingsService _settingsService;
        private readonly IModuleProvider _moduleProvider;
        private readonly ITraceLogService _traceLogService;
        private readonly IContainerProvider _containerProvider;

        private ILibraryServiceProvider _libraryServiceProvider;

        private TreeViewHandler _globalLibraryTreeViewHandler;
        private TreeViewItem _selectedItem;
        private TreeView _treeView;
        private IList<LibraryInfo> _availableGlobalLibraryInfos;
        private IList<LibraryInfo> _openedGlobalLibraryInfos;
        private LibraryInfo _globalLibraryInfo;
        private LibraryInfo _selectedGlobalLibraryInfo;

        private string _libraryPath;
        private string _libraryName;

        private bool _canOpenSystemLibrary;
        private bool _canOpenUserLibrary;
        private bool _canCreateUserLibrary;
        private bool _canCloseUserLibrary;
        private bool _canUpdateProjectLibrary;
        private bool _userLibraryHasBeenChanged;
        private bool _canCreateGroup;
        private bool _canEditGroup;
        private bool _canExportVersion;

        #endregion // fields

        #region ctor

        public GlobalLibraryViewModel(IEventAggregator eventAggregator, ISettingsService settingsService, IModuleProvider moduleProvider, ITraceLogService traceLogService, IContainerProvider containerProvider)
        {
            _eventAggregator = eventAggregator;
            _settingsService = settingsService;
            _moduleProvider = moduleProvider;
            _traceLogService = traceLogService;
            _containerProvider = containerProvider;

            CanCreateUserLibrary = false;
            CanOpenUserLibrary = false;

            _eventAggregator.GetEvent<ServiceProviderInitializeEvent>().Subscribe(InitServiceProvider);

            _eventAggregator.GetEvent<ProjectOpenedEvent>().Subscribe(LoadLibrariesAsync);

            _eventAggregator.GetEvent<ResetContentEvent>().Subscribe(ResetContent);

            _eventAggregator.GetEvent<CloseProjectEvent>().Subscribe(SetState);
            _eventAggregator.GetEvent<DisconnectTiaPortalEvent>().Subscribe(SetState);

            _availableGlobalLibraryInfos = new List<LibraryInfo>();
            _openedGlobalLibraryInfos = new List<LibraryInfo>();

            OpenGlobalLibraryCommand = new DelegateCommand(OpenGlobalLibraryAsync);

            CreateUserLibraryCommand = new DelegateCommand(CreateLibraryAsync);
            OpenUserLibraryCommand = new DelegateCommand(OpenLibrary);
            SaveUserLibraryCommand = new DelegateCommand(SaveLibraryAsync);
            CloseUserLibraryCommand = new DelegateCommand(CloseLibraryAsync);
            UpdateProjectLibraryCommand = new DelegateCommand(UpdateProjectLibrary);
            ExportVersionCommand = new DelegateCommand(ExportVersion);
            CreateGroupCommand = new DelegateCommand(CreateGroup);
            EditGroupCommand = new DelegateCommand(EditGroup);
        }

        private void InitServiceProvider()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(GlobalLibraryViewModel) + " - " + nameof(InitServiceProvider) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                _libraryServiceProvider = _moduleProvider.GetService(typeof(ILibraryServiceProvider)) as ILibraryServiceProvider;
                if (_libraryServiceProvider == null)
                {
                    var version = _settingsService.GetSelectedOpennessApiVersion();
                    WriteTraceLogProxy(processInfo.ProcessMessage + " -> library service provider for version - " + version + " not found!");
                }
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, @"Openness api exception occurred", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }


        #endregion // ctor

        #region properties

        /// <summary>
        /// 
        /// </summary>
        public TreeView TreeView
        {
            get => _treeView;
            set => SetProperty(ref _treeView, value);
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
        public TreeViewHandler GlobalLibraryTreeViewHandler
        {
            get => _globalLibraryTreeViewHandler;
            set
            {
                SetProperty(ref _globalLibraryTreeViewHandler, value);
                RaisePropertyChanged();
            }
        }

        /// <summary>
        /// 
        /// </summary>
        public IList<LibraryInfo> AvailableGlobalLibraryInfos
        {
            get => _availableGlobalLibraryInfos;
            set
            {
                SetProperty(ref _availableGlobalLibraryInfos, value);
                RaisePropertyChanged();
            }
        }

        /// <summary>
        /// 
        /// </summary>
        public IList<LibraryInfo> OpenedGlobalLibraryInfos
        {
            get => _openedGlobalLibraryInfos;
            set
            {
                SetProperty(ref _openedGlobalLibraryInfos, value);
                RaisePropertyChanged();
            }
        }

        /// <summary>
        /// 
        /// </summary>
        public LibraryInfo GlobalLibraryInfo
        {
            get => _globalLibraryInfo;
            set
            {
                SetProperty(ref _globalLibraryInfo, value);
                RaisePropertyChanged();
            }
        }

        /// <summary>
        /// 
        /// </summary>
        public LibraryInfo SelectedGlobalLibraryInfo
        {
            get => _selectedGlobalLibraryInfo;
            set
            {
                SetProperty(ref _selectedGlobalLibraryInfo, value);
                SelectedGlobalLibraryInfoChanged(_selectedGlobalLibraryInfo);
            }
        }

        /// <summary>
        /// 
        /// </summary>
        public bool CanOpenSystemLibrary
        {
            get => _canOpenSystemLibrary;
            set
            {
                SetProperty(ref _canOpenSystemLibrary, value);
                RaisePropertyChanged();
            }
        }

        /// <summary>
        /// 
        /// </summary>
        public bool CanOpenUserLibrary
        {
            get => _canOpenUserLibrary;
            set
            {
                SetProperty(ref _canOpenUserLibrary, value);
                RaisePropertyChanged();
            }
        }

        /// <summary>
        /// 
        /// </summary>
        public bool CanCreateUserLibrary
        {
            get => _canCreateUserLibrary;
            set
            {
                SetProperty(ref _canCreateUserLibrary, value);
                RaisePropertyChanged();
            }
        }

        /// <summary>
        /// 
        /// </summary>
        public bool CanCloseUserLibrary
        {
            get => _canCloseUserLibrary;
            set
            {
                SetProperty(ref _canCloseUserLibrary, value);
                RaisePropertyChanged();
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
        public bool CanUpdateProjectLibrary
        {
            get => _canUpdateProjectLibrary;
            set
            {
                SetProperty(ref _canUpdateProjectLibrary, value);
                RaisePropertyChanged();
            }
        }

        /// <summary>
        /// 
        /// </summary>
        public bool UserLibraryHasBeenChanged
        {
            get => _userLibraryHasBeenChanged;
            set
            {
                SetProperty(ref _userLibraryHasBeenChanged, value);
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

        #endregion // properties

        #region commands

        /// <summary>
        /// 
        /// </summary>
        public DelegateCommand OpenGlobalLibraryCommand { get; }

        /// <summary>
        /// 
        /// </summary>
        public DelegateCommand CreateUserLibraryCommand { get; }

        /// <summary>
        /// 
        /// </summary>
        public DelegateCommand OpenUserLibraryCommand { get; }

        /// <summary>
        /// 
        /// </summary>
        public DelegateCommand SaveUserLibraryCommand { get; }

        /// <summary>
        /// 
        /// </summary>
        public DelegateCommand CloseUserLibraryCommand { get; }

        /// <summary>
        /// 
        /// </summary>
        public DelegateCommand UpdateProjectLibraryCommand { get; }

        /// <summary>
        /// 
        /// </summary>
        public DelegateCommand ExportVersionCommand { get; }

        /// <summary>
        /// 
        /// </summary>
        public DelegateCommand CreateGroupCommand { get; }

        /// <summary>
        /// 
        /// </summary>
        public DelegateCommand EditGroupCommand { get; }

        #endregion // commands

        #region command implementation

        ///// <summary>
        ///// 
        ///// </summary>
        //private void GlobalLibraryInfoSelectionChanged()
        //{
        //    throw new NotImplementedException();
        //}

        /// <summary>
        /// 
        /// </summary>
        private async void OpenGlobalLibraryAsync()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(GlobalLibraryViewModel) + " - " + nameof(OpenGlobalLibraryAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage);
            try
            {
                IamBusy(processInfo);
                var task = _libraryServiceProvider.OpenGlobalLibraryAsync(GlobalLibraryInfo.FileInfo, false);
                await task;

                RefreshGlobalLibraries();

                IamDone(processInfo);
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, @"Openness api exception occurred", MessageBoxButtons.OK, MessageBoxIcon.Error);
                IamDone(processInfo);
            }
        }

        /// <summary>
        /// 
        /// </summary>
        private async void CreateLibraryAsync()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(GlobalLibraryViewModel) + " - " + nameof(CreateLibraryAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {

                var createNewGlobalLibraryView = _containerProvider.Resolve<CreateNewGlobalLibraryView>();
                if (createNewGlobalLibraryView.DataContext is CreateNewGlobalLibraryViewModel createNewGlobalLibraryViewModel)
                {
                    createNewGlobalLibraryViewModel.Path = _settingsService.GetGlobalUserLibraryPath();
                    createNewGlobalLibraryView.ShowDialog();
                    var dialogResult = createNewGlobalLibraryView.DialogResult;

                    if (dialogResult != null && (bool)dialogResult)
                    {
                        _libraryName = createNewGlobalLibraryViewModel.LibraryName;
                        _libraryPath = createNewGlobalLibraryViewModel.Path;
                        var targetInfo = new DirectoryInfo(_libraryPath);

                        IamBusy(processInfo);

                        var result = _libraryServiceProvider.CreateNewGlobalLibraryAsync(targetInfo, _libraryName);
                        await result;

                        RefreshGlobalLibraries();

                        IamDone(processInfo);
                    }
                }
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, @"Openness api exception occurred", MessageBoxButtons.OK, MessageBoxIcon.Error);
                IamDone(processInfo);
            }
        }

        /// <summary>
        /// 
        /// </summary>
        private async void UpdateProjectLibrary()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(GlobalLibraryViewModel) + " - " + nameof(UpdateProjectLibrary) };
            WriteTraceLogProxy(processInfo.ProcessMessage);
            try
            {
                IamBusy(processInfo);
                var result = _libraryServiceProvider.UpdateProjectLibraryAsync((string)SelectedItem.Header, (Guid)SelectedItem.Tag);
                await result;

                WriteTraceLogProxy(processInfo.ProcessMessage + " -> " + nameof(RefreshLibraryEvent));
                _eventAggregator.GetEvent<RefreshLibraryEvent>().Publish(false);
                IamDone(processInfo);
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, @"Openness api exception occurred", MessageBoxButtons.OK, MessageBoxIcon.Error);
                IamDone(processInfo);
            }
        }

        /// <summary>
        /// 
        /// </summary>
        private void OpenLibrary()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(GlobalLibraryViewModel) + " - " + nameof(OpenLibrary) };
            WriteTraceLogProxy(processInfo.ProcessMessage);
            try
            {
                OpenFileDialog fileSearch = new OpenFileDialog();

                fileSearch.InitialDirectory = _settingsService.GetExportPath();
                fileSearch.Filter = @"Siemens user global library|*.al*";
                fileSearch.FilterIndex = 2;
                fileSearch.RestoreDirectory = true;
                var result = fileSearch.ShowDialog();

                if (DialogResult.OK == result)
                {
                    string libraryPath = fileSearch.FileName;
                    OpenLibraryAsync(libraryPath);
                }
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, @"Openness api exception occurred", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        /// <summary>
        /// 
        /// </summary>
        private async void SaveLibraryAsync()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(GlobalLibraryViewModel) + " - " + nameof(SaveLibraryAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage);
            try
            {
                IamBusy(processInfo);
                var result = _libraryServiceProvider.SaveGlobalLibraryAsync((string)SelectedItem.Header, (Guid)SelectedItem.Tag, true);
                await result;

                IamDone(processInfo);
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, @"Openness api exception occurred", MessageBoxButtons.OK, MessageBoxIcon.Error);
                IamDone(processInfo);
            }
        }

        /// <summary>
        /// 
        /// </summary>
        private async void CloseLibraryAsync()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(GlobalLibraryViewModel) + " - " + nameof(CloseLibraryAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                if (CheckLibraryModified())
                {
                    IamBusy(processInfo);
                    var result = _libraryServiceProvider.CloseGlobalLibraryAsync((string)SelectedItem.Header, (Guid)SelectedItem.Tag, true);
                    await result;

                    RefreshGlobalLibraries();

                    IamDone(processInfo);
                }
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, @"Openness api exception occurred", MessageBoxButtons.OK, MessageBoxIcon.Error);
                IamDone(processInfo);
            }
        }

        /// <summary>
        /// 
        /// </summary>
        private void ExportVersion()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(GlobalLibraryViewModel) + " - " + nameof(ExportVersion) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var exportTypeVersionView = _containerProvider.Resolve<ExportTypeVersionView>();
                exportTypeVersionView.FileName.Text = ((TreeViewItem)SelectedItem.Parent).Header.ToString();
                exportTypeVersionView.ShowDialog();
                exportTypeVersionView.Activate();
                exportTypeVersionView.FileName.Focus();
                var dialogResult = exportTypeVersionView.DialogResult;

                if (dialogResult != null && (bool)dialogResult)
                {
                    if (exportTypeVersionView.DataContext is ExportTypeVersionViewModel exportTypeVersionViewModel)
                    {
                        var fileName = exportTypeVersionViewModel.FileName;
                        var directory = exportTypeVersionViewModel.ExportPath;

                        var fullName = Path.Combine(directory, fileName);

                        FileInfo path = new FileInfo(fullName);

                        var exportWithDefaults = _settingsService.GetExportWithDefaults();
                        var exportReadOnly = _settingsService.GetExportReadOnly();
                        int options = 0;
                        options += exportWithDefaults ? 1 : 0;
                        options += exportReadOnly ? 2 : 0;

                        _libraryServiceProvider.ExportVersion((string)SelectedItem.Header, (Guid)SelectedItem.Tag, true, path, options);
                    }
                }
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, "Openness api exception occurred", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        /// <summary>
        /// 
        /// </summary>
        private void CreateGroup()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(GlobalLibraryViewModel) + " - " + nameof(CreateGroup) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var newGroupName = string.Empty;
                var canCreate = false;

                while (!canCreate)
                {
                    newGroupName = EditNewGroupName(newGroupName);

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

                    _libraryServiceProvider.EditGroup(newGroupName, (string)SelectedItem.Header, (Guid)SelectedItem.Tag, true, true);

                    RefreshGlobalLibraries();

                    IamDone(processInfo);
                }
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, Resources.Openness_api_exception_occurred, MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        /// <summary>
        /// 
        /// </summary>
        private void EditGroup()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(GlobalLibraryViewModel) + " - " + nameof(EditGroup) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var editGroupName = string.Empty;
                var canEdit = false;

                while (!canEdit)
                {
                    editGroupName = EditNewGroupName((string)SelectedItem.Header);

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

                    RefreshGlobalLibraries();

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
        /// <param name="newGroupName"></param>
        /// <returns></returns>
        private string EditNewGroupName(string newGroupName)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(GlobalLibraryViewModel) + " - " + nameof(EditNewGroupName) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                string result = string.Empty;

                var groupEditor = _containerProvider.Resolve<GroupEditorView>();
                groupEditor.GroupName.Text = newGroupName;

                groupEditor.ShowDialog();

                var dialogResult = groupEditor.DialogResult;

                if (dialogResult != null && (bool)dialogResult)
                {
                    result = groupEditor.GroupName.Text;
                }

                return result;
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, Resources.Openness_api_exception_occurred, MessageBoxButtons.OK, MessageBoxIcon.Error);
            }

            return null;
        }

        #endregion // command implementation

        #region methods

        /// <summary>
        /// 
        /// </summary>
        /// <param name="path"></param>
        private async void OpenLibraryAsync(string path)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(GlobalLibraryViewModel) + " - " + nameof(OpenLibraryAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage);
            try
            {
                IamBusy(processInfo);
                FileInfo fileInfo = new FileInfo(path);

                var result = _libraryServiceProvider.OpenGlobalLibraryAsync(fileInfo, true);
                await result;

                RefreshGlobalLibraries();

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

        /// <summary>
        /// 
        /// </summary>
        private async void LoadLibrariesAsync()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(GlobalLibraryViewModel) + " - " + nameof(LoadLibrariesAsync) };
            WriteTraceLogProxy(processInfo.ProcessMessage);
            try
            {
                IamBusy(processInfo);
                var globalLibrary = _libraryServiceProvider.OpenLibraryAsync(true);
                await globalLibrary;
                IamDone(processInfo);

                CanCreateUserLibrary = true;
                CanOpenUserLibrary = true;

                RefreshGlobalLibraries();
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
        private void RefreshGlobalLibraries()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(GlobalLibraryViewModel) + " - " + nameof(RefreshGlobalLibraries) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var tempAvailableInfos = new List<LibraryInfo>();
                var tempOpenInfos = new List<LibraryInfo>();
                AvailableGlobalLibraryInfos.Clear();
                OpenedGlobalLibraryInfos.Clear();

                var availableInfos = _libraryServiceProvider.GetGlobalLibraryInfos();

                foreach (var info in availableInfos)
                {
                    if (info.IsOpen)
                    {
                        tempOpenInfos.Add(info);
                    }
                    else
                    {
                        tempAvailableInfos.Add(info);
                    }
                }

                AvailableGlobalLibraryInfos = tempAvailableInfos;
                OpenedGlobalLibraryInfos = tempOpenInfos;

                CreateTreeView();

            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, Resources.Openness_api_exception_occurred, MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        /// <summary>
        /// 
        /// </summary>
        private void CreateTreeView()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(GlobalLibraryViewModel) + " - " + nameof(CreateTreeView) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                TreeView = new TreeView();

                var libraryTree = _libraryServiceProvider.GetGlobalLibraryTree();

                if (libraryTree != null)
                {
                    foreach (var treeItem in libraryTree.Items)
                    {
                        TreeViewItem treeView = new TreeViewItem();
                        treeView.IsExpanded = false;

                        treeView.Header = treeItem.Header;
                        treeView.Tag = treeItem.Tag;

                        WriteTraceLogProxy(processInfo.ProcessMessage + " -> TraverseTree");
                        TraverseTree(treeItem, treeView);
                        TreeView.Items.Add(treeView);
                    }

                }

                GlobalLibraryTreeViewHandler = new TreeViewHandler(new RelayCommand<DependencyPropertyEventArgs>(TreeViewItemSelectedChangedCallback));
                WriteTraceLogProxy(processInfo.ProcessMessage + " -> Refresh TreeView - " + TreeView.Items.Count.ToString());
                GlobalLibraryTreeViewHandler.Refresh(TreeView);
                GlobalLibraryTreeViewHandler.SelectedItem = null;
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, Resources.Openness_api_exception_occurred, MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        /// <summary>
        /// 
        /// </summary>
        /// <param name="treeItem"></param>
        /// <param name="subTreeView"></param>
        private void TraverseTree(TreeItem treeItem, TreeViewItem subTreeView)
        {
            try
            {
                foreach (var item in treeItem.Items)
                {
                    var subsubTreeView = new TreeViewItem() { Header = item.Header, Tag = item.Tag };
                    subsubTreeView.IsExpanded = false;
                    TraverseTree(item, subsubTreeView);
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
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(GlobalLibraryViewModel) + " - " + nameof(ResetContent) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                if (TreeView != null)
                {
                    TreeView.Items.Clear();
                }
                if (GlobalLibraryTreeViewHandler != null)
                {
                    GlobalLibraryTreeViewHandler.View.Clear();
                }

                CanOpenSystemLibrary = false;
                CanCreateUserLibrary = false;
                CanOpenUserLibrary = false;
                CanCloseUserLibrary = false;
                UserLibraryHasBeenChanged = false;
                CanUpdateProjectLibrary = false;
                CanExportVersion = false;
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
        /// <param name="selectedGlobalLibraryInfo"></param>
        private void SelectedGlobalLibraryInfoChanged(LibraryInfo selectedGlobalLibraryInfo)
        {
            CanOpenSystemLibrary = selectedGlobalLibraryInfo != null;
        }

        /// <summary>
        /// 
        /// </summary>
        /// <param name="obj"></param>
        protected virtual void TreeViewItemSelectedChangedCallback(DependencyPropertyEventArgs obj)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(GlobalLibraryViewModel) + " - " + nameof(TreeViewItemSelectedChangedCallback) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                GlobalLibraryTreeViewHandler.SelectedItem = obj.DependencyPropertyChangedEventArgs.NewValue as TreeViewItem;

                SelectedItem = GlobalLibraryTreeViewHandler.SelectedItem;

                if (SelectedItem != null && SelectedItem.Header != null && SelectedItem.Tag != null)
                {
                    CanCloseUserLibrary = _libraryServiceProvider.GetTypeInformation((string)SelectedItem.Header, (Guid)SelectedItem.Tag, true) == TreeTypeInformation.IsUserLib;
                    UserLibraryHasBeenChanged = _libraryServiceProvider.LibraryHasBeenChanged((string)SelectedItem.Header, (Guid)SelectedItem.Tag, true);

                    CanCreateGroup = _libraryServiceProvider.GetTypeInformation((string)SelectedItem.Header, (Guid)SelectedItem.Tag, true) == TreeTypeInformation.IsFolderGroup || _libraryServiceProvider.GetTypeInformation((string)SelectedItem.Header, (Guid)SelectedItem.Tag, true) == TreeTypeInformation.IsTypeGroup;

                    CanExportVersion =
                        _libraryServiceProvider.GetTypeInformation((string)SelectedItem.Header, (Guid)SelectedItem.Tag, true) ==
                        TreeTypeInformation.IsTypeVersion &&
                        !(((string)SelectedItem.Header).Contains("in work") || ((string)SelectedItem.Header).Contains("in test"));

                    var libraryTypeInfo = _libraryServiceProvider.GetTypeInformation((string)SelectedItem.Header, (Guid)SelectedItem.Tag, true);
                    CanUpdateProjectLibrary = libraryTypeInfo == TreeTypeInformation.IsSysLib ||
                                              libraryTypeInfo == TreeTypeInformation.IsUserLib;
                    if (CanUpdateProjectLibrary)
                    {
                        WriteTraceLogProxy(processInfo.ProcessMessage + " -> " + nameof(SelectedSystemLibraryChangedEvent));
                        _eventAggregator.GetEvent<SelectedSystemLibraryChangedEvent>().Publish(SelectedItem);
                    }
                    else
                    {
                        WriteTraceLogProxy(processInfo.ProcessMessage + " -> " + nameof(SelectedSystemLibraryChangedEvent));
                        _eventAggregator.GetEvent<SelectedSystemLibraryChangedEvent>().Publish(null);
                    }
                }
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, Resources.Openness_api_exception_occurred, MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        /// <summary>
        /// 
        /// </summary>
        /// <returns></returns>
        private bool CheckLibraryModified()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(GlobalLibraryViewModel) + " - " + nameof(CheckLibraryModified) };
            bool librarySaved = true;

            if (UserLibraryHasBeenChanged)
            {
                librarySaved = false;
                var result = MessageBox.Show("Do you want to save the changes to the current library?", "Library has been modified", MessageBoxButtons.YesNoCancel, MessageBoxIcon.Warning);

                if (result == DialogResult.Yes || result == DialogResult.No)
                {
                    if (result == DialogResult.Yes)
                    {
                        librarySaved = true;
                        SaveLibraryAsync();
                    }
                }
                else
                {
                    WriteTraceLogProxy(processInfo.ProcessMessage + " - Close library was canceled!");
                }
            }

            return librarySaved;
        }

        private void SetState(IOpennessDemoNavigationContext obj)
        {
            CanCreateUserLibrary = false;
            CanOpenUserLibrary = false;
            UserLibraryHasBeenChanged = false;
            CanCloseUserLibrary = false;
            CanUpdateProjectLibrary = false;
            CanExportVersion = false;
        }

        /// <summary>
        /// 
        /// </summary>
        /// <param name="processInfo"></param>
        protected virtual void IamBusy(ProcessInfo processInfo)
        {
            _eventAggregator.GetEvent<BusyEvent>().Publish(processInfo);
        }

        /// <summary>
        /// 
        /// </summary>
        /// <param name="processInfo"></param>
        protected virtual void IamDone(ProcessInfo processInfo)
        {
            _eventAggregator.GetEvent<DoneEvent>().Publish(processInfo);
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
