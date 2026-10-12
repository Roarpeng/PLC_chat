using Prism.Commands;
using Prism.Mvvm;
using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.ComponentModel;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Windows;
using System.Windows.Forms;
using TiaPortalOpennessAdapter.Models;
using TiaPortalOpennessAdapter.Utils;
using TiaPortalOpennessAdapterContracts;
using TiaPortalOpennessCore.Contracts;
using TiaPortalOpennessInfrastructure.Constants;
using TiaPortalOpennessInfrastructure.Contracts;
using TiaPortalOpennessInfrastructure.Utils;
using Application = System.Windows.Application;
using MessageBox = System.Windows.MessageBox;

namespace TiaPortalOpennessDemo.ViewModels
{
    /// <summary>
    /// Provides the possibility to select the modules and options to be used.
    /// </summary>
    public class PreConfigurationEnvironmentViewModel : BindableBase, ICloseWindow
    {
        #region fields

        private readonly ISettingsService                        _settingsService;
        private readonly ITraceLogService                        _traceLogService;
        private ObservableCollection<TiaPortalModulesAndOptions> _baseModules;
        private ObservableCollection<TiaPortalModulesAndOptions> _modulesAndOptions;
        private IList<TiaPortalModulesAndOptions>                _selectedModuleExpansions;

        private string _modulePath;

        private bool? _dialogResult;
        private bool _baseServiceFound;
        private bool _fallBackChecked;
        private readonly bool _canCloseDialog;

        #endregion // fields

        #region ctor

        /// <summary>
        /// Constructor with default initialization. 
        /// </summary>
        public PreConfigurationEnvironmentViewModel(ISettingsService settingsService, ITraceLogService traceLogService)
        {
            _settingsService                    = settingsService;
            _traceLogService                    = traceLogService;
            _canCloseDialog                     = true;
            _fallBackChecked                    = false;

            ConfirmationCommand                 = new DelegateCommand(ConfirmAndCloseWindow);
            GetPathFromModulesAndOptionsCommand = new DelegateCommand(GetPathFromModulesAndOptions);

            BaseModules                         = new ObservableCollection<TiaPortalModulesAndOptions>();
            ModulesAndOptions                   = new ObservableCollection<TiaPortalModulesAndOptions>();
            SelectedModuleExpansions           = new List<TiaPortalModulesAndOptions>();

            var modulePath                      = _settingsService.GetModulePath();
            var fullPath                        = string.Empty;

            if (!string.IsNullOrEmpty(modulePath))
            {
                fullPath                        = Path.GetFullPath(modulePath);
            }

            if (!string.IsNullOrEmpty(fullPath) && Directory.Exists(fullPath))
            {
                ModulePath = fullPath;
            }
            else
            {
                var location = AppDomain.CurrentDomain.BaseDirectory;
                var fallBackPath = Path.GetFullPath(Path.Combine(location, "ModuleExpansions"));
                ModulePath = fallBackPath;
            }
        }

