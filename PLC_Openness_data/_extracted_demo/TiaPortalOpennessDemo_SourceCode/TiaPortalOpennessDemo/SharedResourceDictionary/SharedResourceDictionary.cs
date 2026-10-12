#define GLOBAL_USE_SHAREDRESOURCEDICTIONARY

using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Windows;

namespace SharedResourceDictionary.Shared
{
    /// <summary>
    /// Implementation of shared resource dictionary to prevent multiple instantiation of the 
    /// recourse dictionaries they are used in multiple user controls.
    /// 
    /// Definition of the custom namespace in the 'AssemblyInfo.cs' for accessing the resource dictionaries they are
    /// defined in the 'TiaPortalOpennessDemoStyling' assembly.
    /// 
    /// // Custom namespace for access to resources in other modules
    /// [assembly: XmlnsDefinition("http://schemas.microsoft.com/winfx/2006/xaml/presentation", "SharedResourceDictionary.Shared")]
    /// </summary>
    public class SharedResourceDictionary : ResourceDictionary
    {
#if GLOBAL_USE_SHAREDRESOURCEDICTIONARY

        /// <summary>
        /// The internal cache of loaded dictionaries
        /// </summary>
        private static readonly Dictionary<Uri, ResourceDictionary> sharedDictionary = new Dictionary<Uri, ResourceDictionary>();

        /// <summary>
        /// local member of the uniform resource identifier (uri)
        /// </summary>
        private Uri sharedSourceUri;

        /// <summary>
        /// Indicates if in design mode
        /// </summary>
        private static bool IsInDesignMode =>
            (bool)DependencyPropertyDescriptor
                .FromProperty(DesignerProperties.IsInDesignModeProperty, typeof(DependencyObject)).Metadata
                .DefaultValue;

        /// <summary>
        /// Gets or sets the uniform resource identifier (uri) to load from.
        /// </summary>
        public new Uri Source
        {
            get => sharedSourceUri;
            set
            {
                sharedSourceUri = value;
                if (!sharedDictionary.ContainsKey(value))
                {
                    try
                    {
                        base.Source = value;
                    }
                    catch (Exception)
                    {
                        // only throw an exception at runtime
                        if (!IsInDesignMode)
                        {
                            throw;
                        }
                    }

                    sharedDictionary.Add(value, this);
                }
                else
                {
                    MergedDictionaries.Add(sharedDictionary[value]);
                }
            }
        }

#endif
    }
}
