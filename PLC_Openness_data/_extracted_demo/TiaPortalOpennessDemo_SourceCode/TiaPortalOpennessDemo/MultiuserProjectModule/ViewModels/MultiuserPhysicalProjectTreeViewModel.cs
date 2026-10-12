using MultiuserProjectModule.Base;
using Prism.Events;
using Prism.Ioc;
using Prism.Regions;
using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using SharedResourceDictionary.Properties;
using TiaPortalOpennessAdapter.Contracts;
using TiaPortalOpennessAdapterContracts;
using TiaPortalOpennessCore.Commands;
using TiaPortalOpennessCore.Events.Content;
using TiaPortalOpennessCore.Events.Global;
using TiaPortalOpennessCore.Events.Libraries;
using TiaPortalOpennessCore.Events.Project;
using TiaPortalOpennessCore.Events.Session;
using TiaPortalOpennessCore.Utils;
using TiaPortalOpennessInfrastructure.Constants;
using TiaPortalOpennessInfrastructure.Contracts;
using TiaPortalOpennessInfrastructure.Utils;

namespace MultiuserProjectModule.ViewModels
{
    public class MultiuserPhysicalProjectTreeViewModel : BaseMultiuserProjectViewModel
    {
        #region fields

        #endregion // fields

        #region ctor

        public MultiuserPhysicalProjectTreeViewModel(IEventAggregator eventAggregator,
                                                    ITraceLogService traceLogService,
                                                    ISettingsService settingsService,
                                                    IModuleProvider moduleProvider,
                                                    IContainerProvider containerProvider,
                                                    IOpennessDemoModel opennessDemoModel)
                                                    : base(eventAggregator, traceLogService, settingsService, moduleProvider, containerProvider, opennessDemoModel)
        {
            TreeTypeInfo = "local session physical project tree";
            var eventAggregator1 = eventAggregator;

            eventAggregator1.GetEvent<OpenLocalSessionEvent>().Subscribe(OpenLocalSession, ThreadOption.UIThread, false, i => i.ShowLogicalTree == false && i.NavigationTarget == NavigationNames.PhysicalLocalSessionView);
            eventAggregator1.GetEvent<SaveLocalSessionEvent>().Subscribe(SaveLocalSessionAsync, ThreadOption.UIThread, false, i => i.ShowLogicalTree == false && i.NavigationTarget == NavigationNames.PhysicalLocalSessionView);
            eventAggregator1.GetEvent<CloseLocalSessionEvent>().Subscribe(CloseLocalSessionAsync, ThreadOption.UIThread, false, i => i.ShowLogicalTree == false && i.NavigationTarget == NavigationNames.PhysicalLocalSessionView);

            eventAggregator1.GetEvent<RefreshEvent>().Subscribe(RefreshContent, ThreadOption.UIThread, false, i => i.ShowLogicalTree == false && i.NavigationTarget == NavigationNames.PhysicalLocalSessionView);

            eventAggregator1.GetEvent<OpenEditorEvent>().Subscribe(OpenEditor, ThreadOption.UIThread, false, i => i.ShowLogicalTree == false && i.NavigationTarget == NavigationNames.PhysicalLocalSessionView);

            eventAggregator1.GetEvent<CompileEvent>().Subscribe(DoCompile, ThreadOption.UIThread, false, i => i.ShowLogicalTree == false && i.NavigationTarget == NavigationNames.PhysicalLocalSessionView);

            eventAggregator1.GetEvent<CaxImportEvent>().Subscribe(CaxImportAsync, ThreadOption.UIThread, false, i => i.ShowLogicalTree == false && i.NavigationTarget == NavigationNames.PhysicalLocalSessionView);
            eventAggregator1.GetEvent<CaxExportEvent>().Subscribe(CaxExportAsync, ThreadOption.UIThread, false, i => i.ShowLogicalTree == false && i.NavigationTarget == NavigationNames.PhysicalLocalSessionView);

            eventAggregator1.GetEvent<ImportElementEvent>().Subscribe(ImportElementAsync, ThreadOption.UIThread, false, i => i.ShowLogicalTree == false && i.NavigationTarget == NavigationNames.PhysicalLocalSessionView);
            eventAggregator.GetEvent<ImportStructureEvent>().Subscribe(ImportStructureAsync, ThreadOption.UIThread, false, i => i.ShowLogicalTree == false && i.NavigationTarget == NavigationNames.PhysicalLocalSessionView);
            eventAggregator1.GetEvent<ExportStructureEvent>().Subscribe(ExportStructureAsync, ThreadOption.UIThread, false, i => i.ShowLogicalTree == false && i.NavigationTarget == NavigationNames.PhysicalLocalSessionView);


            eventAggregator1.GetEvent<ResetContentEvent>().Subscribe(ResetContent);
            eventAggregator1.GetEvent<CloseMultiuserProjectEvent>().Subscribe(CloseMultiuserProjectAsync, ThreadOption.UIThread, false, i => i == false);

            eventAggregator1.GetEvent<SelectedCopySourceChangedEvent>().Subscribe(SelectedCopySourceChanged, ThreadOption.UIThread, false, i => i.NavigationContext.ShowLogicalTree == false && i.NavigationContext.NavigationTarget == NavigationNames.PhysicalLocalSessionView);

        }

