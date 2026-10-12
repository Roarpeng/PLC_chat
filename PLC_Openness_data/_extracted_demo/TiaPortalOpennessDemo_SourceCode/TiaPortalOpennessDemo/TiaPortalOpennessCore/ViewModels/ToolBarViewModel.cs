using Prism.Commands;
using Prism.Events;
using Prism.Mvvm;
using System.Windows;
using TiaPortalOpennessAdapterContracts;
using TiaPortalOpennessCore.Events.Global;
using TiaPortalOpennessCore.Events.Project;
using TiaPortalOpennessCore.Events.Session;
using TiaPortalOpennessCore.Events.TiaPortal;
using TiaPortalOpennessInfrastructure.Constants;
using TiaPortalOpennessInfrastructure.Contracts;

namespace TiaPortalOpennessCore.ViewModels
{
    /// <summary>
    /// The ToolBarViewModel definition of commands and the implementation for interaction with user
    /// </summary>
    public class ToolBarViewModel : BindableBase
    {
        #region fields

        private readonly IEventAggregator      _eventAggregator;
        private readonly ITraceLogService      _traceLogService;

        private IOpennessDemoModel             _opennessDemoModel;
        private IOpennessDemoNavigationContext _opennessDemoNavigationContext;

        private bool                           _baseServiceLoaded;
        private bool                           _canImportElement;
        private bool                           _canExportExecute;
        private bool                           _showLogicalTree;
        private bool                           _projectOpened;
        private bool                           _canOpenProject;
        private bool                           _canCompile;
        private bool                           _canSaveProject;
        private bool                           _canSaveLocalSession;

        private string                         _navigationPath;

        private const string EmptyNavigationTarget = "EmptyProjectTreeView";

        #endregion // fields

        #region ctor

