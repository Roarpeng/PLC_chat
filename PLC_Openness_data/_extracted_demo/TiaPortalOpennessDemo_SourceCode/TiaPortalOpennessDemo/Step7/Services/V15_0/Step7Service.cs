extern alias V15_0;
using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Windows;
using TiaPortalOpennessAdapter.Utils;
using TiaPortalOpennessAdapterContracts;
using TiaPortalOpennessInfrastructure.Contracts;
using TiaPortalOpennessInfrastructure.Exceptions;
using TiaPortalOpennessInfrastructure.Utils;
using V15_0::Siemens.Engineering;
using V15_0::Siemens.Engineering.HW;
using V15_0::Siemens.Engineering.HW.Features;
using V15_0::Siemens.Engineering.Library;
using V15_0::Siemens.Engineering.Library.MasterCopies;
using V15_0::Siemens.Engineering.Library.Types;
using V15_0::Siemens.Engineering.SW;
using V15_0::Siemens.Engineering.SW.Blocks;
using V15_0::Siemens.Engineering.SW.ExternalSources;
using V15_0::Siemens.Engineering.SW.Tags;
using V15_0::Siemens.Engineering.SW.Types;

namespace Step7.Services.V15_0
{
    /// <summary>
    /// Implementation of step 7 service
    /// </summary>
    public class Step7Service : IPlcSoftwareService
    {
        #region fields

        private ITraceLogService _traceLogService;

        #endregion // fields

        #region ctor

        public Step7Service(ITraceLogService traceLogService)
        {
            _traceLogService = traceLogService;
        }

        #endregion // ctor

        #region methods

        #region common

        /// <summary>
        /// Check item whether known
        /// </summary>
        /// <param name="item"></param>
        /// <returns></returns>
        public bool IsKnownObject(Type item)
        {
            bool known = item == typeof(PlcBlockUserGroup) ||
                         item == typeof(PlcBlock) ||
                         item.IsSubclassOf(typeof(PlcBlock)) ||
                         item == typeof(PlcTypeUserGroup) ||
                         item == typeof(PlcType) ||
                         item.IsSubclassOf(typeof(PlcType)) ||
                         item == typeof(PlcTagTableUserGroup) ||
                         item == typeof(PlcTagTable) ||
                         item.IsSubclassOf(typeof(PlcTagTable));

            return known;
        }

        /// <summary>
        /// Retrieve whether item is plc software
        /// </summary>
        /// <param name="item"></param>
        /// <returns></returns>
        public bool IsPlcSoftware(object item)
        {
            return item is PlcSoftware;
        }

        /// <summary>
        /// Retrieve whether item can be a structure import destination
        /// </summary>
        /// <param name="item"></param>
        /// <returns></returns>
        public bool IsPlcStructureDestination(object item)
        {
            bool result = item is PlcBlockSystemGroup ||
                          item is PlcBlockUserGroup ||
                          item is PlcTypeSystemGroup ||
                          item is PlcTypeUserGroup ||
                          item is PlcTagTableSystemGroup ||
                          item is PlcTagTableUserGroup ||
                          item is PlcExternalSourceSystemGroup;

            return result;
        }

        /// <summary>
        /// Retrieve whether item is plc unit system group
        /// </summary>
        /// <param name="item"></param>
        /// <returns></returns>
        public bool IsPlcUnitSystemGroup(object item)
        {
            // not supported
            return false;
        }

        /// <summary>
        /// Indicates if item can be export
        /// </summary>
        /// <param name="item"></param>
        /// <returns></returns>
        public bool CanExportExecute(object item)
        {
            return item is PlcSoftware;
        }

        #endregion // common

        #region import/export

        /// <summary>
        /// Import element
        /// </summary>
        /// <param name="destination"></param>
        /// <param name="importFileInfo"></param>
        /// <param name="option"></param>
        /// <returns></returns>
        public bool ImportElement(object destination, FileInfo importFileInfo, object option)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(Step7Service) + " - " + nameof(ImportElement) };
            WriteTraceLogProxy(processInfo.ProcessMessage + " try");
            bool result = false;

