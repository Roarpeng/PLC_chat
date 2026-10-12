using Prism.Commands;
using Prism.Events;
using Prism.Ioc;
using Prism.Mvvm;
using Prism.Regions;
using System;
using System.Reflection;
using System.Windows;
using System.Windows.Controls;
using TiaPortalOpennessAdapter.Contracts;
using TiaPortalOpennessAdapterBase.Enums;
using TiaPortalOpennessAdapterContracts;
using TiaPortalOpennessCore.Events.Content;
using TiaPortalOpennessCore.Events.Global;
using TiaPortalOpennessCore.Events.Libraries;
using TiaPortalOpennessCore.Events.Project;
using TiaPortalOpennessCore.Events.Session;
using TiaPortalOpennessCore.Events.TiaPortal;
using TiaPortalOpennessCore.Views;
using TiaPortalOpennessInfrastructure.Constants;
using TiaPortalOpennessInfrastructure.Contracts;

namespace TiaPortalOpennessCore.ViewModels
{
    /// <summary>
    /// The MenuViewModel definition of commands and the implementation for interaction with user
    /// </summary>
    public class MenuViewModel : BindableBase
    {
        #region fields

        private ITiaPortalServiceProvider               _tiaPortalServiceProvider;

        private readonly IEventAggregator               _eventAggregator;
        private readonly IModuleProvider                _moduleProvider;
        private readonly ITraceLogService               _traceLogService;
        private readonly ISettingsService               _settingsService;
        private readonly IRegionManager                 _regionManager;
        private readonly IContainerProvider             _containerProvider;
        private readonly IOpennessDemoNavigationContext _opennessDemoNavigationContext;

        private IOpennessDemoModel                      _opennessDemoModel;

        private bool                                    _baseServiceLoaded;
        private bool                                    _tiaPortalOpened;
        private bool                                    _canDisconnect;
        private bool                                    _canConnect;
        private bool                                    _showLogicalTree;
        private bool                                    _projectOpened;

        private bool                                    _canBeSaveProject;
        private bool                                    _canBeCloseProject;
        private bool                                    _localSessionOpened;

        private bool                                    _canBeSaveLocalSession;
        private bool                                    _canBeCloseLocalSession;
        private bool                                    _canUpdateProjectLibrary;

        private bool                                    _canOpenEditor;
        private bool                                    _canCompile;
        private bool                                    _canCreateNewGroup;
        private bool                                    _canImportElement;
        private bool                                    _canImportStructure;
        private bool                                    _canExportStructure;
        private bool                                    _canAddExternalSource;
        private bool                                    _canGenerateBlockFromSource;
        private bool                                    _canGenerateSourceFromBlock;

        private string                                  _navigationPath;
        private string                                  _treeViewType;
        private const string EmptyNavigationTarget = "EmptyProjectTreeView";

        #endregion // fields

        #region ctor

