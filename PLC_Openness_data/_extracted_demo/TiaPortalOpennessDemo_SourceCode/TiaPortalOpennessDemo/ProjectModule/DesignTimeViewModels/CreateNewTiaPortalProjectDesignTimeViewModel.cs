using ProjectModule.ViewModels;
using System.ComponentModel;

namespace ProjectModule.DesignTimeViewModels
{
    /// <summary>
    /// SettingsEditorDesignTimeViewModel for design time only.
    /// </summary>
    [DesignOnly(true)]
    public class CreateNewTiaPortalProjectDesignTimeViewModel : CreateNewTiaPortalProjectViewModel
    {
        /// <summary>
        /// Constructor for design time only.
        /// </summary>
        [DesignOnly(true)]
        public CreateNewTiaPortalProjectDesignTimeViewModel()
            : base("Project name xy", @"C:\..\xy\..")
        {
        }
    }
}
