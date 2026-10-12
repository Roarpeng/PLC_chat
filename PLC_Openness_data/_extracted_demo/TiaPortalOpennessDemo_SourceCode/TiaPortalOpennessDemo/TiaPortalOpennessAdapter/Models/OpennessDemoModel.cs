using System;
using System.Collections.Generic;
using System.Linq;
using TiaPortalOpennessAdapterBase.Enums;
using TiaPortalOpennessAdapterBase.Models;
using TiaPortalOpennessAdapterContracts;

namespace TiaPortalOpennessAdapter.Models
{
    /// <summary>
    /// Definition of meta data
    /// </summary>
    public class OpennessDemoModel : ObservableObject, IOpennessDemoModel
    {
        #region fields

        private ITiaPortalServiceProvider _tiaPortalServiceProvider;

        private IList<string> _tiaPortalProcesses;
        private IList<string> _projectInformation;

        private int _currentProcessId;
        private int _selectedProcessIndex;
        private string _selectedProcessId;

        private int _countLocalSessions;
        private int _countProjectServer;
        private int _countProjects;
        private int _countGlobalLibraries;
        private int _countSettingsFolders;

        private bool _tiaPortalDisposed;
        private bool _portalOpened;
        private bool _canConnect;
        private bool _localSessionOpened;
        private bool _displayLogicalTreeView;
        private bool _isCompilable;
        private bool _canImportElement;
        private bool _canImportStructure;
        private bool _canExportExecute;
        private bool _canAddExternalSource;
        private bool _canGenerateBlockFromSource;
        private bool _canGenerateSourceFromBlock;
        private bool _portalAvailable;

        private TreeTypeInformation _selectedTreeType;
        private TiaPortalStartMode _tiaPortalStartMode;
        private ProjectModel _projectModel;

        #endregion fields

        #region ctor

        /// <summary>
        /// default constructor
        /// </summary>
        public OpennessDemoModel()
        {
            _projectModel = new ProjectModel();

            GetTiaPortalProcesses();
        }

        #endregion // ctor

        #region properties

        /// <summary>
        /// The type of the selected tree item
        /// </summary>
        public TreeTypeInformation SelectedTreeType
        {
            get => _selectedTreeType;
            set => SetProperty(ref _selectedTreeType, value);
        }

        /// <summary>
        /// The selected start mode for TIA Portal
        /// </summary>
        public TiaPortalStartMode TiaPortalStartMode
        {
            get => _tiaPortalStartMode;
            set => SetProperty(ref _tiaPortalStartMode, value);
        }

        /// <summary>
        /// TIA Portal service provider instance to be used
        /// </summary>
        public ITiaPortalServiceProvider TiaPortalServiceProvider
        {
            get => _tiaPortalServiceProvider;
            set
            {
                SetProperty(ref _tiaPortalServiceProvider, value);
                GetTiaPortalProcesses();
            }
        }

        /// <summary>
        /// local session counter
        /// </summary>
        public int CountLocalSessions
        {
            get => _countLocalSessions;
            set => SetProperty(ref _countLocalSessions, value);
        }

        /// <summary>
        /// project server count
        /// </summary>
        public int CountProjectServer
        {
            get => _countProjectServer;
            set => SetProperty(ref _countProjectServer, value);
        }

        /// <summary>
        /// project counter
        /// </summary>
        public int CountProjects
        {
            get => _countProjects;
            set => SetProperty(ref _countProjects, value);
        }

        /// <summary>
        /// global library counter
        /// </summary>
        public int CountGlobalLibraries
        {
            get => _countGlobalLibraries;
            set => SetProperty(ref _countGlobalLibraries, value);
        }

        /// <summary>
        /// settings folder counter
        /// </summary>
        public int CountSettingsFolders
        {
            get => _countSettingsFolders;
            set => SetProperty(ref _countSettingsFolders, value);
        }

        /// <summary>
        /// Indicates if TIA Portal is disposed
        /// </summary>
        public bool TiaPortalDisposed
        {
            get => _tiaPortalDisposed;
            set => SetProperty(ref _tiaPortalDisposed, value);
        }

        /// <summary>
        /// Indicates if TIA Portal is open
        /// </summary>
        public bool PortalOpened
        {
            get => _portalOpened;
            set => SetProperty(ref _portalOpened, value);
        }

        /// <summary>
        /// Indicates if TIA Portal can be connect
        /// </summary>
        public bool CanConnect
        {
            get => _canConnect;
            set => SetProperty(ref _canConnect, value);
        }

        /// <summary>
        /// Indicates if local session is open
        /// </summary>
        public bool LocalSessionOpened
        {
            get => _localSessionOpened;
            set => SetProperty(ref _localSessionOpened, value);
        }

        /// <summary>
        /// Indicates if logical tree is displayed
        /// </summary>
        public bool DisplayLogicalTreeView
        {
            get => _displayLogicalTreeView;
            set => SetProperty(ref _displayLogicalTreeView, value);
        }