        /// <summary>
        /// Default constructor
        /// </summary>
        /// <param name="eventAggregator"></param>
        /// <param name="moduleProvider"></param>
        /// <param name="traceLogService"></param>
        /// <param name="settingsService"></param>
        /// <param name="regionManager"></param>
        /// <param name="opennessDemoModel"></param>
        /// <param name="containerProvider"></param>
        public MenuViewModel(IEventAggregator eventAggregator, IModuleProvider moduleProvider, ITraceLogService traceLogService, ISettingsService settingsService, IRegionManager regionManager, IOpennessDemoModel opennessDemoModel, IOpennessDemoNavigationContext opennessDemoNavigationContext, IContainerProvider containerProvider)
        {
            _eventAggregator = eventAggregator;
            _moduleProvider = moduleProvider;
            _traceLogService = traceLogService;
            _settingsService = settingsService;
            _regionManager = regionManager;
            _containerProvider = containerProvider;
            _opennessDemoModel = opennessDemoModel;

            TreeViewType = NavigationNames.DefaultTreeNavigation;
            _opennessDemoNavigationContext = opennessDemoNavigationContext;

            WriteTraceLogProxy(nameof(MenuViewModel));

            #region subscribe events

            _eventAggregator.GetEvent<InitEnvironmentEvent>().Subscribe(InitEnvironment);

            _eventAggregator.GetEvent<ServiceProviderInitializeEvent>().Subscribe(InitServiceProvider);
            _eventAggregator.GetEvent<TiaPortalStateEvent>().Subscribe(GetTiaPortalState);
            _eventAggregator.GetEvent<NavigationRequestEvent>().Subscribe(Navigate);

            _eventAggregator.GetEvent<SelectedSystemLibraryChangedEvent>().Subscribe(SelectedSystemLibraryChanged);
            _eventAggregator.GetEvent<SelectedProjectItemChangedEvent>().Subscribe(SelectedProjectItemChanged);
            _eventAggregator.GetEvent<UpdateViewNavigationEvent>().Subscribe(UpdateViewNavigation);

            _eventAggregator.GetEvent<LocalSessionOpenedEvent>().Subscribe(GetTiaPortalState);
            _eventAggregator.GetEvent<TiaPortalDisconnectedEvent>().Subscribe(GetTiaPortalState);
            _eventAggregator.GetEvent<LocalSessionSavedEvent>().Subscribe(GetTiaPortalState);
            _eventAggregator.GetEvent<LocalSessionClosedEvent>().Subscribe(GetTiaPortalState);
            _eventAggregator.GetEvent<ProjectClosedEvent>().Subscribe(GetTiaPortalState);
            _eventAggregator.GetEvent<SelectedProcessIdChangedEvent>().Subscribe(GetTiaPortalState);
            _eventAggregator.GetEvent<TiaPortalClosedEvent>().Subscribe(GetTiaPortalState);
            _eventAggregator.GetEvent<TiaPortalConnectedEvent>().Subscribe(GetTiaPortalState);
            _eventAggregator.GetEvent<TiaPortalDisconnectedEvent>().Subscribe(GetTiaPortalState);

            _eventAggregator.GetEvent<ConnectProjectEvent>().Subscribe(ConnectTiaPortal);

            #endregion // subscribe events

            #region commands

            OpenTiaPortalCommand           = new DelegateCommand(OpenTiaPortal, CanOpenTiaPortal);
            ConnectTiaPortalCommand        = new DelegateCommand(ConnectTiaPortal).ObservesCanExecute(() => OpennessDemoModel.PortalAvailable);
            DisconnectTiaPortalCommand     = new DelegateCommand(DisconnectTiaPortal).ObservesCanExecute(() => TiaPortalOpened);
            CloseTiaPortalCommand          = new DelegateCommand(CloseTiaPortal).ObservesCanExecute(() => TiaPortalOpened);

            OpenLocalSessionCommand        = new DelegateCommand(OpenLocalSession, CanOpenLocalSession);
            SaveLocalSessionCommand        = new DelegateCommand(SaveLocalSession, CanSaveLocalSession);
            CloseLocalSessionCommand       = new DelegateCommand(CloseLocalSession, CanCloseLocalSession);

            CreateProjectCommand           = new DelegateCommand(CreateProject, CanOpenProject);
            OpenProjectCommand             = new DelegateCommand(OpenProject, CanOpenProject);
            SaveProjectCommand             = new DelegateCommand(SaveProject, CanSaveProject);
            CloseProjectCommand            = new DelegateCommand(CloseProject, CanCloseProject);

            ExitCommand                    = new DelegateCommand(DoExit);

            RefreshCommand                 = new DelegateCommand(Refresh);

            CreateGroupCommand             = new DelegateCommand(CreateNewGroup).ObservesCanExecute(() => CanCreateNewGroup);

            OpenEditorCommand              = new DelegateCommand(OpenEditor).ObservesCanExecute(() => CanOpenEditor);
            OpenTopologyViewCommand        = new DelegateCommand(OpenTopologyView).ObservesCanExecute(() => ProjectOpened);
            OpenNetworkViewCommand         = new DelegateCommand(OpenNetworkView).ObservesCanExecute(() => ProjectOpened);

            ExecuteCompilerCommand         = new DelegateCommand(ExecuteCompiler).ObservesCanExecute(() => CanCompile);

            CaxImportCommand               = new DelegateCommand(CaxImport).ObservesCanExecute(() => ProjectOpened);
            CaxExportCommand               = new DelegateCommand(CaxExport).ObservesCanExecute(() => ProjectOpened);
            ImportElementCommand           = new DelegateCommand(ImportElement).ObservesCanExecute(() => CanImportElement);
            ImportStructureCommand         = new DelegateCommand(ImportStructure).ObservesCanExecute(() => CanImportStructure);
            ExportStructureCommand         = new DelegateCommand(ExportStructure).ObservesCanExecute(() => CanExportExecute);

            AddExternalSourceCommand       = new DelegateCommand(AddExternalSource).ObservesCanExecute(() => CanAddExternalSource);
            GenerateBlockFromSourceCommand     = new DelegateCommand(GenerateBlockFromSource).ObservesCanExecute(() => CanGenerateBlockFromSource);
            GenerateSourceFromBlockCommand     = new DelegateCommand(GenerateSourceFromBlock).ObservesCanExecute(() => CanGenerateSourceFromBlock);

            SettingsCommand                = new DelegateCommand(EditSettings);

            AboutCommand                   = new DelegateCommand(ShowAboutInfo);

            TreeViewNavigationCommand      = new DelegateCommand<string>(SetTreeType);

            #endregion // commands

            InitNavigation();
        }

        private void InitServiceProvider()
        {
            _tiaPortalServiceProvider = _moduleProvider.GetService(typeof(ITiaPortalServiceProvider)) as ITiaPortalServiceProvider;
            if (_tiaPortalServiceProvider != null)
            {
                WriteTraceLogProxy(nameof(MenuViewModel) + " - " + nameof(InitServiceProvider));
                _tiaPortalServiceProvider.Initialize(_opennessDemoModel, _traceLogService);
            }
            else
            {
                var version = _settingsService.GetSelectedOpennessApiVersion();
                WriteTraceLogProxy(nameof(MenuViewModel) + " - " + nameof(_settingsService) + " for version - " + version + " not found!");
            }
        }

