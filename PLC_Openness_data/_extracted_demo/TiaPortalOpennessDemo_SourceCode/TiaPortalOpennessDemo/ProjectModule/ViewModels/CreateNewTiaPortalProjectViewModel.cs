using Prism.Commands;
using Prism.Mvvm;
using System;
using System.ComponentModel;
using System.IO;
using System.Windows.Forms;
using TiaPortalOpennessCore.Contracts;
using TiaPortalOpennessInfrastructure.Constants;
using TiaPortalOpennessInfrastructure.Contracts;

namespace ProjectModule.ViewModels
{
    /// <summary>
    /// View model for entering the information to create a new project
    /// </summary>
    public class CreateNewTiaPortalProjectViewModel : BindableBase, ICloseWindow
    {
        #region fields

        private readonly ISettingsService _settingsService;

        private bool?                     _dialogResult;
        private bool                      _canCloseDialog;
        private string                    _projectName;
        private string                    _path;

        #endregion // fields

        #region ctor

        /// <summary>
        /// Constructor with initialization
        /// </summary>
        public CreateNewTiaPortalProjectViewModel(ISettingsService settingsService)
        {
            CanCloseDialog                = false;

            _settingsService              = settingsService;
            if (_settingsService != null)
            {
                Path = _settingsService.GetProjectPath();
            }

            ProjectNameTextChangedCommand = new DelegateCommand<object>(ProjectNameTextChanged);
            PathChangedCommand            = new DelegateCommand<object>(PathChanged);
            SelectTargetDirectoryCommand  = new DelegateCommand(SelectTargetDirectory);

            CreateNewProjectCommand       = new DelegateCommand(CreateNewProject);
            CancelCommand                 = new DelegateCommand(CancelDialog);
        }

        /// <summary>
        /// Constructor for design time only.
        /// </summary>
        /// <param name="projectName"></param>
        /// <param name="path"></param>
        [DesignOnly(true)]
        internal CreateNewTiaPortalProjectViewModel(string projectName, string path)
        {
            try
            {
                ProjectName = projectName;
                Path = path;

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
        /// Command to handle input changes for the project name
        /// </summary>
        public DelegateCommand<object> ProjectNameTextChangedCommand { get; }

        /// <summary>
        /// Command to handle input changes for the target directory
        /// </summary>
        public DelegateCommand<object> PathChangedCommand { get; }

        /// <summary>
        /// Command to open folder browser to select the target directory
        /// </summary>
        public DelegateCommand SelectTargetDirectoryCommand { get; }

        /// <summary>
        /// Command to confirm the input and create a new project
        /// </summary>
        public DelegateCommand CreateNewProjectCommand { get; }

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
        public string Title => "Create new TIA Portal project";

        /// <summary>
        /// Project name
        /// </summary>
        public string ProjectName
        {
            get => _projectName;
            set => SetProperty(ref _projectName, value);
        }

        /// <summary>
        /// Path of the target directory as string
        /// </summary>
        public string Path
        {
            get => _path;
            set => SetProperty(ref _path, value);
        }

        /// <summary>
        /// Indicates an validation error of the project name
        /// </summary>
        public bool ProjectNameValidationError
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

        private void ProjectNameTextChanged(object obj)
        {
            ProjectNameValidationError = false;
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
                Path = folderSearch.SelectedPath;
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
                ProjectNameValidationError = false || string.IsNullOrEmpty(ProjectName);
            }
            catch (Exception exception)
            {
                ExceptionOccurred = true;
                MessageBox.Show(exception.Message, @"Exception", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }

            try
            {
                PathValidationError = string.IsNullOrEmpty(Path) || Directory.Exists(Path) == false;
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
        private void CreateNewProject()
        {
            DialogResult = true;

            ValidationProvider();

            if (ProjectNameValidationError || PathValidationError)
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
            ProjectName = string.Empty;
            Path = string.Empty;
            ProjectNameValidationError = false;
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