        /// <summary>
        /// default constructor
        /// </summary>
        /// <param name="eventAggregator"></param>
        /// <param name="traceLogService"></param>
        /// <param name="opennessDemoModel"></param>
        /// <param name="opennessDemoNavigationContext"></param>
        public ToolBarViewModel(IEventAggregator eventAggregator, ITraceLogService traceLogService, IOpennessDemoModel opennessDemoModel, IOpennessDemoNavigationContext opennessDemoNavigationContext)
        {
            _eventAggregator               = eventAggregator;
            _traceLogService               = traceLogService;
            _opennessDemoModel             = opennessDemoModel;

            _opennessDemoNavigationContext = opennessDemoNavigationContext;

            _eventAggregator.GetEvent<InitEnvironmentEvent>().Subscribe(InitEnvironment);

            _eventAggregator.GetEvent<SelectedProjectItemChangedEvent>().Subscribe(SelectedProjectItemChanged);

            _eventAggregator.GetEvent<SetNavigationPathEvent>().Subscribe(SetNavigationPath);
            _eventAggregator.GetEvent<TiaPortalStateEvent>().Subscribe(GetTiaPortalState);

            _eventAggregator.GetEvent<LocalSessionOpenedEvent>().Subscribe(GetTiaPortalState);
            _eventAggregator.GetEvent<TiaPortalDisconnectedEvent>().Subscribe(GetTiaPortalState);
            _eventAggregator.GetEvent<LocalSessionSavedEvent>().Subscribe(GetTiaPortalState);
            _eventAggregator.GetEvent<LocalSessionClosedEvent>().Subscribe(GetTiaPortalState);
            _eventAggregator.GetEvent<ProjectClosedEvent>().Subscribe(GetTiaPortalState);
            _eventAggregator.GetEvent<SelectedProcessIdChangedEvent>().Subscribe(GetTiaPortalState);
            _eventAggregator.GetEvent<TiaPortalClosedEvent>().Subscribe(GetTiaPortalState);
            _eventAggregator.GetEvent<TiaPortalConnectedEvent>().Subscribe(GetTiaPortalState);
            _eventAggregator.GetEvent<TiaPortalDisconnectedEvent>().Subscribe(GetTiaPortalState);

            OpenProjectCommand      = new DelegateCommand(OpenProject).ObservesCanExecute(() => CanOpenProject);
            RefreshCommand          = new DelegateCommand(Refresh);
            SaveProjectCommand      = new DelegateCommand(SaveProject).ObservesCanExecute(() => CanSaveProject);
            SaveLocalSessionCommand = new DelegateCommand(SaveLocalSession).ObservesCanExecute(() => CanSaveLocalSession);

            ExecuteCompilerCommand  = new DelegateCommand(ExecuteCompiler).ObservesCanExecute(() => CanCompile);
            ImportElementCommand    = new DelegateCommand(ImportElement).ObservesCanExecute(() => CanImportElement);
            ExportStructureCommand  = new DelegateCommand(ExportStructure).ObservesCanExecute(() => CanExportExecute);

            InitState();
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
        /// Indicates if an project is open
        /// </summary>
        public bool ProjectOpened
        {
            get => _projectOpened;
            set
            {
                SetProperty(ref _projectOpened, value);
                OpenProjectCommand.RaiseCanExecuteChanged();
                RefreshCommand.RaiseCanExecuteChanged();
                SaveProjectCommand.RaiseCanExecuteChanged();
            }
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

        /// <summary>
        /// Indicates if an element can be export
        /// </summary>
        public bool CanExportExecute
        {
            get => _canExportExecute;
            set
            {
                SetProperty(ref _canExportExecute, value);
                ExportStructureCommand.RaiseCanExecuteChanged();
            }
        }

        /// <summary>
        /// Indicates if project can be open
        /// </summary>
        public bool CanOpenProject
        {
            get => _canOpenProject;
            set
            {
                SetProperty(ref _canOpenProject, value);
                OpenProjectCommand.RaiseCanExecuteChanged();
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
        /// Indicates if project can be save
        /// </summary>
        public bool CanSaveProject
        {
            get => _canSaveProject;
            set
            {
                SetProperty(ref _canSaveProject, value);
                SaveProjectCommand.RaiseCanExecuteChanged();
            }
        }

        /// <summary>
        /// Indicates if local session can be save
        /// </summary>
        public bool CanSaveLocalSession
        {
            get => _canSaveLocalSession;
            set
            {
                SetProperty(ref _canSaveLocalSession, value);
                SaveLocalSessionCommand.RaiseCanExecuteChanged();
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
        /// Indicates if the logical tree should be display
        /// </summary>
        public bool ShowLogicalTree
        {
            get => _showLogicalTree;
            set => SetProperty(ref _showLogicalTree, value);
        }

        #endregion // properties

        #region commands

        /// <summary>
        /// Open project
        /// </summary>
        public DelegateCommand OpenProjectCommand { get; }
        /// <summary>
        /// Refresh View
        /// </summary>
        public DelegateCommand RefreshCommand { get; }
        /// <summary>
        /// Save project
        /// </summary>
        public DelegateCommand SaveProjectCommand { get; }
        /// <summary>
        /// Save local session
        /// </summary>
        public DelegateCommand SaveLocalSessionCommand { get; }
        /// <summary>
        /// Compile 
        /// </summary>
        public DelegateCommand ExecuteCompilerCommand { get; }
        /// <summary>
        /// Import element
        /// </summary>
        public DelegateCommand ImportElementCommand { get; }
        /// <summary>
        /// Export structure
        /// </summary>
        public DelegateCommand ExportStructureCommand { get; }

        #endregion // commands

        #region command implementations

        private void OpenProject()
        {
            WriteTraceLogProxy(nameof(ToolBarViewModel) + " - " + nameof(OpenProject) + " -> " + nameof(OpenProjectEvent));
            _eventAggregator.GetEvent<OpenProjectEvent>().Publish(_opennessDemoNavigationContext);
        }

        private void Refresh()
        {
            WriteTraceLogProxy(nameof(ToolBarViewModel) + " - " + nameof(Refresh) + " -> " + nameof(RefreshEvent));
            _eventAggregator.GetEvent<RefreshEvent>().Publish(_opennessDemoNavigationContext);
        }

        private void SaveProject()
        {
            WriteTraceLogProxy(nameof(ToolBarViewModel) + " - " + nameof(SaveProject) + " -> " + nameof(SaveProjectEvent));
            _eventAggregator.GetEvent<SaveProjectEvent>().Publish(_opennessDemoNavigationContext);
        }

        private void SaveLocalSession()
        {
            WriteTraceLogProxy(nameof(ToolBarViewModel) + " - " + nameof(SaveLocalSession) + " -> " + nameof(SaveLocalSessionEvent));
            _eventAggregator.GetEvent<SaveLocalSessionEvent>().Publish(_opennessDemoNavigationContext);
        }

        private void ExecuteCompiler()
        {
            WriteTraceLogProxy(nameof(ToolBarViewModel) + " - " + nameof(ExecuteCompiler) + " -> " + nameof(CompileEvent));
            _eventAggregator.GetEvent<CompileEvent>().Publish(_opennessDemoNavigationContext);
        }

        private void ImportElement()
        {
            WriteTraceLogProxy(nameof(ToolBarViewModel) + " - " + nameof(ImportElement) + " -> " + nameof(ImportElementEvent));
            _eventAggregator.GetEvent<ImportElementEvent>().Publish(_opennessDemoNavigationContext);
        }

        private void ExportStructure()
        {
            WriteTraceLogProxy(nameof(ToolBarViewModel) + " - " + nameof(ExportStructure) + " -> " + nameof(ExportStructureEvent));
            _eventAggregator.GetEvent<ExportStructureEvent>().Publish(_opennessDemoNavigationContext);
        }

        #endregion // command implementations

        #region methods

        private void InitEnvironment(bool baseServiceLoaded)
        {
            BaseServiceLoaded = baseServiceLoaded;
        }

        private void SetNavigationPath(IOpennessDemoNavigationContext navigationContext)
        {
            _opennessDemoNavigationContext = navigationContext;
            NavigationPath                 = _opennessDemoNavigationContext.NavigationTarget;
            ShowLogicalTree                = _opennessDemoNavigationContext.ShowLogicalTree;
        }

        private void GetTiaPortalState()
        {
            WriteTraceLogProxy(nameof(ToolBarViewModel) + " - " + nameof(GetTiaPortalState) + " -> project: " + OpennessDemoModel.ProjectModel.ProjectOpened + " -> session: " + OpennessDemoModel.LocalSessionOpened);

            CanCompile          = OpennessDemoModel.IsCompilable;
            ProjectOpened       = OpennessDemoModel.ProjectModel.ProjectOpened;
            CanOpenProject      = !ProjectOpened;
            CanSaveProject      = OpennessDemoModel.ProjectModel.ProjectOpened && !OpennessDemoModel.LocalSessionOpened;
            CanSaveLocalSession = OpennessDemoModel.LocalSessionOpened;
            CanExportExecute    = OpennessDemoModel.CanExportExecute;
            CanImportElement    = OpennessDemoModel.CanImportElement;
        }

        private bool DisplayLogicalTreeView()
        {
            WriteTraceLogProxy(nameof(ToolBarViewModel) + " - " + nameof(DisplayLogicalTreeView));

            return NavigationPath == NavigationNames.DefaultTreeNavigation;
        }

        private void InitNavigation()
        {
            WriteTraceLogProxy(nameof(ToolBarViewModel) + " - " + nameof(InitNavigation));

            _navigationPath = NavigationNames.DefaultTreeNavigation;
            ShowLogicalTree = NavigationPath == NavigationNames.DefaultTreeNavigation;
        }

        private void InitState()
        {
            ProjectOpened    = false;
            CanCompile       = false;
            CanImportElement = false;
            CanExportExecute = false;
        }

        private void SelectedProjectItemChanged(object obj)
        {
            WriteTraceLogProxy(nameof(ToolBarViewModel) + " - " + nameof(SelectedProjectItemChanged));

            CanCompile = OpennessDemoModel.IsCompilable;
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