            try
            {
                if (destination == null)
                {
                    throw new ArgumentNullException(nameof(destination), "The import destination parameter for the import is null!");
                }

                if (!(destination is IEngineeringCompositionOrObject importDestination))
                {
                    throw new ArgumentException("The import destination parameter for the import isn't of type IEngineeringCompositionOrObject!", nameof(destination));
                }

                if (importFileInfo == null)
                {
                    throw new ArgumentNullException(nameof(importFileInfo), "The import file info is null!");
                }

                if (option == null)
                {
                    throw new ArgumentNullException(nameof(option), "The import option is null!");
                }

                if (!(option is ImportOptions importOption))
                {
                    throw new ArgumentNullException(nameof(option), "The import option parameter for the import isn't of type ImportOptions!");
                }


                var type = importDestination.GetType();
                var propertyInfos = type.GetProperties();

                foreach (var propertyInfo in propertyInfos)
                {
                    var propertyType = propertyInfo.PropertyType;
                    var propertyDeclaringType = propertyInfo.DeclaringType;

                    var methodInfos = propertyType.GetMethods();
                    var refMethods = new[] { "Import", "ImportScreenGlobalElements", "ImportScreenOverview" };

                    var meth = (from me in methodInfos
                                where refMethods.Contains(me.Name) && me.GetParameters().Length == 2
                                select me).ToList();

                    foreach (var methodInfo in meth)
                    {
                        IList<Type> parameterTypeReferenceList = new List<Type>() { typeof(FileInfo), typeof(ImportOptions) };
                        IList<Type> parameterTypeList = new List<Type>();

                        var parameters = methodInfo.GetParameters();
                        if (parameters.Length > 0)
                        {
                            foreach (var parameter in parameters)
                            {
                                parameterTypeList.Add(parameter.ParameterType);
                            }

                            if (parameterTypeList.SequenceEqual(parameterTypeReferenceList))
                            {
                                if (propertyDeclaringType != null)
                                {
                                    if (importDestination is PlcBlockGroup)
                                    {
                                        if (Path.GetExtension(importFileInfo.FullName).Equals(".xml"))
                                        {
                                            (importDestination as PlcBlockGroup).Blocks.Import(importFileInfo, importOption);
                                        }
                                        else
                                        {
                                            var currentDestination = importDestination as IEngineeringObject;
                                            while (!(currentDestination is PlcSoftware))
                                            {
                                                currentDestination = currentDestination.Parent;
                                            }
                                            var col = (currentDestination as PlcSoftware).ExternalSourceGroup.ExternalSources;

                                            var sourceName = Path.GetRandomFileName();
                                            sourceName = Path.ChangeExtension(sourceName, ".src");
                                            var src = col.CreateFromFile(sourceName, importFileInfo.FullName);
                                            src.GenerateBlocksFromSource();
                                            src.Delete();
                                        }
                                        result = true;
                                    }
                                    else if (importDestination is PlcExternalSourceGroup)
                                    {
                                        var temp = (importDestination as PlcExternalSourceGroup).ExternalSources.Find(Path.GetFileName(importFileInfo.FullName));
                                        temp?.Delete();
                                        (importDestination as PlcExternalSourceGroup).ExternalSources.CreateFromFile(Path.GetFileName(importFileInfo.FullName), importFileInfo.FullName);
                                        result = true;
                                    }
                                    else if (importDestination is PlcTagTableGroup)
                                    {
                                        (importDestination as PlcTagTableGroup).TagTables.Import(importFileInfo, importOption);
                                        result = true;
                                    }
                                    else if (importDestination is PlcTypeGroup)
                                    {
                                        (importDestination as PlcTypeGroup).Types.Import(importFileInfo, importOption);
                                        result = true;
                                    }
                                }
                            }
                        }
                    }
                }

                return result;
            }
            catch (EngineeringException engineeringException)
            {
                throw OpennessApiExceptionHandler.CatchedEngineeringException(engineeringException);
            }
            catch (NonRecoverableException nonRecoverableException)
            {
                throw OpennessApiExceptionHandler.CatchedNonRecoverableException(nonRecoverableException);
            }
            catch (OpennessApiException)
            {
                throw;
            }
            catch (Exception exception)
            {
                throw OpennessApiExceptionHandler.CatchedException(exception);
            }
        }

        /// <summary>
        /// Import folder structure
        /// </summary>
        /// <param name="destination"></param>
        /// <param name="importFolderPath"></param>
        /// <param name="option"></param>
        /// <returns></returns>
        public bool ImportStructure(object destination, string importFolderPath, object option)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(Step7Service) + " - " + nameof(ImportStructure) };
            WriteTraceLogProxy(processInfo.ProcessMessage + " try");

            try
            {
                if (destination == null)
                {
                    throw new ArgumentNullException(nameof(destination), "The import destination parameter for the import is null!");
                }

                if (!(destination is IEngineeringCompositionOrObject importDestination))
                {
                    throw new ArgumentException("The import destination parameter for the import isn't of type IEngineeringCompositionOrObject!", nameof(destination));
                }

                if (string.IsNullOrEmpty(importFolderPath))
                {
                    throw new ArgumentNullException(nameof(importFolderPath), "The import folder path is null!");
                }

                if (option == null)
                {
                    throw new ArgumentNullException(nameof(option), "The import option is null!");
                }

                if (!(option is ImportOptions importOption))
                {
                    throw new ArgumentNullException(nameof(option), "The import option parameter for the import isn't of type ImportOptions!");
                }

                var importFiles = Directory.GetFiles(importFolderPath);
                var importFolders = Directory.GetDirectories(importFolderPath);

                foreach (var importFile in importFiles)
                {
                    ImportFile(importDestination, importFile, importOption);
                }

                foreach (var importFolder in importFolders)
                {
                    var subDestination = CreateSubFolder(importDestination, Path.GetFileName(importFolder));
                    ImportStructure(subDestination as IEngineeringCompositionOrObject, importFolder, importOption);
                }

                return true;
            }
            catch (EngineeringException engineeringException)
            {
                throw OpennessApiExceptionHandler.CatchedEngineeringException(engineeringException);
            }
            catch (NonRecoverableException nonRecoverableException)
            {
                throw OpennessApiExceptionHandler.CatchedNonRecoverableException(nonRecoverableException);
            }
            catch (OpennessApiException)
            {
                throw;
            }
            catch (Exception exception)
            {
                throw OpennessApiExceptionHandler.CatchedException(exception);
            }
        }

        /// <summary>
        /// Export element as structure
        /// </summary>
        /// <param name="element"></param>
        /// <param name="exportWithDefaults"></param>
        /// <param name="exportReadOnly"></param>
        /// <param name="exportPath"></param>
        /// <param name="exportName"></param>
        public void ExportStructure(object element, bool exportWithDefaults, bool exportReadOnly, string exportPath, string exportName)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(Step7Service) + " - " + nameof(ExportStructure) };

            try
            {

                if (element == null)
                {
                    throw new ArgumentNullException(nameof(element), "The export element parameter for the export is null!");
                }

                if (!(element is IEngineeringCompositionOrObject elementToExport))
                {
                    throw new ArgumentException("The export element parameter for the export isn't of type IEngineeringCompositionOrObject!", nameof(element));
                }

                if (string.IsNullOrEmpty(exportPath))
                {
                    throw new ArgumentNullException(nameof(exportPath), "The export path is null!");
                }

                if (string.IsNullOrEmpty(exportName))
                {
                    throw new ArgumentNullException(nameof(exportName), "The export name is null!");
                }


                var fullPath = Path.Combine(exportPath, exportName);

                if (!exportWithDefaults & !exportReadOnly)
                {
                    WriteTraceLogProxy(processInfo.ProcessMessage + " - " + ExportOptions.None);
                    ExportStructure(elementToExport, ExportOptions.None, fullPath);

                }

                if (!exportWithDefaults & exportReadOnly)
                {
                    WriteTraceLogProxy(processInfo.ProcessMessage + " - " + ExportOptions.WithReadOnly);
                    ExportStructure(elementToExport, ExportOptions.WithReadOnly, fullPath);
                }

                if (exportWithDefaults & !exportReadOnly)
                {
                    WriteTraceLogProxy(processInfo.ProcessMessage + " - " + ExportOptions.WithDefaults);
                    ExportStructure(elementToExport, ExportOptions.WithDefaults, fullPath);
                }

                if (exportWithDefaults & exportReadOnly)
                {
                    var options = ExportOptions.WithDefaults | ExportOptions.WithReadOnly;
                    WriteTraceLogProxy(processInfo.ProcessMessage + " - " + options);
                    ExportStructure(elementToExport, ExportOptions.WithDefaults | ExportOptions.WithReadOnly, fullPath);
                }

            }
            catch (EngineeringException engineeringException)
            {
                throw OpennessApiExceptionHandler.CatchedEngineeringException(engineeringException);
            }
            catch (NonRecoverableException nonRecoverableException)
            {
                throw OpennessApiExceptionHandler.CatchedNonRecoverableException(nonRecoverableException);
            }
            catch (OpennessApiException)
            {
                throw;
            }
            catch (Exception exception)
            {
                throw OpennessApiExceptionHandler.CatchedException(exception);
            }
        }

        private void ExportStructure(IEngineeringCompositionOrObject elementToExport, ExportOptions exportOptions, string exportPath)
        {
            try
            {
                if (elementToExport == null)
                {
                    throw new ArgumentNullException(nameof(elementToExport), "The element to export parameter for the structure export is null!");
                }

                if (string.IsNullOrEmpty(exportPath))
                {
                    throw new ArgumentNullException(nameof(exportPath), "The export path parameter for the structure export is null!");
                }

                if (elementToExport is PlcBlock || elementToExport is PlcTagTable || elementToExport is PlcType || elementToExport is PlcExternalSource)
                {
                    ExportItem(elementToExport as IEngineeringObject, exportOptions, exportPath);
                }

                var folderName = GetExportObjectName(elementToExport);
                var newPath = Path.Combine(exportPath, folderName);

                var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(Step7Service) + " - " + nameof(ExportStructure) };
                WriteTraceLogProxy(processInfo.ProcessMessage + " - " + newPath);

                Directory.CreateDirectory(newPath);

                var items = GetSubItem(elementToExport);
                if (items != null)
                {
                    foreach (var item in items)
                    {
                        ExportItem(item as IEngineeringObject, exportOptions, newPath);
                    }
                }

                var folders = GetSubFolder(elementToExport);
                if (folders != null)
                {
                    foreach (var folder in folders)
                    {
                        ExportStructure(folder as IEngineeringCompositionOrObject, exportOptions, newPath);
                    }
                }
            }
            catch (EngineeringException engineeringException)
            {
                throw OpennessApiExceptionHandler.CatchedEngineeringException(engineeringException);
            }
            catch (NonRecoverableException nonRecoverableException)
            {
                throw OpennessApiExceptionHandler.CatchedNonRecoverableException(nonRecoverableException);
            }
            catch (OpennessApiException)
            {
                throw;
            }
            catch (Exception exception)
            {
                throw OpennessApiExceptionHandler.CatchedException(exception);
            }
        }

        private bool ExportItem(IEngineeringObject exportItem, ExportOptions exportOption, string exportPath)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(Step7Service) + " - " + nameof(ExportItem) };

            try
            {
                if (exportItem is PlcBlock)
                {
                    var block = exportItem as PlcBlock;
                    if (block.ProgrammingLanguage == ProgrammingLanguage.ProDiag ||
                        block.ProgrammingLanguage == ProgrammingLanguage.ProDiag_OB)
                    {
                        return false;
                    }

                    bool isSimaticMLSupported = block is GlobalDB || block is ArrayDB || block is InstanceDB ||
                                                block.ProgrammingLanguage == ProgrammingLanguage.STL ||
                                                block.ProgrammingLanguage == ProgrammingLanguage.F_STL ||
                                                block.ProgrammingLanguage == ProgrammingLanguage.LAD ||
                                                block.ProgrammingLanguage == ProgrammingLanguage.LAD_IEC ||
                                                block.ProgrammingLanguage == ProgrammingLanguage.F_LAD ||
                                                block.ProgrammingLanguage == ProgrammingLanguage.F_LAD_LIB ||
                                                block.ProgrammingLanguage == ProgrammingLanguage.FBD ||
                                                block.ProgrammingLanguage == ProgrammingLanguage.FBD_IEC ||
                                                block.ProgrammingLanguage == ProgrammingLanguage.F_FBD ||
                                                block.ProgrammingLanguage == ProgrammingLanguage.F_FBD_LIB ||
                                                block.ProgrammingLanguage == ProgrammingLanguage.SCL ||
                                                block.ProgrammingLanguage == ProgrammingLanguage.GRAPH;

                    bool isExportPermitted = (block as OB)?.SecondaryType != "CyclicInterrupt.Safety" &&
                                             (block as OB)?.SecondaryType != "MCInterpolator" &&
                                             (block as OB)?.SecondaryType != "LookAhead" &&
                                             (block as OB)?.SecondaryType != "MCServo";

                    if (block.IsConsistent && isSimaticMLSupported && isExportPermitted)
                    {
                        exportPath = Path.Combine(exportPath,
                            AdjustNames.AdjustFileName(GetExportObjectName(exportItem)) + ".xml");
                        if (File.Exists(exportPath))
                        {
                            File.Delete(exportPath);
                        }

                        (exportItem as PlcBlock).Export(new FileInfo(exportPath), exportOption);

                        return true;
                    }

                    if (!block.IsConsistent)
                    {
                        throw new EngineeringException(string.Format(CultureInfo.InvariantCulture,
                            $"Object: {GetExportObjectName(exportItem)} with number {exportItem.GetAttribute("Number")} cannot be exported: It is inconsistent. Please compile before export!"));
                    }

                    WriteTraceLogProxy(processInfo.ProcessMessage + $"The export of block {GetExportObjectName(exportItem)} with number {exportItem.GetAttribute("Number")} is not supported!");

                }

                if (exportItem is PlcTagTable || exportItem is PlcType)
                {
                    Directory.CreateDirectory(exportPath);
                    exportPath = Path.Combine(exportPath,
                        AdjustNames.AdjustFileName(GetExportObjectName(exportItem)) + ".xml");
                    File.Delete(exportPath);
                    var parameter = new Dictionary<Type, object>();
                    parameter.Add(typeof(FileInfo), new FileInfo(exportPath));
                    parameter.Add(typeof(ExportOptions), exportOption);
                    exportItem.Invoke("Export", parameter);

                    return true;
                }

                var subItems = GetSubItem(exportItem);
                if (subItems != null && subItems.Any())
                {
                    foreach (var item in subItems)
                    {

                        if (item is Device)
                        {
                            var exportableObject = GetExportableObject(item, typeof(Device));
                            if (exportableObject != null)
                            {
                                ExportStructure(exportableObject as IEngineeringCompositionOrObject, exportOption, exportPath);
                            }
                        }
                        else if (item is DeviceItem)
                        {
                            var exportableObject = GetExportableObject(item, typeof(DeviceItem));
                            if (exportableObject != null)
                            {
                                ExportStructure(exportableObject as IEngineeringCompositionOrObject, exportOption, exportPath);
                            }
                        }

                        string name = ((DeviceItem) item).Name;
                            
                        ExportItem(item as IEngineeringObject, exportOption, exportPath);
                    }
                }


                return false;
            }
            catch (EngineeringException engineeringException)
            {
                throw OpennessApiExceptionHandler.CatchedEngineeringException(engineeringException);
            }
            catch (NonRecoverableException nonRecoverableException)
            {
                throw OpennessApiExceptionHandler.CatchedNonRecoverableException(nonRecoverableException);
            }
            catch (OpennessApiException)
            {
                throw;
            }
            catch (Exception exception)
            {
                throw OpennessApiExceptionHandler.CatchedException(exception);
            }
        }

        private string GetExportObjectName(IEngineeringInstance item)
        {
            try
            {
                var itemName = "";
                if (item == null)
                    return itemName;
                try
                {
                    itemName = ((IEngineeringObject)item).GetAttribute("Name") as string;
                }
                catch (Exception)
                {
                    // ignored
                }

                if (string.IsNullOrEmpty(itemName))
                {
                    if (item is PlcSystemBlockGroupComposition)
                        itemName = "SystemBlocks";
                    else if (item is MasterCopySystemFolder)
                        itemName = "Master copies";
                }

                return itemName;
            }
            catch (EngineeringException engineeringException)
            {
                throw OpennessApiExceptionHandler.CatchedEngineeringException(engineeringException);
            }
            catch (NonRecoverableException nonRecoverableException)
            {
                throw OpennessApiExceptionHandler.CatchedNonRecoverableException(nonRecoverableException);
            }
            catch (OpennessApiException)
            {
                throw;
            }
            catch (Exception exception)
            {
                throw OpennessApiExceptionHandler.CatchedException(exception);
            }
        }

        private IEnumerable<object> GetSubFolder(object item)
        {
            try
            {
                object subFolder;

                if (item is PlcSoftware)
                {
                    var sw = item as PlcSoftware;
                    var col = new Collection<object>();
                    col.Add(sw.BlockGroup);
                    col.Add(sw.TagTableGroup);
                    col.Add(sw.TypeGroup);
                    col.Add(sw.ExternalSourceGroup);
                    subFolder = col;
                }
                else if (item is Device)
                    subFolder = new Collection<object>();
                else if (item is DeviceItem)
                    subFolder = new Collection<object>();
                else if (item is PlcBlockGroup)
                    subFolder = (item as PlcBlockGroup).Groups;
                else if (item is PlcTagTableGroup)
                    subFolder = (item as PlcTagTableGroup).Groups;
                else if (item is PlcTypeGroup)
                    subFolder = (item as PlcTypeGroup).Groups;
                else if (item is ProjectLibrary)
                    subFolder = (item as ProjectLibrary).MasterCopyFolder.Folders;
                else if (item is LibraryTypeFolder)
                    subFolder = (item as LibraryTypeFolder).Folders;
                else if (item is MasterCopyFolder)
                    subFolder = (item as MasterCopyFolder).Folders;
                else if (item is DeviceUserGroup)
                    subFolder = item;
                else if (item is Project)
                {
                    subFolder = new Collection<object>();
                    foreach (var folder in (item as Project).DeviceGroups)
                        (subFolder as Collection<object>).Add(folder);
                }
                else
                {
                    subFolder = new Collection<object>();
                }

                return subFolder as IEnumerable<object>;
            }
            catch (EngineeringException engineeringException)
            {
                throw OpennessApiExceptionHandler.CatchedEngineeringException(engineeringException);
            }
            catch (NonRecoverableException nonRecoverableException)
            {
                throw OpennessApiExceptionHandler.CatchedNonRecoverableException(nonRecoverableException);
            }
            catch (OpennessApiException)
            {
                throw;
            }
            catch (Exception exception)
            {
                throw OpennessApiExceptionHandler.CatchedException(exception);
            }
        }

        private IEnumerable<object> GetSubItem(object item)
        {
            object subItem = null;
            if (item != null)
            {
                if (item is Project)
                {
                    subItem = new Collection<object>();
                    foreach (var device in (item as Project).Devices)
                        (subItem as Collection<object>).Add(device);
                    (subItem as Collection<object>).Add((item as Project).Graphics);
                }
                else if (item is DeviceUserGroup)
                    subItem = (item as DeviceUserGroup).Devices;
                else if (item is PlcSoftware)
                    subItem = new Collection<object>();
                else if (item is Device)
                    subItem = (item as Device).Items;
                else if (item is DeviceItem)
                    subItem = (item as DeviceItem).Items;
                else if (item is PlcBlockGroup)
                    subItem = (item as PlcBlockGroup).Blocks;
                else if (item is PlcTagTableGroup)
                    subItem = (item as PlcTagTableGroup).TagTables;
                else if (item is PlcTypeGroup)
                    subItem = (item as PlcTypeGroup).Types;
                else if (item is PlcExternalSourceGroup)
                    subItem = (item as PlcExternalSourceGroup).ExternalSources;
                else if (item is IEngineeringComposition)
                    subItem = item;
                else if (item is ProjectLibrary)
                    subItem = new Collection<object>();
                else if (item is MasterCopyFolder)
                    subItem = (item as MasterCopyFolder).MasterCopies;
                else if (item is LibraryTypeFolder)
                    subItem = (item as LibraryTypeFolder).Types;
                else
                {
                    subItem = new Collection<object>();
                }
            }

            return subItem as IEnumerable<object>;
        }

        private MethodInfo GetGenericMethodInfo(Type fromType, Type forType)
        {
            try
            {
                MethodInfo genericMethodInfo = null;

                if (fromType != null)
                {
                    var methodInfo = fromType.GetMethod("GetService");

                    if (methodInfo == null && fromType.BaseType != null)
                    {
                        methodInfo = fromType.BaseType.GetMethod("GetService");

                    }

                    if (methodInfo != null)
                    {
                        try
                        {
                            genericMethodInfo = methodInfo.MakeGenericMethod(forType);
                        }
                        catch (Exception e)
                        {
                            Debug.WriteLine(e.Message);
                        }
                    }
                }

                return genericMethodInfo;
            }
            catch (EngineeringException engineeringException)
            {
                throw OpennessApiExceptionHandler.CatchedEngineeringException(engineeringException);
            }
            catch (NonRecoverableException nonRecoverableException)
            {
                throw OpennessApiExceptionHandler.CatchedNonRecoverableException(nonRecoverableException);
            }
            catch (OpennessApiException)
            {
                throw;
            }
            catch (Exception exception)
            {
                throw OpennessApiExceptionHandler.CatchedException(exception);
            }
        }

        private object GetExportableObject(object exportObject, Type exportType)
        {
            if (exportObject != null && exportType != null)
            {
                var methodInfo = GetGenericMethodInfo(exportType, typeof(SoftwareContainer));

                if (methodInfo != null)
                {
                    if (methodInfo.Invoke(exportObject, null) is SoftwareContainer softwareContainer)
                    {
                        if (softwareContainer.Software is PlcSoftware plcSoftware)
                        {
                            return plcSoftware;
                        }
                    }
                }
            }

            return null;
        }

        private void ImportFile(IEngineeringCompositionOrObject importDestination, string importFilePath, ImportOptions importOption)
        {
            var importFileInfo = new FileInfo(importFilePath);
            var importPath = importFileInfo.FullName;

            if (importDestination is PlcBlockGroup)
            {
                if (Path.GetExtension(importPath).Equals(".xml"))
                    (importDestination as PlcBlockGroup).Blocks.Import(importFileInfo, importOption);
                else
                {
                    var currentDestination = importDestination as IEngineeringObject;
                    while (!(currentDestination is PlcSoftware))
                    {
                        currentDestination = currentDestination.Parent;
                    }
                    var col = (currentDestination as PlcSoftware).ExternalSourceGroup.ExternalSources;

                    var sourceName = Path.GetRandomFileName();
                    sourceName = Path.ChangeExtension(sourceName, ".src");
                    var src = col.CreateFromFile(sourceName, importPath);
                    src.GenerateBlocksFromSource();
                    src.Delete();
                }
            }
            else if (importDestination is PlcTagTableGroup)
                (importDestination as PlcTagTableGroup).TagTables.Import(importFileInfo, importOption);
            else if (importDestination is PlcTypeGroup)
                (importDestination as PlcTypeGroup).Types.Import(importFileInfo, importOption);
            else if (importDestination is PlcExternalSourceGroup)
            {
                var temp = (importDestination as PlcExternalSourceGroup).ExternalSources.Find(Path.GetFileName(importPath));
                if (temp != null)
                    temp.Delete();
                (importDestination as PlcExternalSourceGroup).ExternalSources.CreateFromFile(Path.GetFileName(importPath), importPath);
            }
        }

        private object CreateSubFolder(object importDestination, string importFolder)
        {
            object subFolder;

            if (importDestination is PlcBlockSystemGroup)
            {
                var group = importDestination as PlcBlockSystemGroup;
                subFolder = group.Groups.Find(importFolder);
                if (subFolder == null)
                    subFolder = group.Groups.Create(importFolder);
            }
            else if (importDestination is PlcBlockGroup)
            {
                var group = importDestination as PlcBlockGroup;
                subFolder = group.Groups.Find(importFolder);
                if (subFolder == null)
                    subFolder = group.Groups.Create(importFolder);
            }
            else if (importDestination is PlcTagTableGroup)
            {
                var group = importDestination as PlcTagTableGroup;
                subFolder = group.Groups.Find(importFolder);
                if (subFolder == null)
                    subFolder = group.Groups.Create(importFolder);
            }
            else if (importDestination is PlcTypeGroup)
            {
                var group = importDestination as PlcTypeGroup;
                subFolder = group.Groups.Find(importFolder);
                if (subFolder == null)
                    subFolder = group.Groups.Create(importFolder);
            }
            else
            {
                subFolder = new object();
            }

            return subFolder;

        }

        #endregion // import/export

        #region group

        public void CreateGroup(object item, string groupName)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(Step7Service) + " - " + nameof(CreateGroup) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                if (item is PlcTypeGroup)
                {
                    AddNewGroup((PlcTypeGroup)item, groupName);
                }

                if (item is PlcBlockGroup)
                {
                    AddNewGroup((PlcBlockGroup)item, groupName);
                }

                if (item is PlcExternalSourceGroup)
                {
                    AddNewGroup((PlcExternalSourceGroup)item, groupName);
                }

                if (item is PlcTagTableGroup)
                {
                    AddNewGroup((PlcTagTableGroup)item, groupName);
                }

                if (item is PlcTypeSystemGroup)
                {
                    AddNewGroup((PlcTypeSystemGroup)item, groupName);
                }

                if (item is PlcTagTableUserGroup)
                {
                    AddNewGroup((PlcTagTableUserGroup)item, groupName);
                }
            }
            catch (EngineeringException engineeringException)
            {
                throw OpennessApiExceptionHandler.CatchedEngineeringException(engineeringException);
            }
            catch (NonRecoverableException nonRecoverableException)
            {
                throw OpennessApiExceptionHandler.CatchedNonRecoverableException(nonRecoverableException);
            }
            catch (OpennessApiException)
            {
                throw;
            }
            catch (Exception exception)
            {
                throw OpennessApiExceptionHandler.CatchedException(exception);
            }
        }

        private void AddNewGroup(PlcTypeGroup typeGroup, string groupName)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(Step7Service) + " - " + nameof(AddNewGroup) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                WriteTraceLogProxy(processInfo.ProcessMessage + " -> " + groupName);
                typeGroup.Groups.Create(groupName);
            }
            catch (EngineeringException engineeringException)
            {
                throw OpennessApiExceptionHandler.CatchedEngineeringException(engineeringException);
            }
            catch (NonRecoverableException nonRecoverableException)
            {
                throw OpennessApiExceptionHandler.CatchedNonRecoverableException(nonRecoverableException);
            }
            catch (OpennessApiException)
            {
                throw;
            }
            catch (Exception exception)
            {
                throw OpennessApiExceptionHandler.CatchedException(exception);
            }
        }

        private void AddNewGroup(PlcBlockGroup blockGroup, string groupName)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(Step7Service) + " - " + nameof(PlcBlockGroup) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                WriteTraceLogProxy(processInfo.ProcessMessage + " -> " + groupName);
                blockGroup.Groups.Create(groupName);
            }
            catch (EngineeringException engineeringException)
            {
                throw OpennessApiExceptionHandler.CatchedEngineeringException(engineeringException);
            }
            catch (NonRecoverableException nonRecoverableException)
            {
                throw OpennessApiExceptionHandler.CatchedNonRecoverableException(nonRecoverableException);
            }
            catch (OpennessApiException)
            {
                throw;
            }
            catch (Exception exception)
            {
                throw OpennessApiExceptionHandler.CatchedException(exception);
            }
        }

        private void AddNewGroup(PlcExternalSourceGroup externalSourceGroup, string groupName)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(Step7Service) + " - " + nameof(PlcExternalSourceGroup) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                WriteTraceLogProxy(processInfo.ProcessMessage + " -> " + groupName);
                externalSourceGroup.Groups.Create(groupName);
            }
            catch (EngineeringException engineeringException)
            {
                throw OpennessApiExceptionHandler.CatchedEngineeringException(engineeringException);
            }
            catch (NonRecoverableException nonRecoverableException)
            {
                throw OpennessApiExceptionHandler.CatchedNonRecoverableException(nonRecoverableException);
            }
            catch (OpennessApiException)
            {
                throw;
            }
            catch (Exception exception)
            {
                throw OpennessApiExceptionHandler.CatchedException(exception);
            }
        }

        private void AddNewGroup(PlcTagTableGroup tagTableGroup, string groupName)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(Step7Service) + " - " + nameof(PlcTagTableGroup) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                WriteTraceLogProxy(processInfo.ProcessMessage + " -> " + groupName);
                tagTableGroup.Groups.Create(groupName);
            }
            catch (EngineeringException engineeringException)
            {
                throw OpennessApiExceptionHandler.CatchedEngineeringException(engineeringException);
            }
            catch (NonRecoverableException nonRecoverableException)
            {
                throw OpennessApiExceptionHandler.CatchedNonRecoverableException(nonRecoverableException);
            }
            catch (OpennessApiException)
            {
                throw;
            }
            catch (Exception exception)
            {
                throw OpennessApiExceptionHandler.CatchedException(exception);
            }
        }

        private void AddNewGroup(PlcTypeSystemGroup typeSystemGroup, string groupName)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(Step7Service) + " - " + nameof(PlcTypeSystemGroup) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                WriteTraceLogProxy(processInfo.ProcessMessage + " -> " + groupName);
                typeSystemGroup.Groups.Create(groupName);
            }
            catch (EngineeringException engineeringException)
            {
                throw OpennessApiExceptionHandler.CatchedEngineeringException(engineeringException);
            }
            catch (NonRecoverableException nonRecoverableException)
            {
                throw OpennessApiExceptionHandler.CatchedNonRecoverableException(nonRecoverableException);
            }
            catch (OpennessApiException)
            {
                throw;
            }
            catch (Exception exception)
            {
                throw OpennessApiExceptionHandler.CatchedException(exception);
            }
        }

        private void AddNewGroup(PlcTagTableUserGroup tagTableUserGroup, string groupName)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(Step7Service) + " - " + nameof(PlcTagTableUserGroup) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                WriteTraceLogProxy(processInfo.ProcessMessage + " -> " + groupName);
                tagTableUserGroup.Groups.Create(groupName);
            }
            catch (EngineeringException engineeringException)
            {
                throw OpennessApiExceptionHandler.CatchedEngineeringException(engineeringException);
            }
            catch (NonRecoverableException nonRecoverableException)
            {
                throw OpennessApiExceptionHandler.CatchedNonRecoverableException(nonRecoverableException);
            }
            catch (OpennessApiException)
            {
                throw;
            }
            catch (Exception exception)
            {
                throw OpennessApiExceptionHandler.CatchedException(exception);
            }
        }

        #endregion // group

        #region tree structure

        /// <summary>
        /// Retrieve structure as generic method definition
        /// </summary>
        /// <typeparam name="T1">generic type</typeparam>
        /// <typeparam name="T2">generic type</typeparam>
        /// <typeparam name="T3">generic type</typeparam>
        /// <typeparam name="T4">generic type</typeparam>
        /// <param name="deviceItem"></param>
        /// <param name="treeItem"></param>
        /// <param name="engineeringProjectItem"></param>
        /// <param name="engineeringProjectModel"></param>
        public void GetStructure<T1, T2, T3, T4>(T1 deviceItem, T2 treeItem, T3 engineeringProjectItem, T4 engineeringProjectModel)
        {
            // not available in version 15.0
        }

        #endregion // tree structure

        #region mastercopy

        /// <summary>
        /// Create a master copy from source
        /// </summary>
        /// <param name="copyDestination"></param>
        /// <param name="copySource"></param>
        public void CreateCopyFromMasterCopy(object copyDestination, object copySource)
        {
            var folder = string.Empty;
            var plcSoftware = GetPlcSoftware(copyDestination);
            if (copyDestination is PlcBlockUserGroup ||
                copyDestination is PlcTypeUserGroup ||
                copyDestination is PlcTagTableUserGroup)
            {
                folder = copyDestination.GetType().GetProperty("Name")?.GetValue(copyDestination, null) as string;
            }

            if (copySource is MasterCopy masterCopy && plcSoftware != null)
            {
                var contentType = masterCopy.ContentDescriptions.First().ContentType;

                if (contentType == typeof(PlcBlockUserGroup))
                {
                    CopyToProgramBlockGroup(plcSoftware, masterCopy, folder);
                }

                if (contentType == typeof(PlcBlock) || contentType.IsSubclassOf(typeof(PlcBlock)))
                {
                    CopyToProgramBlock(plcSoftware, masterCopy, folder);
                }

                if (contentType == typeof(PlcTypeUserGroup))
                {
                    CopyToUserDataTypeGroup(plcSoftware, masterCopy, folder);
                }

                if (contentType == typeof(PlcType) || contentType.IsSubclassOf(typeof(PlcType)))
                {
                    CopyToUserDataType(plcSoftware, masterCopy, folder);
                }

                if (contentType == typeof(PlcTagTableUserGroup))
                {
                    CopyToPlcTagTableGroup(plcSoftware, masterCopy, folder);
                }

                if (contentType == typeof(PlcTagTable) || contentType.IsSubclassOf(typeof(PlcTagTable)))
                {
                    CopyToPlcTagTable(plcSoftware, masterCopy, folder);
                }
            }
        }

        private void CopyToProgramBlockGroup(PlcSoftware copyDestination, MasterCopy masterCopy, string folder)
        {
            if (string.IsNullOrEmpty(folder))
            {
                copyDestination.BlockGroup.Groups.CreateFrom(masterCopy);
            }
            else
            {
                var destination = copyDestination.BlockGroup.Groups.Find(folder);
                destination?.Groups.CreateFrom(masterCopy);
            }
        }

        private void CopyToProgramBlock(PlcSoftware copyDestination, MasterCopy masterCopy, string folder)
        {
            if (string.IsNullOrEmpty(folder))
            {
                copyDestination.BlockGroup.Blocks.CreateFrom(masterCopy);
            }
            else
            {
                var destination = copyDestination.BlockGroup.Groups.Find(folder);
                destination?.Blocks.CreateFrom(masterCopy);
            }
        }

        private void CopyToUserDataTypeGroup(PlcSoftware copyDestination, MasterCopy masterCopy, string folder)
        {
            if (string.IsNullOrEmpty(folder))
            {
                copyDestination.TypeGroup.Groups.CreateFrom(masterCopy);
            }
            else
            {
                var destination = copyDestination.TypeGroup.Groups.Find(folder);
                destination?.Groups.CreateFrom(masterCopy);
            }
        }

        private void CopyToUserDataType(PlcSoftware copyDestination, MasterCopy masterCopy, string folder)
        {
            if (string.IsNullOrEmpty(folder))
            {
                copyDestination.TypeGroup.Types.CreateFrom(masterCopy);
            }
            else
            {
                var destination = copyDestination.TypeGroup.Groups.Find(folder);
                destination?.Types.CreateFrom(masterCopy);
            }
        }

        private void CopyToPlcTagTableGroup(PlcSoftware copyDestination, MasterCopy masterCopy, string folder)
        {
            if (string.IsNullOrEmpty(folder))
            {
                copyDestination.TagTableGroup.Groups.CreateFrom(masterCopy);
            }
            else
            {
                var destination = copyDestination.TagTableGroup.Groups.Find(folder);
                destination?.Groups.CreateFrom(masterCopy);
            }
        }

        private void CopyToPlcTagTable(PlcSoftware copyDestination, MasterCopy masterCopy, string folder)
        {
            if (string.IsNullOrEmpty(folder))
            {
                copyDestination.TagTableGroup.TagTables.CreateFrom(masterCopy);
            }
            else
            {
                var destination = copyDestination.TagTableGroup.Groups.Find(folder);
                destination?.TagTables.CreateFrom(masterCopy);
            }
        }

        private PlcSoftware GetPlcSoftware(object copyDestination)
        {
            try
            {
                object parent;
                var item = copyDestination;
                var found = false;

                while (true)
                {
                    parent = item.GetType().GetProperty("Parent")?.GetValue(item, null);
                    if (parent is PlcSoftware)
                    {
                        found = true;
                        break;
                    }

                    if (parent == null)
                    {
                        break;
                    }

                    item = parent;
                }

                if (found)
                {
                    return parent as PlcSoftware;
                }
            }
            catch (EngineeringException engineeringException)
            {
                throw OpennessApiExceptionHandler.CatchedEngineeringException(engineeringException);
            }
            catch (NonRecoverableException nonRecoverableException)
            {
                throw OpennessApiExceptionHandler.CatchedNonRecoverableException(nonRecoverableException);
            }
            catch (OpennessApiException)
            {
                throw;
            }
            catch (Exception exception)
            {
                throw OpennessApiExceptionHandler.CatchedException(exception);
            }

            return null;
        }

        #endregion // mastercopy

        #region Copy type version

        /// <summary>
        /// Copy library version to project
        /// </summary>
        /// <param name="copyDestination"></param>
        /// <param name="copySource"></param>
        public void CopyLibraryVersionToProject(object copyDestination, object copySource)
        {
            if (copyDestination is PlcBlockUserGroup plcBlockUserGroup && copySource is CodeBlockLibraryTypeVersion codeBlockLibraryTypeVersion)
            {
                CopyToPlcBlockUserGroup(plcBlockUserGroup, codeBlockLibraryTypeVersion);
            }

            if (copyDestination is PlcBlockSystemGroup plcBlockSystemGroup)
            {
                CopyToPlcBlockSystemGroup(plcBlockSystemGroup);
            }

            if (copyDestination is PlcTypeUserGroup plcTypeUserGroup && copySource is PlcTypeLibraryTypeVersion plcTypeLibraryTypeVersion)
            {
                CopyToPlcTypeUserGroup(plcTypeUserGroup, plcTypeLibraryTypeVersion);
            }

            if (copyDestination is PlcTypeSystemGroup plcTypeSystemGroup)
            {
                CopyToPlcTypeSystemGroup(plcTypeSystemGroup);
            }
        }

        private void CopyToPlcBlockUserGroup(PlcBlockUserGroup plcBlockUserGroup, CodeBlockLibraryTypeVersion codeBlockLibraryTypeVersion)
        {
            plcBlockUserGroup.Blocks.CreateFrom(codeBlockLibraryTypeVersion);
        }

        private void CopyToPlcBlockSystemGroup(PlcBlockSystemGroup plcBlockSystemGroup)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(Step7Service) + " - " + nameof(CopyToPlcBlockSystemGroup) };
            WriteTraceLogProxy(processInfo.ProcessMessage + " - Copy to PlcBlockSystemGroup is not supported! Please select sub group as destination!");
        }

        private void CopyToPlcTypeUserGroup(PlcTypeUserGroup plcTypeUserGroup, PlcTypeLibraryTypeVersion plcTypeLibraryTypeVersion)
        {
            plcTypeUserGroup.Types.CreateFrom(plcTypeLibraryTypeVersion);
        }

        private void CopyToPlcTypeSystemGroup(PlcTypeSystemGroup plcTypeSystemGroup)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(Step7Service) + " - " + nameof(CopyToPlcTypeSystemGroup) };
            WriteTraceLogProxy(processInfo.ProcessMessage + " - Copy to PlcTypeSystemGroup is not supported! Please select sub group as destination!");
        }

        #endregion // Copy type version

        #endregion // methods

        #region trace

        /// <summary>
        /// Execute writing trace log in different thread.
        /// </summary>
        /// <param name="traceLog"></param>
        private void WriteTraceLogProxy(string traceLog)
        {
            Application.Current.Dispatcher.Invoke(delegate
            {
                _traceLogService.Write(traceLog);
            });
        }

        #endregion // trace
    }
}
