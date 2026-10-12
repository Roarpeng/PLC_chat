using Prism.Commands;
using Prism.Mvvm;
using System;
using System.Windows.Forms;
using TiaPortalOpennessCore.Contracts;

namespace LibraryModule.ViewModels
{
    public class GroupEditorViewModel : BindableBase, ICloseWindow
    {
        #region fields

        private bool? _dialogResult;
        private bool _canCloseDialog;
        private bool _createNewGroup;
        private string _title;
        private string _groupName;

        #endregion // fields

        #region ctor

        /// <summary>
        /// Constructor with initialization
        /// </summary>
        public GroupEditorViewModel()
        {
            CanCloseDialog = false;
            CreateNewGroup = false;

            GroupNameTextChangedCommand = new DelegateCommand<object>(GroupNameTextChanged);
            CommitGroupNameCommand = new DelegateCommand(CommitGroupName);
            CancelCommand = new DelegateCommand(CancelDialog);
        }

        #endregion // ctor

        #region commands

        /// <summary>
        /// Command to handle input changes for the project name
        /// </summary>
        public DelegateCommand<object> GroupNameTextChangedCommand { get; }

        /// <summary>
        /// Command to commit changes
        /// </summary>
        public DelegateCommand CommitGroupNameCommand { get; }

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

        public bool CreateNewGroup
        {
            get => _createNewGroup;
            set => SetProperty(ref _createNewGroup, value);
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
        public string Title
        {
            get => _title;
            set => SetProperty(ref _title, value);
        }

        /// <summary>
        /// Project name
        /// </summary>
        public string GroupName
        {
            get => _groupName;
            set => SetProperty(ref _groupName, value);
        }

        /// <summary>
        /// Indicates an validation error of the project name
        /// </summary>
        public bool GroupNameValidationError
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

        private void GroupNameTextChanged(object obj)
        {
            GroupNameValidationError = false;
            CanCloseDialog = true;
        }

        private void CommitGroupName()
        {
            DialogResult = true;

            ValidationProvider();

            if (GroupNameValidationError)
            {
                CanCloseDialog = false;
                MessageBox.Show(@"Group name are required!", @"Validation Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
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
        /// Validation the input
        /// </summary>
        private void ValidationProvider()
        {
            ExceptionOccurred = false;
            try
            {
                GroupNameValidationError = false || string.IsNullOrEmpty(GroupName);
            }
            catch (Exception exception)
            {
                ExceptionOccurred = true;
                MessageBox.Show(exception.Message, @"Exception", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        /// <summary>
        /// User has canceled, everything is fine
        /// </summary>
        private void CancelDialog()
        {
            GroupName = string.Empty;
            GroupNameValidationError = false;
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