        /// <summary>
        /// Constructor for design time only.
        /// </summary>
        /// <param name="modulePath">Sample data</param>
        /// <param name="modulesAndOptions">Sample data</param>
        [DesignOnly(true)]
        internal PreConfigurationEnvironmentViewModel(string modulePath, ObservableCollection<TiaPortalModulesAndOptions> modulesAndOptions)
        {
            try
            {
                _modulePath = modulePath;
                _modulesAndOptions = modulesAndOptions;

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

        #endregion // ctor

        #region commands

        /// <summary>
        /// Command to determine the path from where the modules and options are to be loaded.
        /// </summary>
        public DelegateCommand GetPathFromModulesAndOptionsCommand { get; }
        
        /// <summary>
        /// Command to confirm the selection.
        /// </summary>
        public DelegateCommand ConfirmationCommand { get; }

        #endregion // commands

        #region actions

        /// <summary>
        /// Action for window close.
        /// </summary>
        public Action Close { get; set; }

        #endregion // actions

        #region properties

        /// <summary>
        /// Determine if the call is at design time.
        /// </summary>
        public static bool IsDesignTime => (LicenseManager.UsageMode == LicenseUsageMode.Designtime);

        /// <summary>
        /// Collection of Modules and Options that can be loaded.
        /// </summary>
        public ObservableCollection<TiaPortalModulesAndOptions> BaseModules
        {
            get => _baseModules;
            set => SetProperty(ref _baseModules, value);
        }

        /// <summary>
        /// Collection of Modules and Options that can be loaded.
        /// </summary>
        public ObservableCollection<TiaPortalModulesAndOptions> ModulesAndOptions
        {
            get => _modulesAndOptions;
            set => SetProperty(ref _modulesAndOptions, value);
        }

        /// <summary>
        /// Collection of Modules and Options to be loaded.
        /// </summary>
        public IList<TiaPortalModulesAndOptions> SelectedModuleExpansions
        {
            get => _selectedModuleExpansions;
            set => SetProperty(ref _selectedModuleExpansions, value);
        }

        /// <summary>
        /// The target directory from where the modules and options to be loaded.
        /// </summary>
        public string ModulePath
        {
            get => _modulePath;
            set
            {
                SetProperty(ref _modulePath, value);
                GetModulesAndOptions(_modulePath);
            }
        }

        /// <summary>
        /// The result of the dialog.
        /// </summary>
        public bool? DialogResult
        {
            get => _dialogResult;
            set => SetProperty(ref _dialogResult, value);
        }

        /// <summary>
        /// Indicates if the base service was found
        /// </summary>
        public bool BaseServiceFound
        {
            get => _baseServiceFound;
            set => SetProperty(ref _baseServiceFound, value);
        }

        /// <summary>
        /// Dialog title
        /// </summary>
        public string Title => "Pre selection of modules and options";

        #endregion // properties

        #region methods

        /// <summary>
        /// Determine the path from where the modules and options are to be loaded. 
        /// </summary>
        private void GetPathFromModulesAndOptions()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(PreConfigurationEnvironmentViewModel) + " - " + nameof(GetPathFromModulesAndOptions) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            var folderSearch = new FolderBrowserDialog();
            if (!string.IsNullOrEmpty(ModulePath))
            {
                folderSearch.SelectedPath = ModulePath;
            }
            else
            {
                folderSearch.SelectedPath = _settingsService.GetModulePath();
            }

            if (System.Windows.Forms.DialogResult.OK == folderSearch.ShowDialog())
            {
                ModulePath = folderSearch.SelectedPath;
            }
        }

        /// <summary>
        /// Get the available modules and options from target directory.
        /// </summary>
        /// <param name="modulePath"></param>
        private void GetModulesAndOptions(string modulePath)
        {
            ModulesAndOptions.Clear();

            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(PreConfigurationEnvironmentViewModel) + " - " + nameof(GetModulesAndOptions) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            var version = _settingsService.GetSelectedOpennessApiVersion();
            var moduleExpansions = Resolver.GetAssembliesByPath(modulePath, version);

            if (!moduleExpansions.Any() && !_fallBackChecked)
            {
                _fallBackChecked = true;
                var location = AppDomain.CurrentDomain.BaseDirectory;
                var fallBackPath = Path.GetFullPath(Path.Combine(location, "ModuleExpansions"));
                ModulePath = fallBackPath;
                return;
            }

            BaseServiceFound = false;
            foreach (var item in moduleExpansions)
            {
                var temp = item.ModuleType.GetInterface(typeof(IOpennessBaseModule).FullName);
                if (temp != null)
                {
                    BaseModules.Add(item);
                    BaseServiceFound = true;
                }
                else
                {
                    item.IsSelected = (bool)_settingsService.GetSettingByName("Load" + item.AssemblyName);
                    ModulesAndOptions.Add(item);
                }
            }

            if (BaseServiceFound == false)
            {
                MessageBox.Show("The base service\n- TiaPortalOpennessAdapterService.dll\nfor the TIA Portal Openness Demo was not found, \nplease check the module expansions path in the settings. \nSee the manual for more information.", "Error", MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }

        /// <summary>
        /// Confirm selection an close dialog.
        /// </summary>
        private void ConfirmAndCloseWindow()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(PreConfigurationEnvironmentViewModel) + " - " + nameof(ConfirmAndCloseWindow) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            DialogResult = true;

            var selectedItems = (from item in ModulesAndOptions
                                 where item.IsSelected
                                 select item).ToList();

            foreach (var item in selectedItems)
            {
                SelectedModuleExpansions.Add(item);
            }

            Close?.Invoke();
        }

        /// <summary>
        /// Decision whether the dialog can be closed.
        /// </summary>
        /// <returns></returns>
        public bool CanClose()
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(PreConfigurationEnvironmentViewModel) + " - " + nameof(CanClose) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            return _canCloseDialog;
        }

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


        #endregion // methods
    }
}