        /// <summary>
        /// Indicates if selected tree item can be compile
        /// </summary>
        public bool IsCompilable
        {
            get => _isCompilable;
            set => SetProperty(ref _isCompilable, value);
        }

        /// <summary>
        /// Indicates if element can be import
        /// </summary>
        public bool CanImportElement
        {
            get => _canImportElement;
            set => SetProperty(ref _canImportElement, value);
        }

        /// <summary>
        /// Indicates if folder structure can be import
        /// </summary>
        public bool CanImportStructure
        {
            get => _canImportStructure;
            set => SetProperty(ref _canImportStructure, value);
        }

        /// <summary>
        /// Indicates if an element can be export
        /// </summary>
        public bool CanExportExecute
        {
            get => _canExportExecute;
            set => SetProperty(ref _canExportExecute, value);
        }

        /// <summary>
        /// Indicates if an external source can be add to an element
        /// </summary>
        public bool CanAddExternalSource
        {
            get => _canAddExternalSource;
            set => SetProperty(ref _canAddExternalSource, value);
        }

        /// <summary>
        /// Indicates if an block can be generate from selected source
        /// </summary>
        public bool CanGenerateBlockFromSource
        {
            get => _canGenerateBlockFromSource;
            set => SetProperty(ref _canGenerateBlockFromSource, value);
        }

        /// <summary>
        /// Indicates if an source can be generate from selected block
        /// </summary>
        public bool CanGenerateSourceFromBlock
        {
            get => _canGenerateSourceFromBlock;
            set => SetProperty(ref _canGenerateSourceFromBlock, value);
        }

        /// <summary>
        /// Indicates if an portal instance (process) is available an can be connect
        /// </summary>
        public bool PortalAvailable
        {
            get => _portalAvailable;
            set => SetProperty(ref _portalAvailable, value);
        }

        /// <summary>
        /// The current process id
        /// </summary>
        public int CurrentProcessId
        {
            get => _currentProcessId;
            set => SetProperty(ref _currentProcessId, value);
        }

        /// <summary>
        /// Selected index from process list
        /// </summary>
        public int SelectedProcessIndex
        {
            get => _selectedProcessIndex;
            set => SetProperty(ref _selectedProcessIndex, value);
        }

        /// <summary>
        /// List of available processes
        /// </summary>
        public IList<string> TiaPortalProcesses
        {
            get => _tiaPortalProcesses;
            set => SetProperty(ref _tiaPortalProcesses, value);
        }

        /// <summary>
        /// List of meta data to processes like id, start mode, project name and single or multi user
        /// </summary>
        public IList<string> ProjectInformation
        {
            get => _projectInformation;
            set => SetProperty(ref _projectInformation, value);
        }

        /// <summary>
        /// Selected process id
        /// </summary>
        public string SelectedProcessId
        {
            get => _selectedProcessId;
            set => SetProperty(ref _selectedProcessId, value);
        }

        /// <summary>
        /// Project meta data
        /// </summary>
        public ProjectModel ProjectModel
        {
            get => _projectModel;
            set => SetProperty(ref _projectModel, value);
        }

        #endregion // properties

        #region methods

        /// <summary>
        /// Retrieve all available processes with meta data
        /// </summary>
        public void GetTiaPortalProcesses()
        {
            if (TiaPortalServiceProvider != null)
            {
                TiaPortalProcesses = TiaPortalServiceProvider.GetTiaPortalProcesses();
                ProjectInformation = TiaPortalServiceProvider.GetTiaPortalProjectInformation();
                CheckPortalAvailability();
            }
        }

        private void CheckPortalAvailability()
        {
            PortalAvailable = TiaPortalProcesses?.Count > 0;

            PortalAvailable = (TiaPortalProcesses?.Count >= 1 && Convert.ToInt32(TiaPortalProcesses.First().Split(' ')[1]) != CurrentProcessId);

            SelectedProcessId = (string.IsNullOrEmpty(SelectedProcessId) && PortalAvailable)
                ? TiaPortalProcesses?.First()
                : SelectedProcessId;
        }

        /// <summary>
        /// Get process id from meta string
        /// </summary>
        /// <returns>process id</returns>
        public int GetSelectedProcessId()
        {
            var id = -1;
            if (SelectedProcessId != null && SelectedProcessIndex > -1)
            {
                id = Convert.ToInt32(SelectedProcessId.Split(' ')[1]);
            }
            return id;
        }

        /// <summary>
        /// Set the current process id
        /// </summary>
        /// <param name="processId">process id</param>
        public void SetCurrentProcessId(int processId)
        {
            CurrentProcessId = processId;
        }

        /// <summary>
        /// Retrieve project meta data
        /// </summary>
        /// <returns>project meta data</returns>
        public ProjectModel GetProject()
        {
            return ProjectModel;
        }

        #endregion // methods
    }
}
