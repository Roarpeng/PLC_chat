using System;
using System.Reflection;
using TiaPortalOpennessAdapterBase.Models;

namespace TiaPortalOpennessAdapter.Models
{
    /// <summary>
    /// Definition of meta data for modules and options 
    /// </summary>
    public class TiaPortalModulesAndOptions : ObservableObject
    {
        #region fields

        private Assembly _assembly;
        private Type _moduleType;

        private string _assemblyName;
        private string _location;
        private string _engineeringDll;
        private string _versionInfo;
        private string _fileInfoFullName;

        private bool _isSelected;

        #endregion // fields

        #region properties

        /// <summary>
        /// Assembly (module or option)
        /// </summary>
        public Assembly Assembly
        {
            get => _assembly;
            set => SetProperty(ref _assembly, value);
        }

        /// <summary>
        /// exported type from module 
        /// </summary>
        public Type ModuleType
        {
            get => _moduleType;
            set => SetProperty(ref _moduleType, value);
        }

        /// <summary>
        /// Name of an assembly
        /// </summary>
        public string AssemblyName
        {
            get => _assemblyName;
            set => SetProperty(ref _assemblyName, value);
        }

        /// <summary>
        /// Path from where the module should be load
        /// </summary>
        public string Location
        {
            get => _location;
            set => SetProperty(ref _location, value);
        }

        /// <summary>
        /// The name of the engineering dll
        /// </summary>
        public string EngineeringDll
        {
            get => _engineeringDll;
            set => SetProperty(ref _engineeringDll, value);
        }

        /// <summary>
        /// The required engineering version
        /// </summary>
        public string VersionInfo
        {
            get => _versionInfo;
            set => SetProperty(ref _versionInfo, value);
        }

        /// <summary>
        /// Full name
        /// </summary>
        public string FileInfoFullName
        {
            get => _fileInfoFullName;
            set => SetProperty(ref _fileInfoFullName, value);
        }

        /// <summary>
        /// Indicates if an module or option is selected
        /// </summary>
        public bool IsSelected
        {
            get => _isSelected;
            set => SetProperty(ref _isSelected, value);
        }

        #endregion // properties
    }
}
