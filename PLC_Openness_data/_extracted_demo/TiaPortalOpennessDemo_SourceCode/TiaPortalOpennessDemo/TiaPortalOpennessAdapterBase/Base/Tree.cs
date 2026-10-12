using System.Collections.Generic;

namespace TiaPortalOpennessAdapterBase.Base
{
    /// <summary>
    /// Tree definition
    /// </summary>
    public class Tree
    {
        /// <summary>
        /// Indicates if the node should be expand
        /// </summary>
        public bool ExpandSubTree
        {
            get;
            set;
        }

        /// <summary>
        /// List of sub items
        /// </summary>
        public IList<TreeItem> Items
        {
            get;
            set;
        }

        /// <summary>
        /// Default constructor
        /// </summary>
        public Tree()
        {
            Items = new List<TreeItem>();
        }
    }
}
