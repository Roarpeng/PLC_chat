using Prism.Commands;
using Prism.Mvvm;
using System;
using System.Collections.ObjectModel;
using System.ComponentModel;
using System.IO;
using System.Linq;
using System.Windows;
using System.Windows.Forms;
using SharedResourceDictionary.Properties;
using TiaPortalOpennessAdapter.Services;
using TiaPortalOpennessAdapter.Utils;
using TiaPortalOpennessAdapterBase.Enums;
using TiaPortalOpennessCore.Contracts;
using TiaPortalOpennessInfrastructure.Constants;
using TiaPortalOpennessInfrastructure.Contracts;
using TiaPortalOpennessInfrastructure.Utils;
using Application = System.Windows.Application;
using MessageBox = System.Windows.MessageBox;

namespace TiaPortalModule.ViewModels
{
    /// <summary>
    /// Implementation of the settings editor
    /// </summary>
    public class SettingsEditorViewModel : BindableBase, ICloseWindow
    {
        #region fields

        private bool?                        _dialogResult;
        private bool                         _canCloseDialog;
        private readonly ISettingsService    _settingsService;
        private readonly ITraceLogService    _traceLogService;

        private TiaPortalStartMode           _selectedTiaPortalMode;

        private ObservableCollection<string> _engineeringVersions;
        private ObservableCollection<string> _opennessApiVersions;

        private bool                         _hidePreSelectionVersionDialog;
        private bool                         _originHidePreSelectionVersionDialog;

        private bool                         _loadSinamicsStartdriveModule;
        private bool                         _originLoadSinamicsStartdriveModule;

        private bool                         _loadStep7Module;
        private bool                         _originLoadStep7Module;

        private bool                         _loadWinCcProfessionalModule;
        private bool                         _originLoadWinCcProfessionalModule;

        private bool                         _loadWinCcUnifiedModule;
        private bool                         _originLoadWinCcUnifiedModule;

        private bool                         _exportWithDefaults;
        private bool                         _originExportWithDefaults;

        private bool                         _exportReadOnly;
        private bool                         _originExportReadOnly;

        private string                       _selectedEngineeringVersion;
        private string                       _originSelectedEngineeringVersion;

        private string                       _selectedOpennessApiVersion;
        private string                       _originSelectedOpennessApiVersion;

        private string                       _exportPath;
        private string                       _originDefaultExportPath;

        private string                       _modulePath;
        private string                       _originModulePath;

        private string                       _tiaPortalProjectPath;
        private string                       _originTiaPortalProjectPath;

        private string                       _globalUserLibraryPath;
        private string                       _originGlobalUserLibraryPath;

        private string                       _localSessionPath;
        private string                       _originLocalSessionPath;

        private readonly string              _originTiaPortalMode;

        private string                       _treeExpandLevel;

        private int                          _expandLevel;
        private readonly int                 _originTreeExpendLevel;

        #endregion // fields

        #region ctor

        public SettingsEditorViewModel(ITraceLogService traceLogService, ISettingsService settingsService)
        {
            _traceLogService                    = traceLogService;
            _settingsService                    = settingsService;

            CanCloseDialog                      = true;

            ModuleAndOptionPathChangedCommand   = new DelegateCommand<object>(ModuleAndOptionPathChanged);
            ModuleAndOptionPathCommand          = new DelegateCommand(GetModuleAndOptionPath);
            TiaPortalProjectPathChangedCommand  = new DelegateCommand<object>(TiaPortalProjectPathChanged);
            TiaPortalProjectPathCommand         = new DelegateCommand(GetTiaPortalProjectPath);
            GlobalUserLibraryPathChangedCommand = new DelegateCommand<object>(GlobalUserLibraryPathChanged);
            GlobalUserLibraryPathCommand        = new DelegateCommand(GetGlobalUserLibraryPath);
            LocalSessionPathChangedCommand      = new DelegateCommand<object>(LocalSessionPathChanged);
            LocalSessionPathCommand             = new DelegateCommand(GetLocalSessionPath);
            ExportPathChangedCommand            = new DelegateCommand<object>(DefaultExportPathChanged);
            ExportPathCommand                   = new DelegateCommand(GetDefaultExportPath);
            TreeExpandLevelChangedCommand       = new DelegateCommand<object>(TreeExpandLevelChanged);
            ExpandLevelUpCommand                = new DelegateCommand(ExpandLevelUp);
            ExpandLevelDownCommand              = new DelegateCommand(ExpandLevelDown);
            ResetCommand                        = new DelegateCommand(Reset);
            SaveCommand                         = new DelegateCommand(Save);
            CancelCommand                       = new DelegateCommand(Cancel);

            _originTiaPortalMode                = _settingsService.GetTiaPortalMode();
            SelectedTiaPortalMode               = EnumService.GetEnumValue<TiaPortalStartMode>(_originTiaPortalMode);

            ExpandLevel                         = _settingsService.GetTreeExpendLevel();
            _originTreeExpendLevel              = _settingsService.GetTreeExpendLevel();
            TreeExpandLevel                     = _originTreeExpendLevel.ToString();

            Initialize();
        }

