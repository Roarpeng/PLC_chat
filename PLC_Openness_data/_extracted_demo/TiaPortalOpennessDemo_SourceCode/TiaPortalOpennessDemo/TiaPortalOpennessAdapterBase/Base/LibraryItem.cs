using System;
using System.Collections.Generic;
using TiaPortalOpennessAdapterBase.Enums;

namespace TiaPortalOpennessAdapterBase.Base
{
    /// <summary>
    /// Library item meta data definition
    /// </summary>
    public class LibraryItem
    {
        /// <summary>
        /// Name of an item for display in the tree
        /// </summary>
        public string Header { get; set; }

        /// <summary>
        /// Guid as identifier 
        /// </summary>
        public Guid Tag { get; set; }

        /// <summary>
        /// The item object
        /// </summary>
        public object Item { get; set; }

        /// <summary>
        /// Type info in the tree
        /// </summary>
        public TreeTypeInformation TypeInfo { get; set; }

        /// <summary>
        /// List of sub items
        /// </summary>
        public IList<LibraryItem> LibraryItems
        {
            get;
            set;
        }

        /// <summary>
        /// Default constructor
        /// </summary>
        public LibraryItem()
        {
            LibraryItems = new List<LibraryItem>();
        }
    }
}
