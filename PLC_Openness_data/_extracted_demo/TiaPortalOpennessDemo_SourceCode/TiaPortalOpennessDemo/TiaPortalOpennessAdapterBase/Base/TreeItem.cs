using System;
using System.Collections.Generic;
using System.IO;
using TiaPortalOpennessAdapterBase.Enums;

namespace TiaPortalOpennessAdapterBase.Base
{
    /// <summary>
    /// Tree item definition
    /// </summary>
    public class TreeItem
    {
        /// <summary>
        /// Level of the Item, used to expand automatically 
        /// </summary>
        public int Level { get; set; }

        /// <summary>
        /// Name of an item 
        /// </summary>
        public string Header { get; set; }

        /// <summary>
        /// Guid as identifier
        /// </summary>
        public Guid Tag { get; set; }

        ///// <summary>
        ///// 
        ///// </summary>
        //public string Comment { get; set; }

        /// <summary>
        /// Consistency Status
        /// </summary>
        public string Status { get; set; }

        ///// <summary>
        ///// 
        ///// </summary>
        //public string Version { get; set; }

        /// <summary>
        /// 
        /// </summary>
        public FileInfo Path { get; set; }

        /// <summary>
        /// 
        /// </summary>
        public TreeTypeInformation TypeInfo { get; set; }

        /// <summary>
        /// 
        /// </summary>
        public IList<TreeItem> Items
        {
            get;
            set;
        }

        /// <summary>
        /// 
        /// </summary>
        public TreeItem()
        {
            TypeInfo = TreeTypeInformation.IsOther;
            Items = new List<TreeItem>();
        }
    }
}
