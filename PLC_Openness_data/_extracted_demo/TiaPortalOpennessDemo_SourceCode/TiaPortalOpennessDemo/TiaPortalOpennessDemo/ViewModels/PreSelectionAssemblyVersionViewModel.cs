using Prism.Commands;
using Prism.Mvvm;
using System;
using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Linq;
using System.Windows;
using TiaPortalOpennessAdapter.Utils;
using TiaPortalOpennessCore.Contracts;
using TiaPortalOpennessDemo.Properties;
using TiaPortalOpennessInfrastructure.Constants;

namespace TiaPortalOpennessDemo.ViewModels
{
    /// <summary>
    /// Provides the possibility to select the assembly versions to be used.
    /// </summary>
    public class PreSelectionAssemblyVersionViewModel : BindableBase, ICloseWindow
    {
        #region fields

        private ObservableCollection<string> _engineeringVersions;
        private ObservableCollection<string> _opennessApiVersions;

        private string                       _selectedEngineeringVersion;
        private string                       _selectedOpennessApiVersion;

        private bool?                        _dialogResult;
        private bool                         _hidePreSelectionAssemblyVersionDialog;
        private bool                         _canCloseDialog;

        #endregion // fields

        #region ctor

        /// <summary>
        /// Constructor with default initialization.
        /// </summary>
        public PreSelectionAssemblyVersionViewModel()
        {
            CanCloseDialog = true;

            ConfirmationCommand = new DelegateCommand(ConfirmAndCloseWindow);

            _engineeringVersions = new ObservableCollection<string>();
            _opennessApiVersions = new ObservableCollection<string>();

            GetEngineeringVersions();
        }

        /// <summary>
        ///  Constructor for design time only.
        /// </summary>
        /// <param name="engineeringVersions">Sample data</param>
        /// <param name="opennessApiVersions">Sample data</param>
        /// <param name="hidePreSelectionAssemblyVersionDialog">Sample data</param>
        [DesignOnly(true)]
        internal PreSelectionAssemblyVersionViewModel(ObservableCollection<string> engineeringVersions, ObservableCollection<string> opennessApiVersions, bool hidePreSelectionAssemblyVersionDialog)
        {
            try
            {
                _engineeringVersions                   = engineeringVersions;
                _opennessApiVersions                   = opennessApiVersions;
                _hidePreSelectionAssemblyVersionDialog = hidePreSelectionAssemblyVersionDialog;

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
        /// Command to confirm the selection an close the dialog.
        /// </summary>
        public DelegateCommand ConfirmationCommand { get; }

        #endregion // commands

        #region actions

        /// <summary>
        /// Action will be executed when closing the dialog.
        /// </summary>
        public Action Close { get; set; }

        #endregion // actions

        #region properties

        /// <summary>
        /// Determine if the call is at design time.
        /// </summary>
        public static bool IsDesignTime => (LicenseManager.UsageMode == LicenseUsageMode.Designtime);

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
        public string Title => "Pre selection assembly versions";

        /// <summary>
        /// The result of the dialog.
        /// </summary>
        public bool? DialogResult
        {
            get => _dialogResult;
            set => SetProperty(ref _dialogResult, value);
        }

        /// <summary>
        /// Indicates the visibility of the dialog.
        /// That means, will be the dialog, on start of the demo application, displayed or not.
        /// </summary>
        public bool HidePreSelectionAssemblyVersionDialog
        {
            get => _hidePreSelectionAssemblyVersionDialog;
            set => SetProperty(ref _hidePreSelectionAssemblyVersionDialog, value);
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

        #endregion // properties

        #region methods

        /// <summary>
        /// Retrieving the installed versions of the engineering dll.
        /// </summary>
        private void GetEngineeringVersions()
        {
            EngineeringVersions = new ObservableCollection<string>(Resolver.GetEngineeringVersions());
            if (EngineeringVersions != null && EngineeringVersions.Count > 0)
            {
                SelectedEngineeringVersion = (from item in EngineeringVersions
                                              where item == Settings.Default.SelectedEngineeringVersion
                                              select item).FirstOrDefault();

                if (string.IsNullOrEmpty(SelectedEngineeringVersion))
                {
                    SelectedEngineeringVersion = EngineeringVersions.FirstOrDefault();
                }
            }
            else
            {
                ConfirmAndCloseWindow();
            }
        }

        /// <summary>
        /// Retrieving the installed versions of the openness api
        /// </summary>
        private void GetOpennessApiVersions()
        {
            if (string.IsNullOrEmpty(SelectedEngineeringVersion)) return;
            OpennessApiVersions = new ObservableCollection<string>(Resolver.GetAssemblies(SelectedEngineeringVersion));
            if (OpennessApiVersions != null && OpennessApiVersions.Count > 0)
            {
                SelectedOpennessApiVersion = (from item in OpennessApiVersions
                                              where item == Settings.Default.SelectedOpennessApiVersion
                                              select item).FirstOrDefault();

                if (string.IsNullOrEmpty(SelectedOpennessApiVersion))
                {
                    SelectedOpennessApiVersion = string.Empty;
                }
            }
            else
            {
                ConfirmAndCloseWindow();
            }
        }

        /// <summary>
        /// Storing the selected assembly versions and the visibility flag to be used.
        /// After storing will be invoke the Close method of the dialog.
        /// </summary>
        private void ConfirmAndCloseWindow()
        {
            Settings.Default.SelectedEngineeringVersion      = SelectedEngineeringVersion;
            Settings.Default.SelectedOpennessApiVersion      = SelectedOpennessApiVersion;
            Settings.Default.HidePreSelectionAssemblyVersion = HidePreSelectionAssemblyVersionDialog;
            Settings.Default.Save();

            Close?.Invoke();
        }

        /// <summary>
        /// Before the Close method, CanClose will be executed and the selection is checked.
        /// Is any wrong, the dialog can't be closed.
        /// </summary>
        /// <returns></returns>
        public bool CanClose()
        {
            if (EngineeringVersions.Count > 0)
            {
                if (OpennessApiVersions.Count > 0 && string.IsNullOrEmpty(SelectedOpennessApiVersion))
                {
                    MessageBox.Show("Please select an openness api version before press confirm.", "Error", MessageBoxButton.OK, MessageBoxImage.Error);
                    _canCloseDialog = false;
                }
                else
                {
                    DialogResult = true;
                    _canCloseDialog = true;
                }
            }
            else
            {
                DialogResult = false;
            }

            return _canCloseDialog;
        }

        #endregion // methods
    }
}
