using System.Collections.Generic;

namespace TiaPortalOpennessAdapterBase.Base
{
    /// <summary>
    /// Project content definition
    /// </summary>
    public class ProjectContent
    {
        /// <summary>
        /// Default constructor
        /// </summary>
        public ProjectContent()
        {
            ProjectItems = new List<ProjectItem>();
        }

        /// <summary>
        /// List of project items
        /// </summary>
        public IList<ProjectItem> ProjectItems { get; set; }
    }
}
