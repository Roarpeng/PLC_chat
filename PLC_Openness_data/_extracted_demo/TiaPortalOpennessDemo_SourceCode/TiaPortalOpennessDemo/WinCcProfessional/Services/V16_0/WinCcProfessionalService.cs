extern alias V16_0;
using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Windows;
using TiaPortalOpennessAdapter.Utils;
using TiaPortalOpennessAdapterContracts;
using TiaPortalOpennessInfrastructure.Contracts;
using TiaPortalOpennessInfrastructure.Exceptions;
using TiaPortalOpennessInfrastructure.Utils;
using V16_0::Siemens.Engineering;
using V16_0::Siemens.Engineering.Hmi;
using V16_0::Siemens.Engineering.Hmi.Communication;
using V16_0::Siemens.Engineering.Hmi.Cycle;
using V16_0::Siemens.Engineering.Hmi.Globalization;
using V16_0::Siemens.Engineering.Hmi.RuntimeScripting;
using V16_0::Siemens.Engineering.Hmi.Screen;
using V16_0::Siemens.Engineering.Hmi.Tag;
using V16_0::Siemens.Engineering.Hmi.TextGraphicList;
using V16_0::Siemens.Engineering.HW;
using V16_0::Siemens.Engineering.HW.Features;
using V16_0::Siemens.Engineering.Library;
using V16_0::Siemens.Engineering.Library.MasterCopies;
using V16_0::Siemens.Engineering.Library.Types;

namespace WinCcProfessional.Services.V16_0
{
    public class WinCcProfessionalService : IHmiTargetService
    {
        #region fields

        private const string ExceptionMessage = "This kind of master copy is not supported.";
        private readonly ITraceLogService _traceLogService;

        #endregion // fields

        #region ctor

        public WinCcProfessionalService(ITraceLogService traceLogService)
        {
            _traceLogService = traceLogService;
        }

        #endregion // ctor

        #region methods

        #region common

        /// <summary>
        /// Retrieve whether item is known
        /// </summary>
        /// <param name="item"></param>
        /// <returns></returns>
        public bool IsKnownObject(Type item)
        {
            bool known = item == typeof(ScreenUserFolder) ||
                         item == typeof(Screen) ||
                         item.IsSubclassOf(typeof(Screen)) ||
                         item == typeof(ScreenTemplateUserFolder) ||
                         item == typeof(ScreenTemplate) ||
                         item.IsSubclassOf(typeof(ScreenTemplate)) ||
                         item == typeof(VBScriptUserFolder) ||
                         item == typeof(VBScript) ||
                         item.IsSubclassOf(typeof(VBScript)) ||
                         item == typeof(TagUserFolder) ||
                         item == typeof(TagTable) ||
                         item.IsSubclassOf(typeof(TagTable));

            return known;
        }

        /// <summary>
        /// Retrieve whether item is hmi target
        /// </summary>
        /// <param name="item"></param>
        /// <returns></returns>
        public bool IsHmiTarget(object item)
        {
            return item is HmiTarget;
        }

        /// <summary>
        /// Retrieve whether item can be a structure import destination
        /// </summary>
        /// <param name="item"></param>
        /// <returns></returns>
        public bool IsHmiTargetStructureDestination(object item)
        {
            bool result = item is TagSystemFolder ||
                          item is TagUserFolder ||
                          item is ScreenOverview ||
                          item is ScreenGlobalElements ||
                          item is ScreenSystemFolder ||
                          item is ScreenUserFolder ||
                          item is ScreenTemplateSystemFolder ||
                          item is ScreenTemplateUserFolder ||
                          item is ScreenPopupSystemFolder ||
                          item is ScreenPopupUserFolder ||
                          item is ScreenSlideinSystemFolder ||
                          item is CycleComposition ||
                          item is ConnectionComposition ||
                          item is VBScriptSystemFolder ||
                          item is VBScriptUserFolder ||
                          item is GraphicListComposition ||
                          item is TextListComposition ||
                          item is MultiLingualGraphicComposition;

            return result;
        }

