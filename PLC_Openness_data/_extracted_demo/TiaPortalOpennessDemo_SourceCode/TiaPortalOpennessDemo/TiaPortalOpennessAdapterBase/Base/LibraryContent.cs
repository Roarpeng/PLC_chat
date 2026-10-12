using System.Collections.Generic;

namespace TiaPortalOpennessAdapterBase.Base
{
    /// <summary>
    /// Library content definition
    /// </summary>
    public class LibraryContent
    {
        /// <summary>
        /// Default constructor with initialization
        /// </summary>
        public LibraryContent()
        {
            LibraryItems = new List<LibraryItem>();
        }

        /// <summary>
        /// List of library items
        /// </summary>
        public IList<LibraryItem> LibraryItems { get; set; }

        /// <summary>
        /// Add item to list
        /// </summary>
        /// <param name="libraryItem"></param>
        public void Add(LibraryItem libraryItem)
        {
            LibraryItems.Add(libraryItem);
        }
    }
}