        #endregion // ctor

        #region properties

        /// <summary>
        /// Indicates whether the base service was loaded
        /// </summary>
        public bool BaseServiceLoaded
        {
            get => _baseServiceLoaded;
            set => SetProperty(ref _baseServiceLoaded, value);
        }

        /// <summary>
        /// Model with meta information of the application context
        /// </summary>
        public IOpennessDemoModel OpennessDemoModel
        {
            get => _opennessDemoModel;
            set => SetProperty(ref _opennessDemoModel, value);
        }

        /// <summary>
        /// Indicates if project library can be update
        /// </summary>
        public bool CanUpdateProjectLibrary
        {
            get => _canUpdateProjectLibrary;
            set => SetProperty(ref _canUpdateProjectLibrary, value);
        }

        /// <summary>
        /// Indicates if editor can be open
        /// </summary>
        public bool CanOpenEditor
        {
            get => _canOpenEditor;
            set
            {
                SetProperty(ref _canOpenEditor, value);
                OpenEditorCommand.RaiseCanExecuteChanged();
            }
        }

        /// <summary>
        /// Indicates if selected object can be compile
        /// </summary>
        public bool CanCompile
        {
            get => _canCompile;
            set
            {
                SetProperty(ref _canCompile, value);
                ExecuteCompilerCommand.RaiseCanExecuteChanged();
            }
        }

        /// <summary>
        /// Indicates if connect command can be execute
        /// </summary>
        public bool CanConnect
        {
            get => _canConnect;
            set
            {
                SetProperty(ref _canConnect, value);
                ConnectTiaPortalCommand.RaiseCanExecuteChanged();
            }
        }

        /// <summary>
        /// Indicates if disconnect command can be execute
        /// </summary>
        public bool CanDisconnect
        {
            get => _canDisconnect;
            set
            {
                SetProperty(ref _canDisconnect, value);
                DisconnectTiaPortalCommand.RaiseCanExecuteChanged();
            }
        }

        /// <summary>
        /// Indicates if an portal is open
        /// </summary>
        public bool TiaPortalOpened
        {
            get => _tiaPortalOpened;
            set
            {
                SetProperty(ref _tiaPortalOpened, value);
                OpenTiaPortalCommand.RaiseCanExecuteChanged();
            }
        }

        /// <summary>
        /// Indicates if an project is open
        /// </summary>
        public bool ProjectOpened
        {
            get => _projectOpened;
            set
            {
                SetProperty(ref _projectOpened, value);
                CreateProjectCommand.RaiseCanExecuteChanged();
                OpenProjectCommand.RaiseCanExecuteChanged();
                RefreshCommand.RaiseCanExecuteChanged();
                SaveProjectCommand.RaiseCanExecuteChanged();
                CloseProjectCommand.RaiseCanExecuteChanged();
            }
        }

        /// <summary>
        /// Indicates if project can be save
        /// </summary>
        public bool CanBeSaveProject
        {
            get => _canBeSaveProject;
            set
            {
                SetProperty(ref _canBeSaveProject, value);
                SaveProjectCommand.RaiseCanExecuteChanged();
            }
        }

        /// <summary>
        /// Indicates if project can be close
        /// </summary>
        public bool CanBeCloseProject
        {
            get => _canBeCloseProject;
            set
            {
                SetProperty(ref _canBeCloseProject, value);
                CloseProjectCommand.RaiseCanExecuteChanged();
            }
        }

        /// <summary>
        /// Indicates if a new object group can be create
        /// </summary>
        public bool CanCreateNewGroup
        {
            get => _canCreateNewGroup;
            set
            {
                SetProperty(ref _canCreateNewGroup, value);
                CreateGroupCommand.RaiseCanExecuteChanged();
            }
        }

        /// <summary>
        /// Indicates if a local session is open
        /// </summary>
        public bool LocalSessionOpened
        {
            get => _localSessionOpened;
            set
            {
                SetProperty(ref _localSessionOpened, value);
                OpenLocalSessionCommand.RaiseCanExecuteChanged();
            }
        }

        /// <summary>
        /// Indicates if local session can be save
        /// </summary>
        public bool CanBeSaveLocalSession
        {
            get => _canBeSaveLocalSession;
            set
            {
                SetProperty(ref _canBeSaveLocalSession, value);
                SaveLocalSessionCommand.RaiseCanExecuteChanged();
            }
        }

        /// <summary>
        /// Indicates if local session can be close
        /// </summary>
        public bool CanBeCloseLocalSession
        {
            get => _canBeCloseLocalSession;
            set
            {
                SetProperty(ref _canBeCloseLocalSession, value);
                CloseLocalSessionCommand.RaiseCanExecuteChanged();
            }
        }

        /// <summary>
        /// Indicates if the logical tree should be display
        /// </summary>
        public bool ShowLogicalTree
        {
            get => _showLogicalTree;
            set => SetProperty(ref _showLogicalTree, value);
        }

