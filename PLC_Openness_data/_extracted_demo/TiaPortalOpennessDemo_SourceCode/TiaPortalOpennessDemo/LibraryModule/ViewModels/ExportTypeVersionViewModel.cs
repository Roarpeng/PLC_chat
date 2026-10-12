using Prism.Commands;
using Prism.Mvvm;
using System;
using System.IO;
using System.Windows.Forms;
using TiaPortalOpennessCore.Contracts;
using TiaPortalOpennessInfrastructure.Contracts;

namespace LibraryModule.ViewModels
{
    public class ExportTypeVersionViewModel : BindableBase, ICloseWindow
    {
        #region fields

        private readonly ISettingsService _settingsService;
        private bool? _dialogResult;
        private bool _canCloseDialog;
        private string _fileName;
        private string _exportPath;

        #endregion // fields

        #region ctor

        /// <summary>
        /// Constructor with initialization
        /// </summary>
        public ExportTypeVersionViewModel(ISettingsService settingsService)
        {
            CanCloseDialog = true;

            _settingsService = settingsService;

            FileNameTextChangedCommand = new DelegateCommand<object>(FileNameTextChanged);
            ExportPathChangedCommand = new DelegateCommand<object>(PathChanged);
            SelectTargetDirectoryCommand = new DelegateCommand(SelectTargetDirectory);

            ExportVersionCommand = new DelegateCommand(ExportVersion);
            CancelCommand = new DelegateCommand(CancelDialog);

            ExportPath = _settingsService.GetExportPath();
        }

        #endregion // ctor

        #region commands

        /// <summary>
        /// Command to handle input changes for the project name
        /// </summary>
        public DelegateCommand<object> FileNameTextChangedCommand { get; }

        /// <summary>
        /// Command to handle input changes for the target directory
        /// </summary>
        public DelegateCommand<object> ExportPathChangedCommand { get; }

        /// <summary>
        /// Command to open folder browser to select the target directory
        /// </summary>
        public DelegateCommand SelectTargetDirectoryCommand { get; }

        /// <summary>
        /// Command to confirm the input and create a new project
        /// </summary>
        public DelegateCommand ExportVersionCommand { get; }

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
        public string Title => "Export type version";

        /// <summary>
        /// Project name
        /// </summary>
        public string FileName
        {
            get => _fileName;
            set => SetProperty(ref _fileName, value);
        }

        /// <summary>
        /// Path of the target directory as string
        /// </summary>
        public string ExportPath
        {
            get => _exportPath;
            set => SetProperty(ref _exportPath, value);
        }

        /// <summary>
        /// Indicates an validation error of the project name
        /// </summary>
        public bool FileNameValidationError
        {
            get;
            set;
        }

        /// <summary>
        /// Indicates an validation error of the target directory path
        /// </summary>
        public bool PathValidationError
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

        private void FileNameTextChanged(object obj)
        {
            FileNameValidationError = false;
            CanCloseDialog = true;
        }

        private void PathChanged(object obj)
        {
            PathValidationError = false;
            CanCloseDialog = true;
        }

        /// <summary>
        /// Determine the path of the target directory 
        /// </summary>
        private void SelectTargetDirectory()
        {
            var folderSearch = new FolderBrowserDialog();
            folderSearch.SelectedPath = _settingsService.GetProjectPath();

            if (System.Windows.Forms.DialogResult.OK == folderSearch.ShowDialog())
            {
                ExportPath = folderSearch.SelectedPath;
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
                FileNameValidationError = false || string.IsNullOrEmpty(FileName);
            }
            catch (Exception exception)
            {
                ExceptionOccurred = true;
                MessageBox.Show(exception.Message, @"Exception", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }

            try
            {
                PathValidationError = string.IsNullOrEmpty(ExportPath) || Directory.Exists(ExportPath) == false;
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
        private void ExportVersion()
        {
            DialogResult = true;

            ValidationProvider();

            if (FileNameValidationError || PathValidationError)
            {
                CanCloseDialog = false;
                MessageBox.Show(@"File name and valid path are both required!", @"Validation Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }

            FileInfo exportFileFullPath = new FileInfo(Path.Combine(ExportPath, FileName));
            if (exportFileFullPath != null && exportFileFullPath.Exists)
            {
                CanCloseDialog = false;
                DialogResult = false;
                MessageBox.Show($@"File {exportFileFullPath.FullName} already exists! Please change the export file name or delete the existing file before export.", @"Validation Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
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
            FileName = string.Empty;
            ExportPath = string.Empty;
            FileNameValidationError = false;
            PathValidationError = false;
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
