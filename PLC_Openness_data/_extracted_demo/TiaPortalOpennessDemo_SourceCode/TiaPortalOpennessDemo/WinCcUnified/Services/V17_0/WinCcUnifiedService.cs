extern alias V17_0;
using System;
using System.Windows;
using TiaPortalOpennessAdapterBase.Base;
using TiaPortalOpennessAdapterBase.Enums;
using TiaPortalOpennessAdapterContracts;
using TiaPortalOpennessInfrastructure.Contracts;
using TiaPortalOpennessInfrastructure.Exceptions;
using V17_0::Siemens.Engineering;
using V17_0::Siemens.Engineering.HmiUnified;
using V17_0::Siemens.Engineering.HW;
using V17_0::Siemens.Engineering.HW.Features;


namespace WinCcUnified.Services.V17_0
{
    /// <summary>
    /// Implementation of WinCC unified service
    /// </summary>
    public class WinCcUnifiedService : IHmiSoftwareService
    {
        #region fields

        private const string ExceptionMessage = "This kind of master copy is not supported.";
        private ITraceLogService _traceLogService;

        #endregion // fields

        #region ctor

        public WinCcUnifiedService(ITraceLogService traceLogService)
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
            return false;
        }

        /// <summary>
        /// Retrieve whether item is hmi software
        /// </summary>
        /// <param name="item"></param>
        /// <returns></returns>
        public bool IsHmiSoftware(object item)
        {
            return item is HmiSoftware;
        }

        #endregion // common

