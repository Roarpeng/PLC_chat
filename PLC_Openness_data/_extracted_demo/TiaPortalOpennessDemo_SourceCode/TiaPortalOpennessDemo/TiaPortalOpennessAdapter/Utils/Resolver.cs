using Microsoft.Win32;
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using TiaPortalOpennessAdapter.Models;
using TiaPortalOpennessInfrastructure.Utils;

namespace TiaPortalOpennessAdapter.Utils
{
    /// <summary>
    /// Definition of helper functionality to resolve api dll, modules and options
    /// </summary>
    public static class Resolver
    {

        /// <summary>
        /// Required min version of engineering dll
        /// </summary>
        public const string StrRequiredVersion     = "V15.0";
        private const string BasePath              = "SOFTWARE\\Siemens\\Automation\\Openness\\";
        private const string ReferencedAssembly    = "Siemens.Engineering";
        private const string ReferencedHmiAssembly = "Siemens.Engineering.Hmi";
        private const string ModuleBaseInterface   = "IOpennessBaseModule";
        private const string ModuleInterface       = "IOpennessModule";
        private static string _assemblyPath        = "";
        private static string _assemblyPathHmi     = "";

        /// <summary>
        /// Get version info from registry key
        /// </summary>
        /// <returns></returns>
        public static List<string> GetEngineeringVersions()
        {
            RegistryKey key = GetRegistryKey(BasePath);

            if (key != null)
            {
                try
                {
                    var names = key.GetSubKeyNames().OrderBy(x => x).ToList();

                    var result = (from item in names
                        where Convert.ToDecimal(item.Substring(0, 4)) >= Convert.ToDecimal(StrRequiredVersion.Substring(1, 4))
                        select item.Substring(0, 4)).ToList();

                    key.Dispose();

                    return result;
                }
                finally
                {
                    key.Dispose();
                }
            }

            return new List<string>();
        }

        /// <summary>
        /// Retrieve assembly by path and version
        /// </summary>
        /// <param name="version"></param>
        /// <returns></returns>
        public static List<string> GetAssemblies(string version)
        {
            RegistryKey key = GetRegistryKey(BasePath + version);

            if (key != null)
            {
                try
                {
                    var subKey = key.OpenSubKey("PublicAPI");

                    if (subKey != null)
                    {
                        var subKeys = subKey.GetSubKeyNames().OrderBy(x => x).ToList();

                        var result = (from item in subKeys
                                      where Convert.ToDecimal(item.Substring(0, 4)) >= Convert.ToDecimal(StrRequiredVersion.Substring(1, 4))
                                      select item.Substring(0, 4)).ToList();

                        subKey.Dispose();

                        return result;
                    }
                }
                finally
                {
                    key.Dispose();
                }
            }

            return new List<string>();
        }

        /// <summary>
        /// Retrieve the path from assembly by version
        /// </summary>
        /// <param name="version"></param>
        /// <param name="assembly"></param>
        /// <returns></returns>
        public static string GetAssemblyPath(string version, string assembly)
        {
            var libraries     = OpennessLibraries.GetOpennessLibraries();
            var portalVersion = new Version(version);
            var apiVersion    = new Version(assembly);
            _assemblyPath     = libraries.Where(e => e.TiaPortalVersion.Major == portalVersion.Major &&
                                                     e.TiaPortalVersion.Minor == portalVersion.Minor).SingleOrDefault(e => e.PublicApiVersion.Major == apiVersion.Major && 
                                                                                                                           e.PublicApiVersion.Minor == apiVersion.Minor)?.LibraryFilePath;

            return null;
        }

        private static RegistryKey GetRegistryKey(string keyName)
        {
            RegistryKey baseKey = RegistryKey.OpenBaseKey(RegistryHive.LocalMachine, RegistryView.Registry64);
            RegistryKey key     = baseKey.OpenSubKey(keyName);
            if (key == null)
            {
                baseKey.Dispose();
                baseKey = RegistryKey.OpenBaseKey(RegistryHive.LocalMachine, RegistryView.Default);
                key     = baseKey.OpenSubKey(keyName);
            }
            if (key == null)
            {
                baseKey.Dispose();
                baseKey = RegistryKey.OpenBaseKey(RegistryHive.LocalMachine, RegistryView.Registry32);
                key     = baseKey.OpenSubKey(keyName);
            }
            baseKey.Dispose();

            return key;
        }

