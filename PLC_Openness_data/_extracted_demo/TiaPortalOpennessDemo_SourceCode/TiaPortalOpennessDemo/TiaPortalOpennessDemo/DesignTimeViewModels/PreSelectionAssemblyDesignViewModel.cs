using System.Collections.ObjectModel;
using System.ComponentModel;
using TiaPortalOpennessDemo.ViewModels;

namespace TiaPortalOpennessDemo.DesignTimeViewModels
{
    /// <summary>
    /// PreSelectionAssemblyDesignViewModel for design time only.
    /// </summary>
    [DesignOnly(true)]
    public class PreSelectionAssemblyDesignViewModel : PreSelectionAssemblyVersionViewModel
    {
        #region ctor

        /// <summary>
        /// Constructor for design time only.
        /// </summary>
        [DesignOnly(true)]
        public PreSelectionAssemblyDesignViewModel()
            : base(new ObservableCollection<string> { "15.0", "16.0", "17.0" }, new ObservableCollection<string> { "15.0", "16.0", "17.0" }, true)
        {

        }

        #endregion // ctor
    }
}