        /// <summary>
        /// Indicates if an element can be import
        /// </summary>
        public bool CanImportElement
        {
            get => _canImportElement;
            set
            {
                SetProperty(ref _canImportElement, value);
                ImportElementCommand.RaiseCanExecuteChanged();
            }
        }

        public bool CanImportStructure
        {
            get => _canImportStructure;
            set
            {
                SetProperty(ref _canImportStructure, value);
                ImportStructureCommand.RaiseCanExecuteChanged();
            }
        }

        /// <summary>
        /// Indicates if an element can be export
        /// </summary>
        public bool CanExportExecute
        {
            get => _canExportStructure;
            set
            {
                SetProperty(ref _canExportStructure, value);
                ExportStructureCommand.RaiseCanExecuteChanged();
            }
        }

        /// <summary>
        /// Indicates if an external source can be add
        /// </summary>
        public bool CanAddExternalSource
        {
            get => _canAddExternalSource;
            set
            {
                SetProperty(ref _canAddExternalSource, value);
                AddExternalSourceCommand.RaiseCanExecuteChanged();
            }
        }

        /// <summary>
        /// Indicates if an source can be create form block
        /// </summary>
        public bool CanGenerateBlockFromSource
        {
            get => _canGenerateBlockFromSource;
            set
            {
                SetProperty(ref _canGenerateBlockFromSource, value);
                GenerateBlockFromSourceCommand.RaiseCanExecuteChanged();
            }
        }

        /// <summary>
        /// Indicates if an block can be create form source
        /// </summary>
        public bool CanGenerateSourceFromBlock
        {
            get => _canGenerateSourceFromBlock;
            set
            {
                SetProperty(ref _canGenerateSourceFromBlock, value);
                GenerateSourceFromBlockCommand.RaiseCanExecuteChanged();
            }
        }

        /// <summary>
        /// The current navigation path (target view)
        /// </summary>
        public string NavigationPath
        {
            get => _navigationPath;
            set => SetProperty(ref _navigationPath, value);
        }

        /// <summary>
        /// The selected tree type to be displayed
        /// </summary>
        public string TreeViewType
        {
            get => _treeViewType;
            set => SetProperty(ref _treeViewType, value);
        }

        #endregion // properties

        #region commands

        /// <summary>
        /// Open TIA Portal
        /// </summary>
        public DelegateCommand OpenTiaPortalCommand { get; }
        /// <summary>
        /// Connect TIA Portal
        /// </summary>
        public DelegateCommand ConnectTiaPortalCommand { get; }
        /// <summary>
        /// Disconnect TIA Portal
        /// </summary>
        public DelegateCommand DisconnectTiaPortalCommand { get; }
        /// <summary>
        /// Close TIA Portal
        /// </summary>
        public DelegateCommand CloseTiaPortalCommand { get; }


        /// <summary>
        /// Open local session
        /// </summary>
        public DelegateCommand OpenLocalSessionCommand { get; }
        /// <summary>
        /// Save local session
        /// </summary>
        public DelegateCommand SaveLocalSessionCommand { get; }
        /// <summary>
        /// Close local session
        /// </summary>
        public DelegateCommand CloseLocalSessionCommand { get; }


        /// <summary>
        /// Create project
        /// </summary>
        public DelegateCommand CreateProjectCommand { get; }
        /// <summary>
        /// Open project
        /// </summary>
        public DelegateCommand OpenProjectCommand { get; }
        /// <summary>
        /// Save project
        /// </summary>
        public DelegateCommand SaveProjectCommand { get; }
        /// <summary>
        /// Close project
        /// </summary>
        public DelegateCommand CloseProjectCommand { get; }


        public DelegateCommand ExitCommand { get; }


        /// <summary>
        /// Refresh View
        /// </summary>
        public DelegateCommand RefreshCommand { get; }


        /// <summary>
        /// Create group
        /// </summary>
        public DelegateCommand CreateGroupCommand { get; }


        /// <summary>
        /// Open editor
        /// </summary>
        public DelegateCommand OpenEditorCommand { get; }
        /// <summary>
        /// Open topology view
        /// </summary>
        public DelegateCommand OpenTopologyViewCommand { get; }
        /// <summary>
        /// Open network view
        /// </summary>
        public DelegateCommand OpenNetworkViewCommand { get; }


        /// <summary>
        /// Compile 
        /// </summary>
        public DelegateCommand ExecuteCompilerCommand { get; }


        /// <summary>
        /// CAx import
        /// </summary>
        public DelegateCommand CaxImportCommand { get; }
        /// <summary>
        /// CAx export
        /// </summary>
        public DelegateCommand CaxExportCommand { get; }
        /// <summary>
        /// Import element
        /// </summary>
        public DelegateCommand ImportElementCommand { get; }
        /// <summary>
        /// Import structure
        /// </summary>
        public DelegateCommand ImportStructureCommand { get; }
        /// <summary>
        /// Export structure
        /// </summary>
        public DelegateCommand ExportStructureCommand { get; }


        /// <summary>
        /// Add external source
        /// </summary>
        public DelegateCommand AddExternalSourceCommand { get; }
        /// <summary>
        /// Generate block from source
        /// </summary>
        public DelegateCommand GenerateBlockFromSourceCommand { get; }
        /// <summary>
        /// Generate source form block
        /// </summary>
        public DelegateCommand GenerateSourceFromBlockCommand { get; }


