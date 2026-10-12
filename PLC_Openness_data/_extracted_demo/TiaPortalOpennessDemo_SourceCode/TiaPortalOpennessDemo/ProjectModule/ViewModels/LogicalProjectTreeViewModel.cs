using Prism.Events;
using Prism.Ioc;
using Prism.Regions;
using ProjectModule.Base;
using System;
using System.Windows.Controls;
using System.Windows.Forms;
using System.Windows.Media;
using SharedResourceDictionary.Properties;
using TiaPortalOpennessAdapter.Contracts;
using TiaPortalOpennessAdapterContracts;
using TiaPortalOpennessCore.Commands;
using TiaPortalOpennessCore.Events.Content;
using TiaPortalOpennessCore.Events.Global;
using TiaPortalOpennessCore.Events.Libraries;
using TiaPortalOpennessCore.Events.Project;
using TiaPortalOpennessCore.Events.TiaPortal;
using TiaPortalOpennessCore.Utils;
using TiaPortalOpennessInfrastructure.Constants;
using TiaPortalOpennessInfrastructure.Contracts;
using TiaPortalOpennessInfrastructure.Utils;
using TreeView = System.Windows.Controls.TreeView;

namespace ProjectModule.ViewModels
{
    /// <summary>
    /// Logical tree view model implementation
    /// </summary>
    public class LogicalProjectTreeViewModel : BaseProjectViewModel
    {
        #region fields

        private readonly IEventAggregator _eventAggregator;

        #endregion // fields

        #region ctor

        public LogicalProjectTreeViewModel(IEventAggregator eventAggregator,
                                           ITraceLogService traceLogService,
                                           ISettingsService settingsService,
                                           IModuleProvider moduleProvider,
                                           IContainerProvider containerProvider,
                                           IOpennessDemoModel opennessDemoModel)
            : base(eventAggregator, traceLogService, settingsService, moduleProvider, containerProvider, opennessDemoModel)
        {
            TreeTypeInfo = "logical project tree";
            _eventAggregator = eventAggregator;

            _eventAggregator.GetEvent<OpenProjectEvent>().Subscribe(OpenProject, ThreadOption.UIThread, false, i => i.ShowLogicalTree && i.NavigationTarget == NavigationNames.LogicalProjectView);
            _eventAggregator.GetEvent<CreateNewProjectEvent>().Subscribe(CreateNewProjectAsync, ThreadOption.UIThread, false, i => i.ShowLogicalTree && i.NavigationTarget == NavigationNames.LogicalProjectView);
            _eventAggregator.GetEvent<LoadProjectEvent>().Subscribe(LoadProjectAsync, ThreadOption.UIThread, false, i => i);

            _eventAggregator.GetEvent<ProjectCreateNewGroupEvent>().Subscribe(CreateNewGroup, ThreadOption.UIThread, false, i => i.ShowLogicalTree && i.NavigationTarget == NavigationNames.LogicalProjectView);

            _eventAggregator.GetEvent<RefreshEvent>().Subscribe(RefreshContent, ThreadOption.UIThread, false, i => i.ShowLogicalTree && i.NavigationTarget == NavigationNames.LogicalProjectView);
            _eventAggregator.GetEvent<ResetContentEvent>().Subscribe(ResetContent);
            _eventAggregator.GetEvent<SaveProjectEvent>().Subscribe(SaveProjectAsync, ThreadOption.UIThread, false, i => i.ShowLogicalTree && i.NavigationTarget == NavigationNames.LogicalProjectView);
            _eventAggregator.GetEvent<CloseProjectEvent>().Subscribe(CloseProjectAsync, ThreadOption.UIThread, false, i => i.ShowLogicalTree && i.NavigationTarget == NavigationNames.LogicalProjectView);

            _eventAggregator.GetEvent<OpenEditorEvent>().Subscribe(OpenEditor, ThreadOption.UIThread, false, i => i.ShowLogicalTree && i.NavigationTarget == NavigationNames.LogicalProjectView);
            _eventAggregator.GetEvent<CompileEvent>().Subscribe(DoCompile, ThreadOption.UIThread, false, i => i.ShowLogicalTree && i.NavigationTarget == NavigationNames.LogicalProjectView);

            _eventAggregator.GetEvent<CaxImportEvent>().Subscribe(CaxImportAsync, ThreadOption.UIThread, false, i => i.ShowLogicalTree && i.NavigationTarget == NavigationNames.LogicalProjectView);
            _eventAggregator.GetEvent<CaxExportEvent>().Subscribe(CaxExportAsync, ThreadOption.UIThread, false, i => i.ShowLogicalTree && i.NavigationTarget == NavigationNames.LogicalProjectView);

            _eventAggregator.GetEvent<ImportElementEvent>().Subscribe(ImportElementAsync, ThreadOption.UIThread, false, i => i.ShowLogicalTree && i.NavigationTarget == NavigationNames.LogicalProjectView);
            _eventAggregator.GetEvent<ImportStructureEvent>().Subscribe(ImportStructureAsync, ThreadOption.UIThread, false, i => i.ShowLogicalTree && i.NavigationTarget == NavigationNames.LogicalProjectView);
            _eventAggregator.GetEvent<ExportStructureEvent>().Subscribe(ExportStructureAsync, ThreadOption.UIThread, false, i => i.ShowLogicalTree && i.NavigationTarget == NavigationNames.LogicalProjectView);

            _eventAggregator.GetEvent<AddExternalSourceEvent>().Subscribe(AddExternalSource, ThreadOption.UIThread, false, i => i.ShowLogicalTree && i.NavigationTarget == NavigationNames.LogicalProjectView);
            _eventAggregator.GetEvent<GenerateBlockFromSourceEvent>().Subscribe(GenerateBlockFromSource, ThreadOption.UIThread, false, i => i.ShowLogicalTree && i.NavigationTarget == NavigationNames.LogicalProjectView);
            _eventAggregator.GetEvent<GenerateSourceFromBlockEvent>().Subscribe(GenerateSourceFromBlock, ThreadOption.UIThread, false, i => i.ShowLogicalTree && i.NavigationTarget == NavigationNames.LogicalProjectView);

            _eventAggregator.GetEvent<SelectedCopySourceChangedEvent>().Subscribe(SelectedCopySourceChanged, ThreadOption.UIThread, false, i => i.NavigationContext.ShowLogicalTree && i.NavigationContext.NavigationTarget == NavigationNames.LogicalProjectView);
            _eventAggregator.GetEvent<ResetCopySourceEvent>().Subscribe(CopySourceClear, ThreadOption.UIThread, false, i => i.ShowLogicalTree && i.NavigationTarget == NavigationNames.LogicalProjectView);

            _eventAggregator.GetEvent<RefreshProjectEvent>().Subscribe(RefreshProject, ThreadOption.UIThread, false, i => i);
        }

