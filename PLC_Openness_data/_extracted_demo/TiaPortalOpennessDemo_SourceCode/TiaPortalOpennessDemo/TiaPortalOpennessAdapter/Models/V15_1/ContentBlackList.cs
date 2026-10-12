using System.Collections.Generic;

namespace TiaPortalOpennessAdapter.Models.V15_1
{
    /// <summary>
    /// Definition of an attribute list they values are not displayed
    /// </summary>
    public static class ContentBlackList
    {
        /// <summary>
        /// Attribute list
        /// </summary>
        public static IList<string> AttributeInfoBlackList;

        /// <summary>
        /// static constructor
        /// </summary>
        static ContentBlackList()
        {
            AttributeInfoBlackList = new List<string>()
            {
                "Comment",
                "CommentML",
                "Parent",
                "Container",
                "Items",
                "UnpluggedItems"
            };
        }
    }
}
