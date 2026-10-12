using System.IO;

namespace TiaPortalOpennessAdapterBase.Models
{
    /// <summary>
    /// Library info definition
    /// </summary>
    public class LibraryInfo : ObservableObject
    {
        #region fields

        private bool     _isOpen;
        private string   _libraryName;
        private FileInfo _fileInfo;

        #endregion // fields

        #region ctor

        #endregion // ctor

        #region properties

        /// <summary>
        /// Indicates if the library is open
        /// </summary>
        public bool IsOpen
        {
            get => _isOpen;
            set => SetProperty(ref _isOpen, value);
        }

        /// <summary>
        /// The name of the library
        /// </summary>
        public string LibraryName
        {
            get => _libraryName;
            set => SetProperty(ref _libraryName, value);
        }

        /// <summary>
        /// File info object for the library
        /// </summary>
        public FileInfo FileInfo
        {
            get => _fileInfo;
            set => SetProperty(ref _fileInfo, value);
        }

        #endregion // properties

    }
}