        #region hmi tree structure

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
            GetSoftwareStructure(deviceItem as DeviceItem, treeItem as TreeItem, engineeringProjectItem as ProjectItem);
        }

        private void GetSoftwareStructure(DeviceItem deviceItem, TreeItem treeItem, ProjectItem engineeringProjectItem)
        {
            var hmiSoftware = CheckHmiSoftware(deviceItem);
            if (hmiSoftware != null)
            {
                TreeItem subTreeItem = new TreeItem();

                GetAlarmClasses(hmiSoftware, treeItem, engineeringProjectItem);

                //GetAlarmLogs();

                //GetAnalogAlarms();

                //GetAuditTrails();

                //GetConnections();

                //GetDataLogs();

                //GetDiscreteAlarms();

                //GetOpcUaAlarmTypes();

                //GetPlantObjectTags();

                //GetRuntimeSettings();

                GetScreens(hmiSoftware, treeItem, engineeringProjectItem);

                GetSystemTags(hmiSoftware, treeItem, engineeringProjectItem);

                GetTagTables(hmiSoftware, treeItem, engineeringProjectItem);

                GetTags(hmiSoftware, treeItem, engineeringProjectItem);


                var guid = Guid.NewGuid();
                subTreeItem.Header = GetHmiSoftwareName(hmiSoftware);
                subTreeItem.Tag = guid;
                var subEngineeringTreeItem = new ProjectItem() { Header = subTreeItem.Header, Tag = guid, DeviceItem = hmiSoftware };

                treeItem.Items.Add(subTreeItem);
                engineeringProjectItem.ProjectItems.Add(subEngineeringTreeItem);
            }
        }

        private void GetAlarmClasses(HmiSoftware hmiSoftware, TreeItem treeItem, ProjectItem engineeringProjectItem)
        {
            var guid = Guid.NewGuid();
            var subTreeItem = new TreeItem() { Header = "HMI alarms", Tag = guid };
            engineeringProjectItem.ProjectItems.Add(new ProjectItem() { Header = subTreeItem.Header, Tag = guid, DeviceItem = hmiSoftware, TypeInfo = TreeTypeInformation.IsHmiAlarmGroup });

            foreach (var alarmClass in hmiSoftware.AlarmClasses)
            {
                guid = Guid.NewGuid();
                subTreeItem.Items.Add(new TreeItem() { Header = alarmClass.Name, Tag = guid });
                engineeringProjectItem.ProjectItems.Add(new ProjectItem() { Header = alarmClass.Name, Tag = guid, DeviceItem = alarmClass, TypeInfo = TreeTypeInformation.IsHmiAlarm });
            }

            treeItem.Items.Add(subTreeItem);
        }

        //private void GetAlarmLogs(HmiSoftware hmiSoftware, TreeItem treeItem, ProjectItem engineeringProjectItem)
        //{

        //}

        //private void GetAnalogAlarms(HmiSoftware hmiSoftware, TreeItem treeItem, ProjectItem engineeringProjectItem)
        //{

        //}

        //private void GetAuditTrails(HmiSoftware hmiSoftware, TreeItem treeItem, ProjectItem engineeringProjectItem)
        //{

        //}

        //private void GetConnections(HmiSoftware hmiSoftware, TreeItem treeItem, ProjectItem engineeringProjectItem)
        //{

        //}

        //private void GetDataLogs(HmiSoftware hmiSoftware, TreeItem treeItem, ProjectItem engineeringProjectItem)
        //{

        //}

        //private void GetDiscreteAlarms(HmiSoftware hmiSoftware, TreeItem treeItem, ProjectItem engineeringProjectItem)
        //{

        //}

        //private void GetOpcUaAlarmTypes(HmiSoftware hmiSoftware, TreeItem treeItem, ProjectItem engineeringProjectItem)
        //{

        //}

        //private void GetPlantObjectTags(HmiSoftware hmiSoftware, TreeItem treeItem, ProjectItem engineeringProjectItem)
        //{

        //}

        //private void GetRuntimeSettings(HmiSoftware hmiSoftware, TreeItem treeItem, ProjectItem engineeringProjectItem)
        //{

        //}

        private void GetScreens(HmiSoftware hmiSoftware, TreeItem treeItem, ProjectItem engineeringProjectItem)
        {
            var guid = Guid.NewGuid();
            var subTreeItem = new TreeItem() { Header = "Screens", Tag = guid };
            engineeringProjectItem.ProjectItems.Add(new ProjectItem() { Header = subTreeItem.Header, Tag = guid, DeviceItem = hmiSoftware, TypeInfo = TreeTypeInformation.IsHmiScreenGroup });

            foreach (var screen in hmiSoftware.Screens)
            {
                guid = Guid.NewGuid();
                subTreeItem.Items.Add(new TreeItem() { Header = screen.Name, Tag = guid });
                engineeringProjectItem.ProjectItems.Add(new ProjectItem() { Header = screen.Name, Tag = guid, DeviceItem = screen, TypeInfo = TreeTypeInformation.IsHmiScreen });
            }

            treeItem.Items.Add(subTreeItem);
        }

        private void GetSystemTags(HmiSoftware hmiSoftware, TreeItem treeItem, ProjectItem engineeringProjectItem)
        {
            var guid = Guid.NewGuid();
            var subTreeItem = new TreeItem() { Header = "HMI system tags", Tag = guid };
            engineeringProjectItem.ProjectItems.Add(new ProjectItem() { Header = subTreeItem.Header, Tag = guid, DeviceItem = hmiSoftware, TypeInfo = TreeTypeInformation.IsHmiSystemTagGroup });

            foreach (var systemTag in hmiSoftware.SystemTags)
            {
                guid = Guid.NewGuid();
                subTreeItem.Items.Add(new TreeItem() { Header = systemTag.Name, Tag = guid });
                engineeringProjectItem.ProjectItems.Add(new ProjectItem() { Header = systemTag.Name, Tag = guid, DeviceItem = systemTag, TypeInfo = TreeTypeInformation.IsHmiSystemTag });
            }

            treeItem.Items.Add(subTreeItem);

        }

        private void GetTagTables(HmiSoftware hmiSoftware, TreeItem treeItem, ProjectItem engineeringProjectItem)
        {
            var guid = Guid.NewGuid();
            var subTreeItem = new TreeItem() { Header = "HMI tag tables", Tag = guid };
            engineeringProjectItem.ProjectItems.Add(new ProjectItem() { Header = subTreeItem.Header, Tag = guid, DeviceItem = hmiSoftware, TypeInfo = TreeTypeInformation.IsHmiTagTableGroup });

            foreach (var tagTable in hmiSoftware.TagTables)
            {
                guid = Guid.NewGuid();
                subTreeItem.Items.Add(new TreeItem() { Header = tagTable.Name, Tag = guid });
                engineeringProjectItem.ProjectItems.Add(new ProjectItem() { Header = tagTable.Name, Tag = guid, DeviceItem = tagTable, TypeInfo = TreeTypeInformation.IsHmiTagTable });
            }

            treeItem.Items.Add(subTreeItem);

        }

        private void GetTags(HmiSoftware hmiSoftware, TreeItem treeItem, ProjectItem engineeringProjectItem)
        {
            var guid = Guid.NewGuid();
            var subTreeItem = new TreeItem() { Header = "HMI tags", Tag = guid };
            engineeringProjectItem.ProjectItems.Add(new ProjectItem() { Header = subTreeItem.Header, Tag = guid, DeviceItem = hmiSoftware, TypeInfo = TreeTypeInformation.IsHmiTagGroup });

            foreach (var tag in hmiSoftware.Tags)
            {
                guid = Guid.NewGuid();
                subTreeItem.Items.Add(new TreeItem() { Header = tag.Name, Tag = guid });
                engineeringProjectItem.ProjectItems.Add(new ProjectItem() { Header = tag.Name, Tag = guid, DeviceItem = tag, TypeInfo = TreeTypeInformation.IsHmiTag });
            }

            treeItem.Items.Add(subTreeItem);


        }

        //private void CreateScreenInstance()
        //{

        //}

        private static HmiSoftware CheckHmiSoftware(DeviceItem item)
        {
            var softwareContainer = item.GetService<SoftwareContainer>();

            if (softwareContainer != null && softwareContainer.Software != null && softwareContainer.Software is HmiSoftware)
            {
                return softwareContainer.Software as HmiSoftware;
            }
            return null;
        }

        private string GetHmiSoftwareName(HmiSoftware hmiSoftware)
        {
            return hmiSoftware.Name;
        }

        //private IList<string> GetBlockNames(PlcBlockComposition plcBlockComposition)
        //{
        //    IList<string> blockNames = new List<string>();

        //    foreach (var block in plcBlockComposition)
        //    {
        //        blockNames.Add(block.Name);
        //    }

        //    return blockNames;
        //}

        #endregion // hmi tree structure

        #region mastercopy

        /// <summary>
        /// Create a copy to project from master copy, not supported in version 17.0 
        /// </summary>
        /// <param name="copyDestination"></param>
        /// <param name="copySource"></param>
        public void CreateCopyFromMasterCopy(object copyDestination, object copySource)
        {
            try
            {
                throw new InvalidOperationException(ExceptionMessage);
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
        /// Retrieve the item as hmi software
        /// </summary>
        /// <param name="item"></param>
        /// <returns></returns>
        public object GetHmiSoftware(object item)
        {
            if (item is HmiSoftware hmiSoftware)
            {
                return hmiSoftware;
            }

            return null;
        }

        #endregion // mastercopy

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
