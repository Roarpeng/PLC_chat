extern alias V16_0;
using System;
using System.Collections.Generic;
using V16_0::Siemens.Engineering.Hmi.RuntimeScripting;
using V16_0::Siemens.Engineering.Hmi.Screen;
using V16_0::Siemens.Engineering.SW.Blocks;
using V16_0::Siemens.Engineering.SW.Types;

namespace TiaPortalOpennessAdapter.Models.V16_0
{
    /// <summary>
    /// Definition of dictionaries for mapping of library source to project destination and
    /// type collection to types.
    /// </summary>
    public static class CopyDestinationMapping
    {
        #region fields

        private static readonly Dictionary<Type, IList<Type>> DestinationContainerMappingDictionary;
        private static readonly Dictionary<Type, IList<Type>> DestinationMappingDictionary;

        #endregion // fields

        #region ctor

        /// <summary>
        /// static constructor
        /// </summary>
        static CopyDestinationMapping()
        {
            DestinationContainerMappingDictionary = new Dictionary<Type, IList<Type>>();
            DestinationContainerMappingDictionary.Add(typeof(CodeBlockLibraryType), new List<Type>() { typeof(PlcBlockUserGroup), typeof(PlcBlockSystemGroup) });
            DestinationContainerMappingDictionary.Add(typeof(PlcTypeLibraryType), new List<Type>() { typeof(PlcTypeUserGroup), typeof(PlcTypeSystemGroup) });
            DestinationContainerMappingDictionary.Add(typeof(ScreenLibraryType), new List<Type>() { typeof(ScreenUserFolder), typeof(ScreenSystemFolder) });
            DestinationContainerMappingDictionary.Add(typeof(VBScriptLibraryType), new List<Type>() { typeof(VBScriptUserFolder), typeof(VBScriptSystemFolder) });

            DestinationMappingDictionary = new Dictionary<Type, IList<Type>>();
            DestinationMappingDictionary.Add(typeof(PlcBlockUserGroup), new List<Type>() { typeof(FB), typeof(FC), typeof(OB), typeof(ArrayDB), typeof(GlobalDB), typeof(InstanceDB) });
            DestinationMappingDictionary.Add(typeof(PlcTypeUserGroup), new List<Type>() { typeof(PlcStruct) });
            DestinationMappingDictionary.Add(typeof(ScreenUserFolder), new List<Type>() { typeof(Screen) });
            DestinationMappingDictionary.Add(typeof(VBScriptUserFolder), new List<Type>() { typeof(VBScript) });
        }

        #endregion // ctor

        #region methods

        /// <summary>
        /// Get the list of destination container for a given library source.
        /// </summary>
        /// <param name="copySourceType"></param>
        /// <returns></returns>
        public static IList<Type> GetDestinationContainer(Type copySourceType)
        {
            DestinationContainerMappingDictionary.TryGetValue(copySourceType, out var destinationContainer);

            return destinationContainer;
        }

        /// <summary>
        /// Get the list of types for a given type collection (container).
        /// </summary>
        /// <param name="destinationContainerType"></param>
        /// <returns></returns>
        public static IList<Type> GetDestinationMapping(Type destinationContainerType)
        {
            DestinationMappingDictionary.TryGetValue(destinationContainerType, out var destinationType);

            return destinationType;
        }

        #endregion // methods
    }
}