        /// <summary>
        /// Open Settings editor
        /// </summary>
        public DelegateCommand SettingsCommand { get; }


        /// <summary>
        /// Show About info
        /// </summary>
        public DelegateCommand AboutCommand { get; }


        /// <summary>
        /// Set navigation path (logical or physical tree)
        /// </summary>
        public DelegateCommand<string> TreeViewNavigationCommand { get; }

        #endregion // commands

        #region command implementations

        private void OpenTiaPortal()
        {
            WriteTraceLogProxy(nameof(MenuViewModel) + " - " + nameof(OpenTiaPortal) + " -> " + nameof(OpenTopologyEditorEvent));
            _eventAggregator.GetEvent<OpenTiaPortalEvent>().Publish(_opennessDemoNavigationContext);
        }
        private void ConnectTiaPortal()
        {
            WriteTraceLogProxy(nameof(MenuViewModel) + " - " + nameof(ConnectTiaPortal) + " -> " + nameof(ConnectTiaPortalEvent) + " - load logical tree: " + _opennessDemoNavigationContext.ShowLogicalTree + " - navigation path: " + _opennessDemoNavigationContext.NavigationTarget);
            _eventAggregator.GetEvent<ConnectTiaPortalEvent>().Publish(_opennessDemoNavigationContext);
        }
        private void DisconnectTiaPortal()
        {
            _opennessDemoNavigationContext.NavigationTarget = EmptyNavigationTarget;

            WriteTraceLogProxy(nameof(MenuViewModel) + " - " + nameof(DisconnectTiaPortal) + " -> " + nameof(DisconnectTiaPortalEvent));
            _eventAggregator.GetEvent<DisconnectTiaPortalEvent>().Publish(_opennessDemoNavigationContext);
        }
        private void CloseTiaPortal()
        {
            _opennessDemoNavigationContext.NavigationTarget = EmptyNavigationTarget;

            WriteTraceLogProxy(nameof(MenuViewModel) + " - " + nameof(DisconnectTiaPortal) + " -> " + nameof(CloseTiaPortalEvent));
            _eventAggregator.GetEvent<CloseTiaPortalEvent>().Publish(_opennessDemoNavigationContext);
        }

        private void OpenLocalSession()
        {
            SetNavigationContext(NavigationPath, true);

            WriteTraceLogProxy(nameof(MenuViewModel) + " - " + nameof(OpenLocalSession) + " -> " + nameof(OpenLocalSessionEvent));
            _eventAggregator.GetEvent<OpenLocalSessionEvent>().Publish(_opennessDemoNavigationContext);

            WriteTraceLogProxy(nameof(MenuViewModel) + " - " + nameof(OpenLocalSession) + " -> " + nameof(ResetContentEvent));
            _eventAggregator.GetEvent<ResetContentEvent>().Publish();

            WriteTraceLogProxy(nameof(MenuViewModel) + " - " + nameof(OpenLocalSession) + " -> Navigate>" + _opennessDemoNavigationContext.NavigationTarget);
            Navigate(_opennessDemoNavigationContext.NavigationTarget);
        }

        private bool ExpectedVersionsAvailable()
        {
            try
            {
                WriteTraceLogProxy(nameof(MenuViewModel) + " - " + nameof(CanOpenLocalSession));

                Version engineeringVersion = Version.Parse(_settingsService.GetSelectedEngineeringVersion());
                Version expectedEngineeringVersion = Version.Parse("17.0");
                Version opennessApiVersion = Version.Parse(_settingsService.GetSelectedOpennessApiVersion());
                Version expectedOpennessApiVersion = Version.Parse("17.0");

                return (engineeringVersion == expectedEngineeringVersion && opennessApiVersion == expectedOpennessApiVersion);
            }
            catch (Exception e)
            {
                var methodBase = MethodBase.GetCurrentMethod();
                WriteTraceLogProxy(methodBase.Name + " - " + e.Message);
                return false;
            }
        }

        private void SaveLocalSession()
        {
            SetNavigationContext(NavigationPath, true);

            WriteTraceLogProxy(nameof(MenuViewModel) + " - " + nameof(SaveLocalSession) + " -> " + nameof(SaveLocalSessionEvent));
            _eventAggregator.GetEvent<SaveLocalSessionEvent>().Publish(_opennessDemoNavigationContext);
        }

        private void CloseLocalSession()
        {
            WriteTraceLogProxy(nameof(MenuViewModel) + " - " + nameof(CloseLocalSession) + " -> " + nameof(CloseLocalSessionEvent));
            _eventAggregator.GetEvent<CloseLocalSessionEvent>().Publish(_opennessDemoNavigationContext);

            WriteTraceLogProxy(nameof(MenuViewModel) + " - " + nameof(CloseLocalSession) + " -> Navigate>" + _opennessDemoNavigationContext.NavigationTarget);
            Navigate(_opennessDemoNavigationContext.NavigationTarget);
        }