        #endregion // ctor

        #region methods

        protected override void CreateTreeView()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(MultiuserPhysicalProjectTreeViewModel) + " - " + nameof(CreateTreeView) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                TreeView = new TreeView();

                var physicalTree = ProjectServiceProvider.GetPhysicalTree();
                LogicalTreeView = false;

                if (physicalTree != null)
                {
                    TreeViewItem treeView = new TreeViewItem();
                    treeView.IsExpanded = true;

                    if (SettingsService.GetTreeExpendLevel() is int expandLevel)
                    {
                        WriteTraceLogProxy(processInfo.ProcessMessage + " - " + nameof(CreateTreeView) + " -> TraverseTree");
                        foreach (var treeItem in physicalTree.Items)
                        {
                            treeItem.Level = 0;
                            treeView.Header = treeItem.Header;
                            treeView.Tag = treeItem.Tag;

                            TraverseTree(expandLevel, treeItem, treeView, treeItem.Level);
                        }

                    }
                    TreeView.Items.Add(treeView);
                }

                ProjectTreeViewHandler = new TreeViewHandler(new RelayCommand<DependencyPropertyEventArgs>(MultiuserProjectTreeViewItemSelectedChangedCallback));
                WriteTraceLogProxy(processInfo.ProcessMessage + " - " + nameof(CreateTreeView) + " -> Refresh TreeView - " + TreeView.Items.Count);
                ProjectTreeViewHandler.Refresh(TreeView);
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, Resources.Openness_api_exception_occurred, MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }

        /// <summary>
        /// Call service provider to open the editor
        /// </summary>
        /// <param name="navigationContext"></param>
        protected override void OpenEditor(IOpennessDemoNavigationContext navigationContext)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(MultiuserPhysicalProjectTreeViewModel) + " - " + nameof(OpenEditor) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                ProjectServiceProvider.OpenEditor((string)SelectedItem.Header, (Guid)SelectedItem.Tag, navigationContext.ShowLogicalTree);
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, Resources.Openness_api_exception_occurred, MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }

        /// <summary>
        /// The selected source object has been changed
        /// </summary>
        /// <param name="libraryModel"></param>
        protected override void SelectedCopySourceChanged(ILibraryContext libraryModel)// object selectedCopySourceItem)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(MultiuserPhysicalProjectTreeViewModel) + " - " + nameof(SelectedCopySourceChanged) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                if (!libraryModel.NavigationContext.ShowLogicalTree)
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
                MessageBox.Show(e.Message, Resources.Openness_api_exception_occurred, MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }



        protected override void DoCompile(IOpennessDemoNavigationContext navigationContext)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(MultiuserPhysicalProjectTreeViewModel) + " - " + nameof(DoCompile) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                ProjectServiceProvider.DoCompile((string)SelectedItem.Header, (Guid)SelectedItem.Tag, navigationContext.ShowLogicalTree);
            }
            catch (Exception e)
            {
                WriteTraceLogProxy(e.Message);
                if (e.InnerException != null) WriteTraceLogProxy(e.InnerException);
                MessageBox.Show(e.Message, Resources.Openness_api_exception_occurred, MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }

        #endregion // methods

        #region INavigationAware implementation

        public override void OnNavigatedTo(NavigationContext navigationContext)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(MultiuserLogicalProjectTreeViewModel) + " - " + nameof(OnNavigatedTo) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            var processId = navigationContext.Parameters["ProcessId"] as string;
            var treeTypeName = navigationContext.Parameters["TreeTypeName"] as string;

            if (processId != ProcessId || treeTypeName != TreeTypeName)
            {
                ProcessId = processId;
                TreeTypeName = treeTypeName;

                ResetContent();

                LoadProjectAsync(false);
            }
        }

        public override bool IsNavigationTarget(NavigationContext navigationContext)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(MultiuserLogicalProjectTreeViewModel) + " - " + nameof(IsNavigationTarget) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            return true;
        }

        public override void OnNavigatedFrom(NavigationContext navigationContext)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(MultiuserLogicalProjectTreeViewModel) + " - " + nameof(OnNavigatedFrom) };
            WriteTraceLogProxy(processInfo.ProcessMessage);
            ProcessId = navigationContext.Parameters["ProcessId"] as string;
            TreeTypeName = navigationContext.Parameters["TreeTypeName"] as string;
        }

        #endregion // INavigationAware implementation
    }
}