        /// <summary>
        /// Retrieve whether item is vb scrip
        /// </summary>
        /// <param name="item"></param>
        /// <returns></returns>
        public bool IsVbScript(object item)
        {
            return item is VBScript;
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
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(WinCcProfessionalService) + " - " + nameof(ImportElement) };
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
                    throw new ArgumentException( "The import destination parameter for the import isn't of type IEngineeringCompositionOrObject!", nameof(destination));
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
                                    if (importDestination is CycleComposition || importDestination is ConnectionComposition || importDestination is MultiLingualGraphicComposition
                                        || importDestination is GraphicListComposition || importDestination is TextListComposition)
                                    {
                                        var parameter = new Dictionary<Type, object>();
                                        parameter.Add(typeof(string), importFileInfo.FullName);
                                        parameter.Add(typeof(ImportOptions), importOption);
                                        // Export check
                                        (importDestination as IEngineeringComposition).Invoke("Import", parameter);
                                        result = true;
                                    }
                                    else if (importDestination is TagFolder)
                                    {
                                        (importDestination as TagFolder).TagTables.Import(importFileInfo, importOption);
                                        result = true;
                                    }
                                    else if (importDestination is ScreenFolder)
                                    {
                                        (importDestination as ScreenFolder).Screens.Import(importFileInfo, importOption);
                                        result = true;
                                    }
                                    else if (importDestination is ScreenTemplateFolder)
                                    {
                                        (importDestination as ScreenTemplateFolder).ScreenTemplates.Import(importFileInfo, importOption);
                                        result = true;
                                    }
                                    else if (importDestination is ScreenPopupFolder)
                                    {
                                        (importDestination as ScreenPopupFolder).ScreenPopups.Import(importFileInfo, importOption);
                                        result = true;
                                    }
                                    else if (importDestination is ScreenSlideinSystemFolder)
                                    {
                                        (importDestination as ScreenSlideinSystemFolder).ScreenSlideins.Import(importFileInfo, importOption);
                                        result = true;
                                    }
                                    else if (importDestination is VBScriptFolder)
                                    {
                                        (importDestination as VBScriptFolder).VBScripts.Import(importFileInfo, importOption);
                                        result = true;
                                    }
                                    else if (importDestination is ScreenGlobalElements)
                                    {
                                        (importDestination.Parent as HmiTarget)?.ImportScreenGlobalElements(importFileInfo, importOption);
                                        result = true;
                                    }
                                    else if (importDestination is ScreenOverview)
                                    {
                                        (importDestination.Parent as HmiTarget)?.ImportScreenOverview(importFileInfo, importOption);
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
        /// <returns></returns>
        public bool ImportStructure(object destination, string importFolderPath, object option)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(WinCcProfessionalService) + " - " + nameof(ImportStructure) };
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
        /// Export element as structure
        /// </summary>
        /// <param name="element"></param>
        /// <param name="exportWithDefaults"></param>
        /// <param name="exportReadOnly"></param>
        /// <param name="exportPath"></param>
        /// <param name="exportName"></param>
        public void ExportStructure(object element, bool exportWithDefaults, bool exportReadOnly, string exportPath, string exportName)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(WinCcProfessionalService) + " - " + nameof(ExportStructure) };

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

                if (elementToExport is ScreenOverview || elementToExport is ScreenGlobalElements || elementToExport is TagTable || elementToExport is Screen ||
                    elementToExport is Cycle || elementToExport is Connection || elementToExport is MultiLingualGraphic || elementToExport is ScreenTemplate ||
                    elementToExport is VBScript || elementToExport is TextList || elementToExport is ScreenPopup || elementToExport is ScreenSlidein)
                {
                    ExportItem(elementToExport as IEngineeringObject, exportOptions, exportPath);
                }

                var folderName = GetExportObjectName(elementToExport);
                var newPath = Path.Combine(exportPath, folderName);

