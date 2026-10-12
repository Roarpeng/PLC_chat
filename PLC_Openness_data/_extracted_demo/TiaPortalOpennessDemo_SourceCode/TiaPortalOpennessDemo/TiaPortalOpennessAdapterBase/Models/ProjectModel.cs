using System.IO;
using TiaPortalOpennessAdapterBase.Base;

namespace TiaPortalOpennessAdapterBase.Models
{
    /// <summary>
    /// Implementation of Project model to decouple api form application
    /// </summary>
    public class ProjectModel : ObservableObject
    {
        #region fields

        private bool          _projectOpened;
        private string        _projectName;
        private DirectoryInfo _targetDirectory;

        private Tree          _logicalTree;
        private Tree          _physicalTree;

        private Tree          _projectLibraryTree;
        private Tree          _globalLibraryTree;

        #endregion // fields

        #region ctor

        #endregion // ctor

        #region properties

        /// <summary>
        /// Indicates if the project is open
        /// </summary>
        public bool ProjectOpened
        {
            get => _projectOpened;
            set => SetProperty(ref _projectOpened, value);
        }

        /// <summary>
        /// The name of the project
        /// </summary>
        public string ProjectName
        {
            get => _projectName;
            set => SetProperty(ref _projectName, value);
        }

        /// <summary>
        /// The target directory of the project
        /// </summary>
        public DirectoryInfo TargetDirectory
        {
            get => _targetDirectory;
            set => SetProperty(ref _targetDirectory, value);
        }

        //public ProjectContent ProjectContent
        //{
        //    get;
        //    set;
        //}

        /// <summary>
        /// The project tree (engineering tree)
        /// </summary>
        public Tree ProjectTree
        {
            get;
            set;
        }

        /// <summary>
        /// Logical tree (decoupled tree)
        /// </summary>
        public Tree LogicalTree
        {
            get => _logicalTree;
            set => SetProperty(ref _logicalTree, value);
        }

        /// <summary>
        /// Physical tree (decoupled tree)
        /// </summary>
        public Tree PhysicalTree
        {
            get => _physicalTree;
            set => SetProperty(ref _physicalTree, value);
        }

        /// <summary>
        /// Project library tree (decoupled)
        /// </summary>
        public Tree ProjectLibraryTree
        {
            get => _projectLibraryTree;
            set => SetProperty(ref _projectLibraryTree, value);
        }

        /// <summary>
        /// Global library tree (decoupled)
        /// </summary>
        public Tree GlobalLibraryTree
        {
            get => _globalLibraryTree;
            set => SetProperty(ref _globalLibraryTree, value);
        }
        #endregion // properties

        #region methods

        #endregion // methods

    }
}
