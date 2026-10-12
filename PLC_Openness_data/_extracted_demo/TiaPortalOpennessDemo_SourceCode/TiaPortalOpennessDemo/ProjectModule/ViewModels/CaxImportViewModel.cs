using Prism.Commands;
using Prism.Mvvm;
using System;
using System.Collections.ObjectModel;
using System.ComponentModel;
using System.IO;
using System.Windows.Forms;
using TiaPortalOpennessAdapterBase.Enums;
using TiaPortalOpennessAdapterBase.Models;
using TiaPortalOpennessCore.Contracts;
using TiaPortalOpennessInfrastructure.Constants;
using TiaPortalOpennessInfrastructure.Contracts;
using MessageBox = System.Windows.Forms.MessageBox;

namespace ProjectModule.ViewModels
{
    /// <summary>
    /// CaxImportViewModel implementation
    /// </summary>
    public class CaxImportViewModel : BindableBase, ICloseWindow
    {
        #region fields

        private readonly ISettingsService _settingsService;

        private bool? _dialogResult;
        private bool _canCloseDialog;

        private ObservableCollection<CaxImportOptionInfo> _caxImportOptionInfos;
        private CaxImportOptionInfo _selectedCaxImportOptionInfo;
        private FileInfo _caxImportFileInfo;
        private string _caxImportFile;

        #endregion // fields

        #region ctor

        /// <summary>
        /// Constructor with initialization
        /// </summary>
        public CaxImportViewModel(ISettingsService settingsService)
        {
            CanCloseDialog = false;
            _settingsService = settingsService;

            CaxImportFileChangedCommand = new DelegateCommand<object>(CaxImportFileChanged);
            SelectCaxImportFileCommand = new DelegateCommand(SelectCaxImportFile);

            CaxImportCommand = new DelegateCommand(CaxImport);
            CancelCommand = new DelegateCommand(CancelDialog);

            var importOptions = new ObservableCollection<CaxImportOptionInfo>();
            SelectedCaxImportOptionInfo = new CaxImportOptionInfo() { OptionName = "Move to parking lot", OptionType = CaxImportOption.MoveToParkingLot };
            importOptions.Add(SelectedCaxImportOptionInfo);
            importOptions.Add(new CaxImportOptionInfo() { OptionName = "Overwrite TIA device", OptionType = CaxImportOption.OverwriteTiaDevice });
            importOptions.Add(new CaxImportOptionInfo() { OptionName = "Retain TIA device", OptionType = CaxImportOption.RetainTiaDevice });

            CaxImportOptionInfos = importOptions;
        }

        /// <summary>
        /// Constructor for design time only.
        /// </summary>
        /// <param name="caxImportFile"></param>
        /// <param name="caxImportOptionInfos"></param>
        /// <param name="selectedCaxImportOption"></param>
        [DesignOnly(true)]
        internal CaxImportViewModel(string caxImportFile, ObservableCollection<CaxImportOptionInfo> caxImportOptionInfos, CaxImportOptionInfo selectedCaxImportOption)
        {
            try
            {
                CaxImportFile = caxImportFile;
                CaxImportOptionInfos = caxImportOptionInfos;
                SelectedCaxImportOptionInfo = selectedCaxImportOption;

                if (!IsDesignTime)
                {
                    throw new InvalidOperationException(ExceptionInfo.StrDesignTimeOnlyConstructorException);
                }
            }
            catch (Exception ex)
            {
                MessageBox.Show($"{ex.Message}{Environment.NewLine}{Environment.NewLine}Details:{Environment.NewLine}{ex}", "TIA Portal Openness Demo", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        #endregion // ctor

        #region commands

        /// <summary>
        /// Command to handle input changes for the target directory
        /// </summary>M
        public DelegateCommand<object> CaxImportFileChangedCommand { get; }

        /// <summary>
        /// Command to open file browser for select the CAx import file
        /// </summary>
        public DelegateCommand SelectCaxImportFileCommand { get; }

        /// <summary>
        /// Command to confirm the input and create a new project
        /// </summary>
        public DelegateCommand CaxImportCommand { get; }

        /// <summary>
        /// Command to cancel 
        /// </summary>
        public DelegateCommand CancelCommand { get; }

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
        /// Collection of import options for choosing
        /// </summary>
        public ObservableCollection<CaxImportOptionInfo> CaxImportOptionInfos
        {
            get => _caxImportOptionInfos;
            set
            {
                SetProperty(ref _caxImportOptionInfos, value);
                RaisePropertyChanged(nameof(CaxImportOptionInfos));
            }
        }

        /// <summary>
        /// Selection import option to be used
        /// </summary>
        public CaxImportOptionInfo SelectedCaxImportOptionInfo
        {
            get => _selectedCaxImportOptionInfo;
            set
            {
                SetProperty(ref _selectedCaxImportOptionInfo, value);
                RaisePropertyChanged(nameof(SelectedCaxImportOptionInfo));
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
        /// Window title
        /// </summary>
        public string Title => "Select CAx import file";

        /// <summary>
        /// Project name
        /// </summary>
        public string CaxImportFile
        {
            get => _caxImportFile;
            set => SetProperty(ref _caxImportFile, value);
        }

        /// <summary>
        /// Import file info
        /// </summary>
        public FileInfo CaxImportFileInfo
        {
            get => _caxImportFileInfo;
            set => SetProperty(ref _caxImportFileInfo, value);
        }

        /// <summary>
        /// Indicates an validation error of the project name
        /// </summary>
        public bool CaxImportFileValidationError
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

        #endregion // properties

        #region methods

        private void CaxImportFileChanged(object obj)
        {
            CaxImportFileValidationError = false;
            CanCloseDialog = true;
        }

        /// <summary>
        /// Determine the path of the target directory 
        /// </summary>
        private void SelectCaxImportFile()
        {
            var fileSearch = new OpenFileDialog();

            fileSearch.InitialDirectory = _settingsService.GetExportPath();
            fileSearch.Filter = @"AML File|*.aml";
            fileSearch.FilterIndex = 2;
            fileSearch.RestoreDirectory = true;
            var result = fileSearch.ShowDialog();

            if (System.Windows.Forms.DialogResult.OK == result)
            {
                if (File.Exists(fileSearch.FileName))
                {
                    CaxImportFileInfo = new FileInfo(fileSearch.FileName);
                    CaxImportFile = CaxImportFileInfo.FullName;
                }
            }
        }

        /// <summary>
        /// Validation the input
        /// </summary>
        private void ValidationProvider()
        {
            ExceptionOccurred = false;
            try
            {
                CaxImportFileValidationError = string.IsNullOrEmpty(CaxImportFile) || File.Exists(CaxImportFile) == false;
            }
            catch (Exception exception)
            {
                ExceptionOccurred = true;
                MessageBox.Show(exception.Message, @"Exception", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        /// <summary>
        /// Validation and confirmation of the input and close the dialog
        /// </summary>
        private void CaxImport()
        {
            DialogResult = true;

            ValidationProvider();

            if (CaxImportFileValidationError)
            {
                CanCloseDialog = false;
                MessageBox.Show(@"Project name and valid path are both required!", @"Validation Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }

            if (ExceptionOccurred)
            {
                CanCloseDialog = false;
            }

            if (CanCloseDialog)
            {
                Close?.Invoke();
            }
        }

        /// <summary>
        /// User has canceled, everything is fine
        /// </summary>
        private void CancelDialog()
        {
            CaxImportFile = string.Empty;
            CaxImportFileValidationError = false;
            ExceptionOccurred = false;

            DialogResult = false;
            CanCloseDialog = true;

            Close?.Invoke();
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
    }
}