                var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(WinCcProfessionalService) + " - " + nameof(ExportStructure) };
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
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(WinCcProfessionalService) + " - " + nameof(ExportItem) };

            try
            {
                if (exportItem is ScreenOverview || exportItem is ScreenGlobalElements || exportItem is Screen || exportItem is TagTable || exportItem is Connection ||
                exportItem is GraphicList || exportItem is TextList || exportItem is Cycle || exportItem is MultiLingualGraphic || exportItem is ScreenTemplate ||
                exportItem is VBScript || exportItem is ScreenPopup || exportItem is ScreenSlidein)
                {
                    Directory.CreateDirectory(exportPath);
                    exportPath = Path.Combine(exportPath, AdjustNames.AdjustFileName(GetExportObjectName(exportItem)) + ".xml");
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
                    if (item is CycleComposition)
                        itemName = "Cycles";
                    else if (item is ConnectionComposition)
                        itemName = "Connections";
                    else if (item is MasterCopySystemFolder)
                        itemName = "Master copies";
                    else if (item is MultiLingualGraphicComposition)
                        itemName = "Multilingual graphics";
                    else if (item is ScreenOverview)
                        itemName = "ScreenOverview";
                    else if (item is GraphicListComposition)
                        itemName = "GraphicLists";
                    else if (item is TextListComposition)
                        itemName = "TextLists";
                    else if (item is ScreenGlobalElements)
                        itemName = "ScreenGlobalElements";
                    else if (item is ScreenSlideinSystemFolder)
                        itemName = "Slide-in screens";
                    else if (item is ScreenSlidein)
                        itemName = "Slide-in screen " + (item as ScreenSlidein).SlideinType;
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

                if (item is HmiTarget)
                {
                    var target = item as HmiTarget;
                    var col = new Collection<object>();
                    col.Add(target.ScreenFolder);
                    col.Add(target.ScreenTemplateFolder);
                    col.Add(target.TagFolder);
                    col.Add(target.Connections);
                    col.Add(target.VBScriptFolder);
                    col.Add(target.Cycles);
                    subFolder = col;
                }
                else if (item is Device)
                    subFolder = new Collection<object>();
                else if (item is DeviceItem)
                    subFolder = new Collection<object>();
                else if (item is TagFolder)
                    subFolder = (item as TagFolder).Folders;
                else if (item is VBScriptFolder)
                    subFolder = (item as VBScriptFolder).Folders;
                else if (item is ScreenFolder)
                    subFolder = (item as ScreenFolder).Folders;
                else if (item is ScreenTemplateFolder)
                    subFolder = (item as ScreenTemplateFolder).Folders;
                else if (item is ScreenPopupFolder)
                    subFolder = (item as ScreenPopupFolder).Folders;
                else if (item is ProjectLibrary)
                    subFolder = (item as ProjectLibrary).MasterCopyFolder.Folders;
                else if (item is TagTable)
                    subFolder = (item as TagTable).Tags;
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
                else if (item is HmiTarget)
                    subItem = new Collection<object>();
                else if (item is Device)
                    subItem = (item as Device).Items;
                else if (item is DeviceItem)
                    subItem = (item as DeviceItem).Items;
                else if (item is TagFolder)
                    subItem = (item as TagFolder).TagTables;
                else if (item is ScreenFolder)
                    subItem = (item as ScreenFolder).Screens;
                else if (item is ScreenTemplateFolder)
                    subItem = (item as ScreenTemplateFolder).ScreenTemplates;
                else if (item is ScreenPopupFolder)
                    subItem = (item as ScreenPopupFolder).ScreenPopups;
                else if (item is ScreenSlideinSystemFolder)
                    subItem = (item as ScreenSlideinSystemFolder).ScreenSlideins;
                else if (item is VBScriptFolder)
                    subItem = (item as VBScriptFolder).VBScripts;
                else if (item is MultiLingualGraphicComposition)
                    subItem = item;
                else if (item is TagTable)
                    subItem = (item as TagTable).Tags;
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
                        if (softwareContainer.Software is HmiTarget hmiTarget)
                        {
                            return hmiTarget;
                        }
                    }
                }
            }

            return null;
        }

        private void ImportFile(IEngineeringCompositionOrObject importdDestination, string importFilePath, ImportOptions importOption)
        {
            var importFileInfo = new FileInfo(importFilePath);
            var importPath = importFileInfo.FullName;


            if (importdDestination is CycleComposition ||
                importdDestination is ConnectionComposition ||
                importdDestination is MultiLingualGraphicComposition ||
                importdDestination is GraphicListComposition ||
                importdDestination is TextListComposition)
            {
                var parameter = new Dictionary<Type, object>();
                parameter.Add(typeof(FileInfo), importFileInfo);
                parameter.Add(typeof(ImportOptions), importOption);
                // Export prüfen
                (importdDestination as IEngineeringComposition).Invoke("Import", parameter);
            }
            else if (importdDestination is TagFolder)
                (importdDestination as TagFolder).TagTables.Import(importFileInfo, importOption);
            else if (importdDestination is ScreenFolder)
                (importdDestination as ScreenFolder).Screens.Import(importFileInfo, importOption);
            else if (importdDestination is ScreenTemplateFolder)
                (importdDestination as ScreenTemplateFolder).ScreenTemplates.Import(importFileInfo, importOption);
            else if (importdDestination is ScreenPopupFolder)
                (importdDestination as ScreenPopupFolder).ScreenPopups.Import(importFileInfo, importOption);
            else if (importdDestination is ScreenSlideinSystemFolder)
                (importdDestination as ScreenSlideinSystemFolder).ScreenSlideins.Import(importFileInfo, importOption);
            else if (importdDestination is VBScriptFolder)
                (importdDestination as VBScriptFolder).VBScripts.Import(importFileInfo, importOption);
            else if (importdDestination is ScreenGlobalElements)
                (importdDestination.Parent as HmiTarget)?.ImportScreenGlobalElements(importFileInfo, importOption);
            else if (importdDestination is ScreenOverview)
                (importdDestination.Parent as HmiTarget)?.ImportScreenOverview(importFileInfo, importOption);
        }

        private object CreateSubFolder(object importDestination, string importFolder)
        {
            object subFolder;

            if (importDestination is TagFolder)
            {
                var group = importDestination as TagFolder;
                subFolder = group.Folders.Find(importFolder);
                if (subFolder == null)
                    subFolder = group.Folders.Create(importFolder);
            }
            else if (importDestination is VBScriptFolder)
            {
                var group = importDestination as VBScriptFolder;
                subFolder = group.Folders.Find(importFolder);
                if (subFolder == null)
                    subFolder = group.Folders.Create(importFolder);
            }
            else if (importDestination is ScreenFolder)
            {
                var group = importDestination as ScreenFolder;
                subFolder = group.Folders.Find(importFolder);
                if (subFolder == null)
                    subFolder = group.Folders.Create(importFolder);
            }
            else if (importDestination is ScreenTemplateFolder)
            {
                var group = importDestination as ScreenTemplateFolder;
                subFolder = group.Folders.Find(importFolder);
                if (subFolder == null)
                    subFolder = group.Folders.Create(importFolder);
            }
            else if (importDestination is ScreenPopupFolder)
            {
                var group = importDestination as ScreenPopupFolder;
                subFolder = group.Folders.Find(importFolder);
                if (subFolder == null)
                    subFolder = group.Folders.Create(importFolder);
            }
            else if (importDestination is LibraryTypeFolder)
            {
                var group = importDestination as LibraryTypeFolder;
                subFolder = group.Folders.Find(importFolder);
                if (subFolder == null)
                    subFolder = group.Folders.Create(importFolder);
            }
            else if (importDestination is MasterCopyFolder)
            {
                var group = importDestination as MasterCopyFolder;
                subFolder = group.Folders.Find(importFolder);
                if (subFolder == null)
                    subFolder = group.Folders.Create(importFolder);
            }
            else if (importDestination is DeviceUserGroup)
            {
                var group = importDestination as DeviceUserGroup;
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

        #region hmi target structure

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
            // not available in version 16.0
        }

        #endregion // hmi target structure

        #region mastercopy

        /// <summary>
        /// Create a copy to project from master copy 
        /// </summary>
        /// <param name="copyDestination"></param>
        /// <param name="copySource"></param>
        public void CreateCopyFromMasterCopy(object copyDestination, object copySource)
        {
            var folder = string.Empty;
            var hmiTarget = GetHmiTarget(copyDestination);
            if (copyDestination is ScreenUserFolder ||
                copyDestination is ScreenTemplateUserFolder ||
                copyDestination is VBScriptUserFolder ||
                copyDestination is TagUserFolder)
            {
                folder = copyDestination.GetType().GetProperty("Name")?.GetValue(copyDestination, null) as string;
            }

            if (copySource is MasterCopy masterCopy && hmiTarget != null)
            {
                var contentType = masterCopy.ContentDescriptions.First().ContentType;

                if (contentType == typeof(ScreenUserFolder))
                {
                    CopyToScreenUserFolder(hmiTarget, masterCopy, folder);
                }

                if (contentType == typeof(Screen) || contentType.IsSubclassOf(typeof(Screen)))
                {
                    CopyToScreen(hmiTarget, masterCopy, folder);
                }

                if (contentType == typeof(ScreenTemplateUserFolder))
                {
                    CopyToScreenTemplateUserFolder(hmiTarget, masterCopy, folder);
                }

                if (contentType == typeof(ScreenTemplate) || contentType.IsSubclassOf(typeof(ScreenTemplate)))
                {
                    CopyToScreenTemplate(hmiTarget, masterCopy, folder);
                }

                if (contentType == typeof(VBScriptUserFolder))
                {
                    CopyToVbScriptUserFolder(hmiTarget, masterCopy, folder);
                }

                if (contentType == typeof(VBScript) || contentType.IsSubclassOf(typeof(VBScript)))
                {
                    CopyToVbScript(hmiTarget, masterCopy, folder);
                }

                if (contentType == typeof(TagUserFolder))
                {
                    CopyToTagUserFolder(hmiTarget, masterCopy, folder);
                }

                if (contentType == typeof(TagTable) || contentType.IsSubclassOf(typeof(TagTable)))
                {
                    CopyToTagTable(hmiTarget, masterCopy, folder);
                }
            }
        }

        private void CopyToScreenUserFolder(HmiTarget copyDestination, MasterCopy masterCopy, string folder)
        {
            var processInfo = new ProcessInfo()
            {
                ProcessMessageId = Guid.NewGuid(),
                ProcessMessage = nameof(WinCcProfessionalService) + " - " +
                                 nameof(CopyToScreenUserFolder) + " - " +
                                 copyDestination.Name + " - " +
                                 masterCopy.Name + " - " +
                                 folder + " - " + ExceptionMessage
            };
            WriteTraceLogProxy(processInfo.ProcessMessage);
            throw new InvalidOperationException(ExceptionMessage);
        }

        private void CopyToScreen(HmiTarget copyDestination, MasterCopy masterCopy, string folder)
        {
            if (string.IsNullOrEmpty(folder))
            {
                copyDestination.ScreenFolder.Screens.CreateFrom(masterCopy);
            }
            else
            {
                var destination = copyDestination.ScreenFolder.Folders.Find(folder);
                if (destination != null)
                {
                    destination.Screens.CreateFrom(masterCopy);
                }
            }
        }

        private void CopyToScreenTemplateUserFolder(HmiTarget copyDestination, MasterCopy masterCopy, string folder)
        {
            var processInfo = new ProcessInfo()
            {
                ProcessMessageId = Guid.NewGuid(),
                ProcessMessage = nameof(WinCcProfessionalService) + " - " +
                                 nameof(CopyToScreenUserFolder) + " - " +
                                 copyDestination.Name + " - " +
                                 masterCopy.Name + " - " +
                                 folder + " - " + ExceptionMessage
            };
            WriteTraceLogProxy(processInfo.ProcessMessage);
            throw new InvalidOperationException(ExceptionMessage);
        }

        private void CopyToScreenTemplate(HmiTarget copyDestination, MasterCopy masterCopy, string folder)
        {
            if (string.IsNullOrEmpty(folder))
            {
                copyDestination.ScreenTemplateFolder.ScreenTemplates.CreateFrom(masterCopy);
            }
            else
            {
                var destination = copyDestination.ScreenTemplateFolder.Folders.Find(folder);
                if (destination != null)
                {
                    destination.ScreenTemplates.CreateFrom(masterCopy);
                }
            }
        }

        private void CopyToVbScriptUserFolder(HmiTarget copyDestination, MasterCopy masterCopy, string folder)
        {
            var processInfo = new ProcessInfo()
            {
                ProcessMessageId = Guid.NewGuid(),
                ProcessMessage = nameof(WinCcProfessionalService) + " - " +
                                 nameof(CopyToScreenUserFolder) + " - " +
                                 copyDestination.Name + " - " +
                                 masterCopy.Name + " - " +
                                 folder + " - " + ExceptionMessage
            };
            WriteTraceLogProxy(processInfo.ProcessMessage);
            throw new InvalidOperationException(ExceptionMessage);
        }

        private void CopyToVbScript(HmiTarget copyDestination, MasterCopy masterCopy, string folder)
        {
            if (string.IsNullOrEmpty(folder))
            {
                copyDestination.VBScriptFolder.VBScripts.CreateFrom(masterCopy);
            }
            else
            {
                var destination = copyDestination.VBScriptFolder.Folders.Find(folder);
                if (destination != null)
                {
                    destination.VBScripts.CreateFrom(masterCopy);
                }
            }
        }

        private void CopyToTagUserFolder(HmiTarget copyDestination, MasterCopy masterCopy, string folder)
        {
            var processInfo = new ProcessInfo()
            {
                ProcessMessageId = Guid.NewGuid(),
                ProcessMessage = nameof(WinCcProfessionalService) + " - " +
                                 nameof(CopyToScreenUserFolder) + " - " +
                                 copyDestination.Name + " - " +
                                 masterCopy.Name + " - " +
                                 folder + " - " + ExceptionMessage
            };
            WriteTraceLogProxy(processInfo.ProcessMessage);
            throw new InvalidOperationException(ExceptionMessage);
        }

        private void CopyToTagTable(HmiTarget copyDestination, MasterCopy masterCopy, string folder)
        {
            if (string.IsNullOrEmpty(folder))
            {
                copyDestination.TagFolder.TagTables.CreateFrom(masterCopy);
            }
            else
            {
                var destination = copyDestination.TagFolder.Folders.Find(folder);
                if (destination != null)
                {
                    destination.TagTables.CreateFrom(masterCopy);
                }
            }
        }

        private HmiTarget GetHmiTarget(object copyDestination)
        {
            try
            {
                object parent;
                var item = copyDestination;
                var found = false;

                while (true)
                {
                    parent = item.GetType().GetProperty("Parent")?.GetValue(item, null);
                    if (parent is HmiTarget)
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
                    return parent as HmiTarget;
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
            if (copyDestination is ScreenUserFolder screenUserFolder && copySource is ScreenLibraryTypeVersion screenLibraryTypeVersion)
            {
                CopyToScreenUserFolder(screenUserFolder, screenLibraryTypeVersion);
            }

            if (copyDestination is ScreenSystemFolder screenSystemFolder)
            {
                CopyToScreenSystemFolder(screenSystemFolder);
            }

            if (copyDestination is VBScriptUserFolder vbScriptUserFolder && copySource is VBScriptLibraryTypeVersion vbScriptLibraryTypeVersion)
            {
                CopyToVbScriptUserFolder(vbScriptUserFolder, vbScriptLibraryTypeVersion);
            }

            if (copyDestination is VBScriptSystemFolder vbScriptSystemFolder)
            {
                CopyToVbScriptSystemFolder(vbScriptSystemFolder);
            }
        }

        private void CopyToScreenUserFolder(ScreenUserFolder screenUserFolder, ScreenLibraryTypeVersion screenLibraryTypeVersion)
        {
            screenUserFolder.Screens.CreateFrom(screenLibraryTypeVersion);
        }

        private void CopyToScreenSystemFolder(ScreenSystemFolder screenSystemFolder)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(WinCcProfessionalService) + " - " + nameof(CopyToScreenSystemFolder) };
            WriteTraceLogProxy(processInfo.ProcessMessage + " - Copy to ScreenSystemFolder is not supported! Please select sub group as destination!");
        }

        private void CopyToVbScriptUserFolder(VBScriptUserFolder vbScriptUserFolder, VBScriptLibraryTypeVersion vbScriptLibraryTypeVersion)
        {
            vbScriptUserFolder.VBScripts.CreateFrom(vbScriptLibraryTypeVersion);
        }

        private void CopyToVbScriptSystemFolder(VBScriptSystemFolder vbScriptSystemFolder)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(WinCcProfessionalService) + " - " + nameof(CopyToVbScriptSystemFolder) };
            WriteTraceLogProxy(processInfo.ProcessMessage + " - Copy to VBScriptSystemFolder is not supported! Please select sub group as destination!");
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