        /// <summary>
        /// Resolve assembly by name
        /// </summary>
        /// <param name="sender"></param>
        /// <param name="args"></param>
        /// <returns></returns>
        public static Assembly OnResolve(object sender, ResolveEventArgs args)
        {
            var assemblyName = new AssemblyName(args.Name);
            string path      = "";

            if (assemblyName.Name.Equals(ReferencedAssembly))
                path = _assemblyPath;
            if (assemblyName.Name.Equals(ReferencedHmiAssembly))
                path = _assemblyPathHmi;

            bool okay = string.IsNullOrEmpty(path) == false && File.Exists(path);
            if (okay)
            {
                try
                {
                    var opennessName = AssemblyName.GetAssemblyName(path);
                    var asm = Assembly.Load(opennessName);
                    return asm;

                }
                catch (Exception e)
                {
                    Console.WriteLine(e);
                    throw;
                }
            }
            return null;
        }

        /// <summary>
        /// Check if openness api is installed
        /// </summary>
        /// <returns></returns>
        public static bool IsOpennessInstalled()
        {
            return !string.IsNullOrEmpty(GetLibraryFilePath());
        }

        private static string GetLibraryFilePath()
        {
            var engineeringVersion = GetEngineeringVersions();

            var requiredVersion = (from version in engineeringVersion
                                    where Convert.ToDecimal(version) >= Convert.ToDecimal(StrRequiredVersion.Substring(1, 4))
                                    select version).FirstOrDefault();

            return requiredVersion;
        }

        /// <summary>
        /// Retrieve assemblies by path 
        /// </summary>
        /// <param name="path"></param>
        /// <param name="version"></param>
        /// <returns></returns>
        public static IList<TiaPortalModulesAndOptions> GetAssembliesByPath(string path, string version)
        {
            IList<TiaPortalModulesAndOptions> moduleList = new List<TiaPortalModulesAndOptions>();
            var dirInfo   = new DirectoryInfo(path);
            var fileInfos = dirInfo.GetFiles("*.dll");

            foreach (var fileInfo in fileInfos)
            {
                var engineeringDll = string.Empty;
                var versionInfo    = string.Empty;
                var result         = new Type[0];

                try
                {
                    var nextAssembly = Assembly.ReflectionOnlyLoadFrom(fileInfo.FullName);

                    // check if the assembly references the engineering dll in the required version
                    foreach (var referencedAssembly in nextAssembly.GetReferencedAssemblies())
                    {
                        var referencedVersion = referencedAssembly.Version.Major + "." + referencedAssembly.Version.Minor;
                        if (referencedAssembly.Name == ReferencedAssembly && referencedVersion == version)
                        {
                            Assembly.ReflectionOnlyLoadFrom(_assemblyPath);
                            engineeringDll = referencedAssembly.Name;
                            versionInfo    = referencedAssembly.Version.Major + "." + referencedAssembly.Version.Minor;
                            // get the exported types for the required version
                            result         = nextAssembly.GetExportedTypes();

                            break;
                        }
                    }

                    if (result.Length > 0)
                    {
                        foreach (var typeInfo in result)
                        {
                            //try
                            //{
                            if (typeInfo != null)
                            {
                                // check for required interfaces and add module to list
                                foreach (var implementedInterface in typeInfo.GetInterfaces())
                                {
                                    if (implementedInterface.Name == ModuleInterface ||
                                        implementedInterface.Name == ModuleBaseInterface)
                                    {
                                        moduleList.Add(new TiaPortalModulesAndOptions()
                                        {
                                            Assembly         = nextAssembly,
                                            AssemblyName     = typeInfo.Name,
                                            ModuleType       = typeInfo,
                                            Location         = nextAssembly.Location,
                                            EngineeringDll   = engineeringDll,
                                            VersionInfo      = versionInfo,
                                            FileInfoFullName = fileInfo.FullName,
                                            IsSelected       = false
                                        });
                                    }
                                }
                            }
                            //}
                            //catch (Exception)
                            //{

                            //}
                        }
                    }
                }
                catch (BadImageFormatException)
                {
                    // It's not a TIA Portal Openness Module... -> ignore
                }
                catch (ReflectionTypeLoadException ex)
                {
                    StringBuilder stringBuilder = new StringBuilder();

                    foreach (var exSub in ex.LoaderExceptions)
                    {
                        stringBuilder.AppendLine(exSub.Message);
                        FileNotFoundException fileNotFoundException = exSub as FileNotFoundException;

                        if (fileNotFoundException != null)
                        {
                            if (!string.IsNullOrEmpty(fileNotFoundException.FusionLog))
                            {
                                stringBuilder.AppendLine("Fusion Log:");
                                stringBuilder.AppendLine(fileNotFoundException.FusionLog);
                            }
                        }

                        stringBuilder.AppendLine();
                    }
                }
            }
            return moduleList;
        }
    }
}
