using ContentModule.ViewModels;
using System.Collections.Generic;
using System.ComponentModel;

namespace ContentModule.DesignTimeViewModels
{
    /// <summary>
    /// AboutInfoDesignTimeViewModel for design time only.
    /// </summary>
    [DesignOnly(true)]
    class ContentDesignTimeViewModel : ContentViewModel
    {
        #region ctor

        /// <summary>
        /// Constructor for design time only.
        /// </summary>
        [DesignOnly(true)]
        public ContentDesignTimeViewModel()
            : base(new Dictionary<string, string>() { { "Element name xy", "Content xy" }, { "Element z", "Content z" } })
        {

        }

        #endregion // ctor
    }

}
