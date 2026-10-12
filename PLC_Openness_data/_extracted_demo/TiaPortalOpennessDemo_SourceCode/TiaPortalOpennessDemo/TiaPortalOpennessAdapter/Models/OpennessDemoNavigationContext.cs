using TiaPortalOpennessAdapterContracts;
using TiaPortalOpennessInfrastructure.Constants;

namespace TiaPortalOpennessAdapter.Models
{
    /// <summary>
    /// Define meta data for navigation 
    /// </summary>
    public class OpennessDemoNavigationContext : IOpennessDemoNavigationContext
    {
        #region fields

        #endregion // fields

        #region ctor

        /// <summary>
        /// Default constructor with initialization
        /// </summary>
        public OpennessDemoNavigationContext()
        {
            IsLocalSession = false;
            ShowLogicalTree = true;
            NavigationTarget = NavigationNames.DefaultTreeNavigation;
        }

        #endregion // ctor

        #region properties

        /// <summary>
        /// Indicates if process is a local session
        /// </summary>
        public bool IsLocalSession { get; set; }

        /// <summary>
        /// Indicates if the logical tree should be display
        /// </summary>
        public bool ShowLogicalTree { get; set; }

        /// <summary>
        /// The name of the navigation target (region)
        /// </summary>
        public string NavigationTarget { get; set; }

        #endregion // properties
    }
}
