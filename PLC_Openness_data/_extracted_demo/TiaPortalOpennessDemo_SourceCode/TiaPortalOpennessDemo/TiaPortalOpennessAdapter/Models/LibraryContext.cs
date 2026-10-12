using TiaPortalOpennessAdapterContracts;

namespace TiaPortalOpennessAdapter.Models
{
    /// <summary>
    /// Definition of library context
    /// </summary>
    public class LibraryContext : ILibraryContext
    {
        #region fields

        #endregion // fields

        #region ctor

        /// <summary>
        /// Constructor with parameter for initialization
        /// </summary>
        /// <param name="navigationContext"></param>
        /// <param name="libraryItem"></param>
        public LibraryContext(IOpennessDemoNavigationContext navigationContext, object libraryItem)
        {
            NavigationContext = navigationContext;
            LibraryItem = libraryItem;
        }

        #endregion // ctor

        /// <summary>
        /// Navigation context defines the context of use
        /// </summary>
        public IOpennessDemoNavigationContext NavigationContext { get; set; }

        /// <summary>
        /// Library item to be used
        /// </summary>
        public object LibraryItem { get; set; }
    }
}