        #endregion // ctor

        #region methods

        /// <summary>
        /// Create the tree view and refresh the tree view handler
        /// </summary>
        /// <param name="loadLogicalTree"></param>
        protected override void CreateTreeView(bool loadLogicalTree)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(LogicalProjectTreeViewModel) + " - " + nameof(CreateTreeView) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                if (loadLogicalTree)
                {

                    TreeView = new TreeView();

                    var logicalTree = ProjectServiceProvider.GetLogicalTree();
                    LogicalTreeView = true;

                    if (logicalTree != null)
                    {
                        TreeViewItem treeView = new TreeViewItem();
                        treeView.IsExpanded = true;

                        if (SettingsService.GetTreeExpendLevel() is int expandLevel)
                        {
                            WriteTraceLogProxy(processInfo.ProcessMessage + " -> TraverseTree");
                            foreach (var treeItem in logicalTree.Items)
                            {
                                treeItem.Level = 0;
                                treeView.Header = treeItem.Header;
                                treeView.Tag = treeItem.Tag;

                                TraverseTree(expandLevel, treeItem, treeView, treeItem.Level);
                            }

                        }

                        TreeView.Items.Add(treeView);
                    }

                    ProjectTreeViewHandler = new TreeViewHandler(new RelayCommand<DependencyPropertyEventArgs>(TreeViewItemSelectedChangedCallback));
                    WriteTraceLogProxy(processInfo.ProcessMessage + " -> Refresh TreeView - " + TreeView.Items.Count);
                    ProjectTreeViewHandler.Refresh(TreeView);
                    ProjectTreeViewHandler.SelectedItem = null;
                    WriteTraceLogProxy(processInfo.ProcessMessage + "->" + nameof(TiaPortalStateEvent));
                    _eventAggregator.GetEvent<TiaPortalStateEvent>().Publish();
                }
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message,  Resources.Openness_api_exception_occurred, MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        /// <summary>
        /// Call service provider to open the editor
        /// </summary>
        /// <param name="navigationContext"></param>
        protected override void OpenEditor(IOpennessDemoNavigationContext navigationContext)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(LogicalProjectTreeViewModel) + " - " + nameof(OpenEditor) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                ProjectServiceProvider.OpenEditor((string)SelectedItem.Header, (Guid)SelectedItem.Tag, navigationContext.ShowLogicalTree);
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, Resources.Openness_api_exception_occurred, MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        /// <summary>
        /// Call service provider to compile
        /// </summary>
        /// <param name="navigationContext"></param>
        protected override void DoCompile(IOpennessDemoNavigationContext navigationContext)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(LogicalProjectTreeViewModel) + " - " + nameof(DoCompile) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                ProjectServiceProvider.DoCompile((string)SelectedItem.Header, (Guid)SelectedItem.Tag, navigationContext.ShowLogicalTree);
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, Resources.Openness_api_exception_occurred, MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        /// <summary>
        /// The selected source object has been changed
        /// </summary>
        /// <param name="libraryModel"></param>
        protected override void SelectedCopySourceChanged(ILibraryContext libraryModel)// object selectedCopySourceItem)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(LogicalProjectTreeViewModel) + " - " + nameof(SelectedCopySourceChanged) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                if (libraryModel.NavigationContext.ShowLogicalTree)
                {
                    var treeTypeItems = ProjectServiceProvider.GetTreeTypeItems(libraryModel.LibraryItem, true);

                    if (TreeView != null)
                    {
                        ProjectTreeViewHandler.ClearBackground(TreeView);

                        if (treeTypeItems != null)
                        {
                            foreach (TreeViewItem item in TreeView.Items)
                            {
                                foreach (var sourceItem in treeTypeItems)
                                {
                                    SetBackground(item, sourceItem);

                                    if ((Guid)item.Tag == sourceItem.Tag)
                                    {
                                        item.Background = Brushes.LightGreen;
                                    }
                                }
                            }
                        }
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
        /// The copy process has been canceled
        /// </summary>
        /// <param name="navigationContext"></param>
        private void CopySourceClear(IOpennessDemoNavigationContext navigationContext)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(LogicalProjectTreeViewModel) + " - " + nameof(CopySourceClear) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                if (TreeView != null)
                {
                    ProjectTreeViewHandler.ClearBackground(TreeView);
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
        /// Refresh the project content
        /// </summary>
        /// <param name="loadLogicalTree"></param>
        private void RefreshProject(bool loadLogicalTree)
        {
            try
            {
                ResetContent();

                LoadTreeDataAsync(loadLogicalTree);
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
        public override void OnNavigatedTo(NavigationContext navigationContext)
        {
            //var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(LogicalProjectTreeViewModel) + " - " + nameof(OnNavigatedTo) };

            var processId = navigationContext.Parameters["ProcessId"] as string;
            var treeTypeName = navigationContext.Parameters["TreeTypeName"] as string;

            if (processId != ProcessId || treeTypeName != TreeTypeName)
            {
                ProcessId = processId;
                TreeTypeName = treeTypeName;

                ResetContent();

                LoadProjectAsync(true);
            }
        }

        /// <summary>
        /// Is this the target?
        /// </summary>
        /// <param name="navigationContext"></param>
        /// <returns></returns>
        public override bool IsNavigationTarget(NavigationContext navigationContext)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(LogicalProjectTreeViewModel) + " - " + nameof(IsNavigationTarget) };
            WriteTraceLogProxy(processInfo.ProcessMessage + " - " + navigationContext.Uri);

            return true;
        }

        /// <summary>
        /// Navigate from where?
        /// </summary>
        /// <param name="navigationContext"></param>
        public override void OnNavigatedFrom(NavigationContext navigationContext)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(LogicalProjectTreeViewModel) + " - " + nameof(OnNavigatedFrom) };
            WriteTraceLogProxy(processInfo.ProcessMessage + " - " + navigationContext.Uri);
            ProcessId = navigationContext.Parameters["ProcessId"] as string;
            TreeTypeName = navigationContext.Parameters["TreeTypeName"] as string;
        }

        #endregion // INavigationAware implementation
    }
}
