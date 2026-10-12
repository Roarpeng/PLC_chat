using System.Collections.ObjectModel;
using System.ComponentModel;
using TiaPortalOpennessCore.ViewModels;

namespace TiaPortalOpennessCore.DesignTimeViewModels
{
    /// <summary>
    /// AboutInfoDesignTimeViewModel for design time only.
    /// </summary>
    [DesignOnly(true)]
    public class AboutInfoDesignTimeViewModel : AboutInfoViewModel
    {
        #region ctor

        /// <summary>
        /// Constructor for design time only.
        /// </summary>
        [DesignOnly(true)]
        public AboutInfoDesignTimeViewModel()
            : base(new ObservableCollection<string> { "Application Info: xyz", "App name xyz" })
        {

        }

        #endregion // ctor
    }

}