        private void CreateProject()
        {
            SetNavigationContext(NavigationPath, false);

            WriteTraceLogProxy(nameof(MenuViewModel) + " - " + nameof(CreateProject) + " -> " + nameof(CreateNewProjectEvent));
            _eventAggregator.GetEvent<CreateNewProjectEvent>().Publish(_opennessDemoNavigationContext);
        }
        private void OpenProject()
        {
            SetNavigationContext(NavigationPath, false);

            WriteTraceLogProxy(nameof(MenuViewModel) + " - " + nameof(OpenProject) + " -> " + nameof(OpenProjectEvent));
            _eventAggregator.GetEvent<OpenProjectEvent>().Publish(_opennessDemoNavigationContext);
        }
        private void SaveProject()
        {
            SetNavigationContext(NavigationPath, false);

            WriteTraceLogProxy(nameof(MenuViewModel) + " - " + nameof(SaveProject) + " -> " + nameof(SaveProjectEvent));
            _eventAggregator.GetEvent<SaveProjectEvent>().Publish(_opennessDemoNavigationContext);
        }
        private void CloseProject()
        {
            WriteTraceLogProxy(nameof(MenuViewModel) + " - " + nameof(CloseProject) + " -> " + nameof(CloseProjectEvent));
            _eventAggregator.GetEvent<CloseProjectEvent>().Publish(_opennessDemoNavigationContext);
        }


        private void DoExit()
        {
            _eventAggregator.GetEvent<ExitEvent>().Publish();
        }


        private void Refresh()
        {
            WriteTraceLogProxy(nameof(MenuViewModel) + " - " + nameof(Refresh) + " -> " + nameof(RefreshEvent));
            _eventAggregator.GetEvent<RefreshEvent>().Publish(_opennessDemoNavigationContext);
        }

        private void CreateNewGroup()
        {
            WriteTraceLogProxy(nameof(MenuViewModel) + " - " + nameof(CreateNewGroup) + " -> " + nameof(ProjectCreateNewGroupEvent));
            _eventAggregator.GetEvent<ProjectCreateNewGroupEvent>().Publish(_opennessDemoNavigationContext);
        }

        private void OpenEditor()
        {
            WriteTraceLogProxy(nameof(MenuViewModel) + " - " + nameof(OpenEditor) + " -> " + nameof(OpenEditorEvent));
            _eventAggregator.GetEvent<OpenEditorEvent>().Publish(_opennessDemoNavigationContext);
        }
        private void OpenTopologyView()
        {
            WriteTraceLogProxy(nameof(MenuViewModel) + " - " + nameof(OpenTopologyView) + " -> " + nameof(OpenTopologyEditorEvent));
            _eventAggregator.GetEvent<OpenTopologyEditorEvent>().Publish(_opennessDemoNavigationContext);
        }
        private void OpenNetworkView()
        {
            WriteTraceLogProxy(nameof(MenuViewModel) + " - " + nameof(OpenNetworkView) + " -> " + nameof(OpenNetworkEditorEvent));
            _eventAggregator.GetEvent<OpenNetworkEditorEvent>().Publish(_opennessDemoNavigationContext);
        }

        private void ExecuteCompiler()
        {
            WriteTraceLogProxy(nameof(MenuViewModel) + " - " + nameof(ExecuteCompiler) + " -> " + nameof(CompileEvent));
            _eventAggregator.GetEvent<CompileEvent>().Publish(_opennessDemoNavigationContext); //DisplayLogicalTreeView());
        }

        private void CaxImport()
        {
            WriteTraceLogProxy(nameof(MenuViewModel) + " - " + nameof(CaxImport) + " -> " + nameof(CaxImportEvent));
            _eventAggregator.GetEvent<CaxImportEvent>().Publish(_opennessDemoNavigationContext);
        }
        private void CaxExport()
        {
            WriteTraceLogProxy(nameof(MenuViewModel) + " - " + nameof(CaxExport) + " -> " + nameof(CaxExportEvent));
            _eventAggregator.GetEvent<CaxExportEvent>().Publish(_opennessDemoNavigationContext);
        }
        private void ImportElement()
        {
            WriteTraceLogProxy(nameof(MenuViewModel) + " - " + nameof(ImportElement) + " -> " + nameof(ImportElementEvent));
            _eventAggregator.GetEvent<ImportElementEvent>().Publish(_opennessDemoNavigationContext);
        }
        private void ImportStructure()
        {
            WriteTraceLogProxy(nameof(MenuViewModel) + " - " + nameof(ImportStructure) + " -> " + nameof(ImportStructureEvent));
            _eventAggregator.GetEvent<ImportStructureEvent>().Publish(_opennessDemoNavigationContext);
        }
        private void ExportStructure()
        {
            WriteTraceLogProxy(nameof(MenuViewModel) + " - " + nameof(ExportStructure) + " -> " + nameof(ExportStructureEvent));
            _eventAggregator.GetEvent<ExportStructureEvent>().Publish(_opennessDemoNavigationContext);
        }

