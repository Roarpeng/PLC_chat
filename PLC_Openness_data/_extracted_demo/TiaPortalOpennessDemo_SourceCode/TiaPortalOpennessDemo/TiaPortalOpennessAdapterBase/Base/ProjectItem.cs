using System;
using System.Collections.Generic;
using TiaPortalOpennessAdapterBase.Enums;

namespace TiaPortalOpennessAdapterBase.Base
{
    /// <summary>
    /// 
    /// </summary>
    public class ProjectItem
    {
        /// <summary>
        /// Name of an item for display
        /// </summary>
        public string Header { get; set; }

        /// <summary>
        /// Guid as identifier
        /// </summary>
        public Guid Tag { get; set; }

        /// <summary>
        /// Device item object
        /// </summary>
        public object DeviceItem { get; set; }

        /// <summary>
        /// Type info in the tree
        /// </summary>
        public TreeTypeInformation TypeInfo { get; set; }

        /// <summary>
        /// List of sub items
        /// </summary>
        public IList<ProjectItem> ProjectItems
        {
            get;
            set;
        }

        /// <summary>
        /// Default constructor
        /// </summary>
        public ProjectItem()
        {
            ProjectItems = new List<ProjectItem>();
        }
    }
}
