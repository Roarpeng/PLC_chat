using System.Collections.ObjectModel;
using System.ComponentModel;
using TiaPortalModule.ViewModels;
using TiaPortalOpennessAdapterBase.Enums;

namespace TiaPortalModule.DesignTimeViewModels
{
    /// <summary>
    /// SettingsEditorDesignTimeViewModel for design time only.
    /// </summary>
    [DesignOnly(true)]
    public class SettingsEditorDesignTimeViewModel : SettingsEditorViewModel
    {
        /// <summary>
        /// Constructor for design time only.
        /// </summary>
        [DesignOnly(true)]
        public SettingsEditorDesignTimeViewModel()
        : base(true, new ObservableCollection<string>() { "V17x", "V16x" }, "V17x", new ObservableCollection<string>() { "V17y", "V15y" }, "V15y", "C..//../Modules", "C..//../Projects", "C..//../GlobalUserLibrary", "C..//../LocalSession", "C..//../Export", true, false, TiaPortalStartMode.WithUserInterface, "33")
        {
        }
    }
}