        private void AddExternalSource()
        {
            WriteTraceLogProxy(nameof(MenuViewModel) + " - " + nameof(AddExternalSource) + " -> " + nameof(AddExternalSourceEvent));
            _eventAggregator.GetEvent<AddExternalSourceEvent>().Publish(_opennessDemoNavigationContext);
        }
        private void GenerateBlockFromSource()
        {
            WriteTraceLogProxy(nameof(MenuViewModel) + " - " + nameof(GenerateBlockFromSource) + " -> " + nameof(GenerateBlockFromSourceEvent));
            _eventAggregator.GetEvent<GenerateBlockFromSourceEvent>().Publish(_opennessDemoNavigationContext);
        }
        private void GenerateSourceFromBlock()
        {
            WriteTraceLogProxy(nameof(MenuViewModel) + " - " + nameof(GenerateSourceFromBlock) + " -> " + nameof(GenerateSourceFromBlockEvent));
            _eventAggregator.GetEvent<GenerateSourceFromBlockEvent>().Publish(_opennessDemoNavigationContext);
        }

        private void EditSettings()
        {
            WriteTraceLogProxy(nameof(MenuViewModel) + " - " + nameof(EditSettings) + " -> " + nameof(EditSettingsEvent));
            _eventAggregator.GetEvent<EditSettingsEvent>().Publish();
        }

        private void ShowAboutInfo()
        {
            WriteTraceLogProxy(nameof(MenuViewModel) + " - " + nameof(ShowAboutInfo));

            var aboutInfoView = _containerProvider.Resolve<AboutInfoView>();
            aboutInfoView.ShowDialog();
        }

        private void SetTreeType(string treeViewType)
        {
            TreeViewType = treeViewType;
            ShowLogicalTree = TreeViewType == NavigationNames.DefaultTreeNavigation;

            SetNavigationContext(TreeViewType, _opennessDemoNavigationContext.IsLocalSession);
        }

        private void SetNavigationContext(string navigationPath, bool localSession)
        {
            NavigationPath = TreeViewType;

            if (localSession)
            {
                NavigationPath = "Multiuser" + TreeViewType;
            }

            _opennessDemoNavigationContext.NavigationTarget = NavigationPath;
            _opennessDemoNavigationContext.ShowLogicalTree  = DisplayLogicalTreeView();
            _opennessDemoNavigationContext.IsLocalSession   = localSession;

            OpennessDemoModel.DisplayLogicalTreeView        = DisplayLogicalTreeView();

            WriteTraceLogProxy(nameof(MenuViewModel) + " - " + nameof(SetNavigationContext));
            _eventAggregator.GetEvent<SetNavigationPathEvent>().Publish(_opennessDemoNavigationContext);

            Navigate(NavigationPath);
        }

        #endregion // command implementations

        #region methods

        private void InitEnvironment(bool baseServiceLoaded)
        {
            BaseServiceLoaded = baseServiceLoaded;
        }

        private void SelectedSystemLibraryChanged(TreeViewItem treeViewItem)
        {
            CanUpdateProjectLibrary = (treeViewItem != null);
        }

        private void Navigate(string navigationPath)
        {
            if (OpennessDemoModel != null)
            {
                WriteTraceLogProxy(nameof(MenuViewModel) + " - " + nameof(Navigate) + " -> local session " + OpennessDemoModel.LocalSessionOpened);
                var navigationParameters = new NavigationParameters();
                navigationParameters.Add("ProcessId", OpennessDemoModel.CurrentProcessId.ToString());
                navigationParameters.Add("TreeTypeName", _opennessDemoNavigationContext.NavigationTarget);

                WriteTraceLogProxy(nameof(MenuViewModel) + " - " + nameof(Navigate) + " -> " + navigationPath);
                _regionManager.RequestNavigate(RegionNames.ProjectTreeRegion, _opennessDemoNavigationContext.NavigationTarget, navigationParameters);
            }
        }

        private void SelectedProjectItemChanged(object obj)
        {
            WriteTraceLogProxy(nameof(MenuViewModel) + " - " + nameof(SelectedProjectItemChanged));

            CanOpenEditor = false;

            CanOpenEditor = CanOpenEditor || OpennessDemoModel.SelectedTreeType == TreeTypeInformation.IsDevice;
            CanOpenEditor = CanOpenEditor || OpennessDemoModel.SelectedTreeType == TreeTypeInformation.IsProgramBlock;
            CanOpenEditor = CanOpenEditor || OpennessDemoModel.SelectedTreeType == TreeTypeInformation.IsPlcDataType;
            CanOpenEditor = CanOpenEditor || OpennessDemoModel.SelectedTreeType == TreeTypeInformation.IsPlcSystemType;
            CanOpenEditor = CanOpenEditor || OpennessDemoModel.SelectedTreeType == TreeTypeInformation.IsPlcUserType;
            CanOpenEditor = CanOpenEditor || OpennessDemoModel.SelectedTreeType == TreeTypeInformation.IsType;
            CanOpenEditor = CanOpenEditor || OpennessDemoModel.SelectedTreeType == TreeTypeInformation.IsTechnological;
            CanOpenEditor = CanOpenEditor || OpennessDemoModel.SelectedTreeType == TreeTypeInformation.IsWatchAndForceTable;
            CanOpenEditor = CanOpenEditor || OpennessDemoModel.SelectedTreeType == TreeTypeInformation.IsTagTable;

            CanCompile = false;

            CanCompile = OpennessDemoModel.IsCompilable;
        }