        [DesignOnly(true)]
        internal SettingsEditorViewModel(bool hidePreSelectionVersionDialog,
                                        ObservableCollection<string> engineeringVersions,
                                        string selectedEngineeringVersion,
                                        ObservableCollection<string> opennessApiVersions,
                                        string selectedOpennessApiVersion,
                                        string moduleAndOptionPath,
                                        string projectPath,
                                        string globalUserLibraryPath,
                                        string localSessionPath,
                                        string defaultExportPath,
                                        bool exportWithDefaults,
                                        bool exportReadOnly,
                                        TiaPortalStartMode selectedTiaPortalMode,
                                        string treeExpandLevel)
        {
            try
            {
                _hidePreSelectionVersionDialog = hidePreSelectionVersionDialog;
                _engineeringVersions           = engineeringVersions;
                _selectedEngineeringVersion    = selectedEngineeringVersion;
                _opennessApiVersions           = opennessApiVersions;
                _selectedOpennessApiVersion    = selectedOpennessApiVersion;
                _modulePath                    = moduleAndOptionPath;
                _tiaPortalProjectPath          = projectPath;
                _globalUserLibraryPath         = globalUserLibraryPath;
                _localSessionPath              = localSessionPath;
                _exportPath                    = defaultExportPath;
                _exportWithDefaults            = exportWithDefaults;
                _exportReadOnly                = exportReadOnly;
                _selectedTiaPortalMode         = selectedTiaPortalMode;
                _treeExpandLevel               = treeExpandLevel;

                if (!IsDesignTime)
                {
                    throw new InvalidOperationException(ExceptionInfo.StrDesignTimeOnlyConstructorException);
                }
            }
            catch (Exception ex)
            {
                MessageBox.Show($"{ex.Message}{Environment.NewLine}{Environment.NewLine}Details:{Environment.NewLine}{ex}", "TIA Portal Openness Demo", MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }

        private void Initialize()
        {
            HidePreSelectionVersionDialog        = _settingsService.GetHidePreSelectionAssemblyVersion();
            LoadSinamicsStartdriveModule         = _settingsService.GetLoadSinamicsStartdriveModule();
            _originLoadSinamicsStartdriveModule  = _settingsService.GetLoadSinamicsStartdriveModule();
            LoadStep7Module                      = _settingsService.GetLoadStep7Module();
            _originLoadStep7Module               = _settingsService.GetLoadStep7Module();
            LoadWinCcProfessionalModule          = _settingsService.GetLoadWinCcProfessionalModule();
            _originLoadWinCcProfessionalModule   = _settingsService.GetLoadWinCcProfessionalModule();
            LoadWinCcUnifiedModule               = _settingsService.GetLoadWinCcUnifiedModule();
            _originLoadWinCcUnifiedModule        = _settingsService.GetLoadWinCcUnifiedModule(); 
            _originHidePreSelectionVersionDialog = _settingsService.GetHidePreSelectionAssemblyVersion();
            _originSelectedEngineeringVersion    = _settingsService.GetSelectedEngineeringVersion();
            GetEngineeringVersions();
            _originSelectedOpennessApiVersion    = _settingsService.GetSelectedOpennessApiVersion();
            GetOpennessApiVersions();
            ExportWithDefaults                   = _settingsService.GetExportWithDefaults();
            _originExportWithDefaults            = _settingsService.GetExportWithDefaults();
            ExportReadOnly                       = _settingsService.GetExportReadOnly();
            _originExportReadOnly                = _settingsService.GetExportReadOnly();
            ExportPath                           = _settingsService.GetExportPath();
            _originDefaultExportPath             = _settingsService.GetExportPath();
            ModuleAndOptionPath                  = _settingsService.GetModulePath();
            _originModulePath                    = _settingsService.GetModulePath();
            TiaPortalProjectPath                 = _settingsService.GetProjectPath();
            _originTiaPortalProjectPath          = _settingsService.GetProjectPath();
            GlobalUserLibraryPath                = _settingsService.GetGlobalUserLibraryPath();
            _originGlobalUserLibraryPath         = _settingsService.GetGlobalUserLibraryPath();
            LocalSessionPath                     = _settingsService.GetLocalSessionPath();
            _originLocalSessionPath              = _settingsService.GetLocalSessionPath();
        }

        #endregion // ctor

        #region commands

        public DelegateCommand<object> ModuleAndOptionPathChangedCommand { get; }
        public DelegateCommand ModuleAndOptionPathCommand { get; }
        public DelegateCommand<object> TiaPortalProjectPathChangedCommand { get; }
        public DelegateCommand TiaPortalProjectPathCommand { get; }
        public DelegateCommand<object> GlobalUserLibraryPathChangedCommand { get; }
        public DelegateCommand GlobalUserLibraryPathCommand { get; }
        public DelegateCommand<object> LocalSessionPathChangedCommand { get; }
        public DelegateCommand LocalSessionPathCommand { get; }
        public DelegateCommand<object> ExportPathChangedCommand { get; }
        public DelegateCommand ExportPathCommand { get; }
        public DelegateCommand<object> TreeExpandLevelChangedCommand { get; }
        public DelegateCommand ExpandLevelUpCommand { get; }
        public DelegateCommand ExpandLevelDownCommand { get; }
        public DelegateCommand ResetCommand { get; }
        public DelegateCommand SaveCommand { get; }
        public DelegateCommand CancelCommand { get; }

        #endregion // commands

        #region command implementation

        private void ModuleAndOptionPathChanged(object obj)
        {
            ModuleAndOptionPathValidationError = false;
            CanCloseDialog = true;
        }

        private void GetModuleAndOptionPath()
        {
            var folderSearch = new FolderBrowserDialog();
            folderSearch.SelectedPath = _originModulePath;

            if (System.Windows.Forms.DialogResult.OK == folderSearch.ShowDialog())
            {
                ModuleAndOptionPath = folderSearch.SelectedPath;
            }
        }

        private void TiaPortalProjectPathChanged(object obj)
        {
            TiaPortalProjectPathError = false;
            CanCloseDialog = true;
        }

        private void GetTiaPortalProjectPath()
        {
            var folderSearch = new FolderBrowserDialog();
            folderSearch.SelectedPath = _originTiaPortalProjectPath;

            if (System.Windows.Forms.DialogResult.OK == folderSearch.ShowDialog())
            {
                TiaPortalProjectPath = folderSearch.SelectedPath;
            }
        }

        private void GlobalUserLibraryPathChanged(object obj)
        {
            GlobalUserLibraryPathError = false;
            CanCloseDialog = true;
        }

        private void GetGlobalUserLibraryPath()
        {
            var folderSearch = new FolderBrowserDialog();
            folderSearch.SelectedPath = _originGlobalUserLibraryPath;

            if (System.Windows.Forms.DialogResult.OK == folderSearch.ShowDialog())
            {
                GlobalUserLibraryPath = folderSearch.SelectedPath;
            }
        }

        private void LocalSessionPathChanged(object obj)
        {
            LocalSessionPathError = false;
            CanCloseDialog = true;
        }

        private void GetLocalSessionPath()
        {
            var folderSearch = new FolderBrowserDialog();
            folderSearch.SelectedPath = _originLocalSessionPath;

            if (System.Windows.Forms.DialogResult.OK == folderSearch.ShowDialog())
            {
                LocalSessionPath = folderSearch.SelectedPath;
            }
        }

        private void DefaultExportPathChanged(object obj)
        {
            ExportPathValidationError = false;
            CanCloseDialog = true;
        }

        private void GetDefaultExportPath()
        {
            var folderSearch = new FolderBrowserDialog();
            folderSearch.SelectedPath = _originDefaultExportPath;

            if (System.Windows.Forms.DialogResult.OK == folderSearch.ShowDialog())
            {
                ExportPath = folderSearch.SelectedPath;
            }
        }

        private void TreeExpandLevelChanged(object obj)
        {
            int numValue;

            if (int.TryParse(TreeExpandLevel, out numValue))
            {
                TreeExpandLevel = numValue.ToString();
            }
            else
            {
                TreeExpandLevel = "1";
            }

        }

        private void ExpandLevelUp()
        {
            if (ExpandLevel < 99)
            {
                ExpandLevel++;
            }
            TreeExpandLevelChanged(ExpandLevel);
        }

        private void ExpandLevelDown()
        {
            if (ExpandLevel > 1)
            {
                ExpandLevel--;
            }
            TreeExpandLevelChanged(ExpandLevel);
        }

        private void Reset()
        {
            HidePreSelectionVersionDialog = _originHidePreSelectionVersionDialog;

            LoadSinamicsStartdriveModule  = _originLoadSinamicsStartdriveModule;
            LoadStep7Module               = _originLoadStep7Module;
            LoadWinCcProfessionalModule   = _originLoadWinCcProfessionalModule;
            LoadWinCcUnifiedModule        = _originLoadWinCcUnifiedModule;

            SelectedEngineeringVersion    = _originSelectedEngineeringVersion;
            SelectedOpennessApiVersion    = _originSelectedOpennessApiVersion;

            ModuleAndOptionPath           = _originModulePath;
            TiaPortalProjectPath          = _originTiaPortalProjectPath;
            GlobalUserLibraryPath         = _originGlobalUserLibraryPath;
            LocalSessionPath              = _originLocalSessionPath;

            ExportPath                    = _originDefaultExportPath;
            ExportWithDefaults            = _originExportWithDefaults;
            ExportReadOnly                = _originExportReadOnly;

            SelectedTiaPortalMode         = EnumService.GetEnumValue<TiaPortalStartMode>(_originTiaPortalMode);

            TreeExpandLevel               = _originTreeExpendLevel.ToString();
            ExpandLevel                   = _originTreeExpendLevel;
        }

        private void Save()
        {
            ValidationProvider();

            if (ModuleAndOptionPathValidationError || ExportPathValidationError)
            {
                CanCloseDialog = false;
                MessageBox.Show(@"Valid module and option path and default export path are both required!", @"Validation Error", MessageBoxButton.OK, MessageBoxImage.Error);
            }

            if (ExceptionOccurred)
            {
                CanCloseDialog = false;
            }

            if (CanCloseDialog)
            {
                _settingsService.SetHidePreSelectionAssemblyVersion(HidePreSelectionVersionDialog);

                _settingsService.SetLoadSinamicsStartdriveModule(LoadSinamicsStartdriveModule);
                _settingsService.SetLoadStep7Module(LoadStep7Module);
                _settingsService.SetLoadWinCcProfessionalModule(LoadWinCcProfessionalModule);
                _settingsService.SetLoadWinCcUnifiedModule(LoadWinCcUnifiedModule);

                _settingsService.SetSelectedEngineeringVersion(SelectedEngineeringVersion);
                _settingsService.SetSelectedOpennessApiVersion(SelectedOpennessApiVersion);

                _settingsService.SetModulePath(ModuleAndOptionPath);
                _settingsService.SetProjectPath(TiaPortalProjectPath);
                _settingsService.SetGlobalUserLibraryPath(GlobalUserLibraryPath);
                _settingsService.SetLocalSessionPath(LocalSessionPath);

                _settingsService.SetDefaultExportPath(ExportPath);
                _settingsService.SetExportWithDefaults(ExportWithDefaults);
                _settingsService.SetExportReadOnly(ExportReadOnly);

                _settingsService.SetTiaPortalMode(SelectedTiaPortalMode.ToString());

                _settingsService.SetTreeExpendLevel(ExpandLevel);

                Close?.Invoke();
            }
        }

        private void Cancel()
        {
            CanCloseDialog = true;

            Close?.Invoke();
        }

        #endregion // command implementation

        #region actions

        /// <summary>
        /// Close Action of the window.
        /// </summary>
        public Action Close { get; set; }

        #endregion // actions

        #region properties

        /// <summary>
        /// Determine if the call is at design time.
        /// </summary>
        public static bool IsDesignTime => (LicenseManager.UsageMode == LicenseUsageMode.Designtime);

        /// <summary>
        /// Mode to open TIA Portal instance (with UI or without UI)
        /// </summary>
        public TiaPortalStartMode SelectedTiaPortalMode
        {
            get => _selectedTiaPortalMode;
            set
            {
                _selectedTiaPortalMode = value;
                RaisePropertyChanged(nameof(SelectedTiaPortalMode));
            }
        }

        /// <summary>
        /// Installed versions of the engineering dll
        /// </summary>
        public ObservableCollection<string> EngineeringVersions
        {
            get => _engineeringVersions;
            set => SetProperty(ref _engineeringVersions, value);
        }

        /// <summary>
        /// Installed versions of the openness api 
        /// </summary>
        public ObservableCollection<string> OpennessApiVersions
        {
            get => _opennessApiVersions;
            set => SetProperty(ref _opennessApiVersions, value);
        }

        /// <summary>
        /// The result of the dialog (window)
        /// </summary>
        public bool? DialogResult
        {
            get => _dialogResult;
            set
            {
                _dialogResult = value;
                // Attention!!!
                // The string parameter must not be removed, even if
                // the ReSharper suggests it!
                RaisePropertyChanged("DialogResult");
            }
        }

        /// <summary>
        /// Indicates whether the window can be closed
        /// </summary>
        public bool CanCloseDialog
        {
            get => _canCloseDialog;
            set
            {
                _canCloseDialog = value;
                // Attention!!!
                // The string parameter must not be removed, even if
                // the ReSharper suggests it!
                RaisePropertyChanged("CanCloseDialog");
            }
        }

        /// <summary>
        /// Indicates the visibility of the dialog.
        /// That means, will be the dialog, on start of the demo application, displayed or not.
        /// </summary>
        public bool HidePreSelectionVersionDialog
        {
            get => _hidePreSelectionVersionDialog;
            set => SetProperty(ref _hidePreSelectionVersionDialog, value);
        }

        /// <summary>
        /// Indicates whether the sinamics startdrive module should be load
        /// </summary>
        public bool LoadSinamicsStartdriveModule
        {
            get => _loadSinamicsStartdriveModule;
            set => SetProperty(ref _loadSinamicsStartdriveModule, value);
        }

        /// <summary>
        /// Indicates whether the step7 module should be load
        /// </summary>
        public bool LoadStep7Module
        {
            get => _loadStep7Module;
            set => SetProperty(ref _loadStep7Module, value);
        }

        /// <summary>
        /// Indicates whether the winCC professional module should be load
        /// </summary>
        public bool LoadWinCcProfessionalModule
        {
            get => _loadWinCcProfessionalModule;
            set => SetProperty(ref _loadWinCcProfessionalModule, value);
        }

        /// <summary>
        /// Indicates whether the winCC unified module should be load
        /// </summary>
        public bool LoadWinCcUnifiedModule
        {
            get => _loadWinCcUnifiedModule;
            set => SetProperty(ref _loadWinCcUnifiedModule, value);
        }

        /// <summary>
        /// If true, then the default values are also exported
        /// </summary>
        public bool ExportWithDefaults
        {
            get => _exportWithDefaults;
            set => SetProperty(ref _exportWithDefaults, value);
        }

        /// <summary>
        /// If true, then the read-only values are also exported
        /// </summary>
        public bool ExportReadOnly
        {
            get => _exportReadOnly;
            set => SetProperty(ref _exportReadOnly, value);
        }

        /// <summary>
        /// Indicates an validation error of modules or options path
        /// </summary>
        public bool ModuleAndOptionPathValidationError
        {
            get;
            set;
        }

        /// <summary>
        /// Indicates an validation error of project path
        /// </summary>
        public bool TiaPortalProjectPathError
        {
            get;
            set;
        }

        /// <summary>
        /// Indicates an validation error of global user library path
        /// </summary>
        public bool GlobalUserLibraryPathError
        {
            get;
            set;
        }

        /// <summary>
        /// Indicates an validation error of local session path
        /// </summary>
        public bool LocalSessionPathError
        {
            get;
            set;
        }

        /// <summary>
        /// Indicates an validation error of the export path
        /// </summary>
        public bool ExportPathValidationError
        {
            get;
            set;
        }

        /// <summary>
        /// Indicates whether an exception has occurred
        /// </summary>
        public bool ExceptionOccurred
        {
            get;
            set;
        }

        /// <summary>
        /// Selected version of the engineering dll
        /// </summary>
        public string SelectedEngineeringVersion
        {
            get => _selectedEngineeringVersion;
            set
            {
                SetProperty(ref _selectedEngineeringVersion, value);
                SelectedOpennessApiVersion = null;
                GetOpennessApiVersions();
            }
        }

        /// <summary>
        /// Selected version of the openness api
        /// </summary>
        public string SelectedOpennessApiVersion
        {
            get => _selectedOpennessApiVersion;
            set => SetProperty(ref _selectedOpennessApiVersion, value);
        }

        /// <summary>
        /// Dialog title
        /// </summary>
        public string Title => "Application settings editor";

        /// <summary>
        /// Path from which modules and options are loaded
        /// </summary>
        public string ModuleAndOptionPath
        {
            get => _modulePath;
            set => SetProperty(ref _modulePath, value);
        }

        /// <summary>
        /// Path from where a project are loaded
        /// </summary>
        public string TiaPortalProjectPath
        {
            get => _tiaPortalProjectPath;
            set => SetProperty(ref _tiaPortalProjectPath, value);
        }

        /// <summary>
        /// Path where a global user library are saved
        /// </summary>
        public string GlobalUserLibraryPath
        {
            get => _globalUserLibraryPath;
            set => SetProperty(ref _globalUserLibraryPath, value);
        }

        /// <summary>
        /// Path from where a local session are loaded
        /// </summary>
        public string LocalSessionPath
        {
            get => _localSessionPath;
            set => SetProperty(ref _localSessionPath, value);
        }

        /// <summary>
        /// The export path
        /// </summary>
        public string ExportPath
        {
            get => _exportPath;
            set => SetProperty(ref _exportPath, value);
        }

        /// <summary>
        /// Initial tree expand level for all tree views (settings string)
        /// </summary>
        public string TreeExpandLevel
        {
            get => _treeExpandLevel;
            set
            {
                SetProperty(ref _treeExpandLevel, value);
                RaisePropertyChanged(nameof(TreeExpandLevel));
            }
        }

        /// <summary>
        /// Initial tree expand level for all tree views
        /// </summary>
        public int ExpandLevel
        {
            get => _expandLevel;
            set
            {
                _expandLevel = value;
                TreeExpandLevel = _expandLevel.ToString();
                RaisePropertyChanged(nameof(TreeExpandLevel));
            }
        }

        #endregion // properties

        #region methods

        /// <summary>
        /// Retrieving the installed versions of the engineering dll.
        /// </summary>
        private void GetEngineeringVersions()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(SettingsEditorViewModel) + " - " + nameof(GetEngineeringVersions) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                EngineeringVersions = new ObservableCollection<string>(Resolver.GetEngineeringVersions());
                if (EngineeringVersions != null && EngineeringVersions.Count > 0)
                {
                    var selectedVersion = _settingsService.GetSelectedEngineeringVersion();

                    SelectedEngineeringVersion = (from item in EngineeringVersions
                                                  where item == selectedVersion
                                                  select item).FirstOrDefault();

                    if (string.IsNullOrEmpty(SelectedEngineeringVersion))
                    {
                        SelectedEngineeringVersion = EngineeringVersions.FirstOrDefault();
                        MessageBox.Show("The expected engineering version isn't available!", "Engineering version", MessageBoxButton.OK, MessageBoxImage.Warning);
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

        /// <summary>
        /// Retrieving the installed versions of the openness api
        /// </summary>
        private void GetOpennessApiVersions()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(SettingsEditorViewModel) + " - " + nameof(GetOpennessApiVersions) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                if (string.IsNullOrEmpty(SelectedEngineeringVersion)) return;
                OpennessApiVersions = new ObservableCollection<string>(Resolver.GetAssemblies(SelectedEngineeringVersion));
                if (OpennessApiVersions != null && OpennessApiVersions.Count > 0)
                {
                    var selectedVersion = _settingsService.GetSelectedOpennessApiVersion();

                    SelectedOpennessApiVersion = (from item in OpennessApiVersions
                                                  where item == selectedVersion
                                                  select item).FirstOrDefault();

                    if (string.IsNullOrEmpty(SelectedOpennessApiVersion))
                    {
                        SelectedOpennessApiVersion = string.Empty;
                        MessageBox.Show("The expected openness api version isn't available!", "Openness api version", MessageBoxButton.OK, MessageBoxImage.Warning);
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

        /// <summary>
        /// Validation of the entered path values
        /// </summary>
        private void ValidationProvider()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(SettingsEditorViewModel) + " - " + nameof(ValidationProvider) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            ExceptionOccurred = false;
            try
            {
                ModuleAndOptionPathValidationError = string.IsNullOrEmpty(ModuleAndOptionPath) || Directory.Exists(ModuleAndOptionPath) == false;
            }
            catch (Exception exception)
            {
                ExceptionOccurred = true;
                MessageBox.Show(exception.Message, @"Exception", MessageBoxButton.OK, MessageBoxImage.Error);
            }

            try
            {
                TiaPortalProjectPathError = string.IsNullOrEmpty(TiaPortalProjectPath) || Directory.Exists(TiaPortalProjectPath) == false;
            }
            catch (Exception exception)
            {
                ExceptionOccurred = true;
                MessageBox.Show(exception.Message, @"Exception", MessageBoxButton.OK, MessageBoxImage.Error);
            }

            try
            {
                GlobalUserLibraryPathError = string.IsNullOrEmpty(GlobalUserLibraryPath) || Directory.Exists(GlobalUserLibraryPath) == false;
            }
            catch (Exception exception)
            {
                ExceptionOccurred = true;
                MessageBox.Show(exception.Message, @"Exception", MessageBoxButton.OK, MessageBoxImage.Error);
            }

            try
            {
                LocalSessionPathError = string.IsNullOrEmpty(LocalSessionPath) || Directory.Exists(LocalSessionPath) == false;
            }
            catch (Exception exception)
            {
                ExceptionOccurred = true;
                MessageBox.Show(exception.Message, @"Exception", MessageBoxButton.OK, MessageBoxImage.Error);
            }

            try
            {
                ExportPathValidationError = string.IsNullOrEmpty(ExportPath) || Directory.Exists(ExportPath) == false;
            }
            catch (Exception exception)
            {
                ExceptionOccurred = true;
                MessageBox.Show(exception.Message, @"Exception", MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }

        /// <summary>
        /// Decision whether the dialog can be closed.
        /// </summary>
        /// <returns></returns>
        public bool CanClose()
        {
            return CanCloseDialog;
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

        /// <summary>
        /// Execute writing trace log in different thread for all inner exceptions
        /// </summary>
        /// <param name="exception"></param>
        private void WriteTraceLogProxy(Exception exception)
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
