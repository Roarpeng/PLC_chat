using System.Collections.ObjectModel;
using System.ComponentModel;
using TiaPortalOpennessAdapter.Models;
using TiaPortalOpennessDemo.ViewModels;

namespace TiaPortalOpennessDemo.DesignTimeViewModels
{
    /// <summary>
    /// PreConfigurationDesignViewModel for design time only.
    /// </summary>
    [DesignOnly(true)]
    public class PreConfigurationDesignViewModel : PreConfigurationEnvironmentViewModel
    {
        #region ctor

        /// <summary>
        /// Constructor for design time only.
        /// </summary>
        [DesignOnly(true)]
        public PreConfigurationDesignViewModel()
            : base(@"C:\..\Automation\..\Openness", new ObservableCollection<TiaPortalModulesAndOptions>()
            {
                new TiaPortalModulesAndOptions { IsSelected = true, AssemblyName = "Step7_xyz", EngineeringDll = "Siemens.xyz.dll", VersionInfo = "88.8"},
                new TiaPortalModulesAndOptions { IsSelected = false, AssemblyName = "WinCc_xyz", EngineeringDll = "Siemens.xyz.dll", VersionInfo = "99.9"}
            })
        {

        }

        #endregion // ctor
    }
}