        private bool CanOpenTiaPortal()
        {
            WriteTraceLogProxy(nameof(MenuViewModel) + " - " + nameof(CanOpenTiaPortal));

            return !TiaPortalOpened;
        }

        private bool CanOpenProject()
        {
            WriteTraceLogProxy(nameof(MenuViewModel) + " - " + nameof(CanOpenProject));

            return !ProjectOpened && !OpennessDemoModel.LocalSessionOpened;
        }

        private bool CanSaveProject()
        {
            return OpennessDemoModel.ProjectModel.ProjectOpened && !OpennessDemoModel.LocalSessionOpened;
        }

        private bool CanCloseProject()
        {
            return OpennessDemoModel.ProjectModel.ProjectOpened && !OpennessDemoModel.LocalSessionOpened;
        }


        private bool CanOpenLocalSession()
        {
            return !OpennessDemoModel.LocalSessionOpened && !OpennessDemoModel.ProjectModel.ProjectOpened && ExpectedVersionsAvailable();
        }

        private bool CanSaveLocalSession()
        {
            return OpennessDemoModel.LocalSessionOpened;
        }

        private bool CanCloseLocalSession()
        {
            return OpennessDemoModel.LocalSessionOpened;
        }

        private void UpdateViewNavigation(bool localSession)
        {
            WriteTraceLogProxy(nameof(MenuViewModel) + " - " + nameof(UpdateViewNavigation));

            SetNavigationContext(NavigationPath, localSession);
        }

        private void InitNavigation()
        {
            WriteTraceLogProxy(nameof(MenuViewModel) + " - " + nameof(InitNavigation));

            TiaPortalOpened = false;
            _navigationPath = NavigationNames.DefaultTreeNavigation;
            ShowLogicalTree = NavigationPath == NavigationNames.DefaultTreeNavigation;
        }

        private bool DisplayLogicalTreeView()
        {
            WriteTraceLogProxy(nameof(MenuViewModel) + " - " + nameof(DisplayLogicalTreeView));

            return TreeViewType == NavigationNames.DefaultTreeNavigation;
        }

        private void GetTiaPortalState()
        {
            WriteTraceLogProxy(nameof(MenuViewModel) + " - " + nameof(GetTiaPortalState));


            TiaPortalOpened        = OpennessDemoModel.PortalOpened;
            ProjectOpened          = OpennessDemoModel.ProjectModel.ProjectOpened;

            CanBeSaveProject       = OpennessDemoModel.ProjectModel.ProjectOpened && !OpennessDemoModel.LocalSessionOpened;
            CanBeCloseProject      = OpennessDemoModel.ProjectModel.ProjectOpened && !OpennessDemoModel.LocalSessionOpened;
            LocalSessionOpened     = OpennessDemoModel.LocalSessionOpened;

            CanBeSaveLocalSession  = OpennessDemoModel.LocalSessionOpened;
            CanBeCloseLocalSession = OpennessDemoModel.LocalSessionOpened;

            OpennessDemoModel.GetTiaPortalProcesses();
            OpennessDemoModel.PortalAvailable = (OpennessDemoModel.CurrentProcessId != OpennessDemoModel.GetSelectedProcessId());
            ConnectTiaPortalCommand.RaiseCanExecuteChanged();

            CanCreateNewGroup = OpennessDemoModel.SelectedTreeType == TreeTypeInformation.IsTypeGroup ||
                                OpennessDemoModel.SelectedTreeType == TreeTypeInformation.IsDeviceUserGroup ||
                                OpennessDemoModel.SelectedTreeType == TreeTypeInformation.IsProgramBlockGroup ||
                                OpennessDemoModel.SelectedTreeType == TreeTypeInformation.IsTechnologicalGroup ||
                                OpennessDemoModel.SelectedTreeType == TreeTypeInformation.IsExternalSourceGroup ||
                                OpennessDemoModel.SelectedTreeType == TreeTypeInformation.IsTagTableGroup ||
                                OpennessDemoModel.SelectedTreeType == TreeTypeInformation.IsPlcDataTypeGroup ||
                                OpennessDemoModel.SelectedTreeType == TreeTypeInformation.IsPlcTypeUserGroup ||
                                OpennessDemoModel.SelectedTreeType == TreeTypeInformation.IsWatchAndForceTableGroup;

            CanExportExecute   = OpennessDemoModel.CanExportExecute;
            CanImportElement   = OpennessDemoModel.CanImportElement;
            CanImportStructure = OpennessDemoModel.CanImportStructure;

            CanAddExternalSource       = OpennessDemoModel.CanAddExternalSource;
            CanGenerateBlockFromSource = OpennessDemoModel.CanGenerateBlockFromSource;
            CanGenerateSourceFromBlock = OpennessDemoModel.CanGenerateSourceFromBlock;
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
