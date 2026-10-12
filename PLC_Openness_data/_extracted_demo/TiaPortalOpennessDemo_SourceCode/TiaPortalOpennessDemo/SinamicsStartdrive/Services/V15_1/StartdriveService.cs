extern alias V15_1;
using System;
using System.Diagnostics;
using System.Linq;
using TiaPortalOpennessAdapter.Models.V15_1;
using TiaPortalOpennessAdapterBase.Base;
using TiaPortalOpennessAdapterBase.Enums;
using TiaPortalOpennessAdapterContracts;
using TiaPortalOpennessInfrastructure.Contracts;
using V15_1::Siemens.Engineering.HW;
using V15_1::Siemens.Engineering.MC.Drives;

namespace SinamicsStartdrive.Services.V15_1
{
    /// <summary>
    /// Implementation of start drive service
    /// </summary>
    public class StartdriveService : IStartdriveService
    {
        #region fields

        private ITraceLogService _traceLogService;

        #endregion // fields

        #region ctor

        public StartdriveService(ITraceLogService traceLogService)
        {
            _traceLogService = traceLogService;
        }

        #endregion // ctor

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
            GetSinamicsStructure(deviceItem as DeviceItem, treeItem as TreeItem, engineeringProjectItem as ProjectItem, engineeringProjectModel as EngineeringProjectModel);
        }

        private void GetSinamicsStructure(DeviceItem deviceItem, TreeItem treeItem, ProjectItem engineeringProjectItem, EngineeringProjectModel engineeringProjectModel)
        {
            var driveObjectComposition = CheckDriveSoftware(deviceItem);
            if (driveObjectComposition != null)
            {
                GetSDrives(driveObjectComposition, treeItem, engineeringProjectItem, engineeringProjectModel);
            }

            if (deviceItem.Items != null && deviceItem.Items.Count > 0)
            {
                driveObjectComposition = CheckDriveSoftware(deviceItem.Items.First());
                if (driveObjectComposition != null)
                {
                    GetGDrives(driveObjectComposition, treeItem, engineeringProjectItem, engineeringProjectModel);
                }
            }
        }

        private void GetSDrives(DriveObjectComposition driveObjectComposition, TreeItem treeItem, ProjectItem engineeringProjectItem, EngineeringProjectModel engineeringProjectModel)
        {
            GetDrives(driveObjectComposition, treeItem, engineeringProjectItem, engineeringProjectModel);
        }

        private void GetGDrives(DriveObjectComposition driveObjectComposition, TreeItem treeItem, ProjectItem engineeringProjectItem, EngineeringProjectModel engineeringProjectModel)
        {
            GetDrives(driveObjectComposition, treeItem, engineeringProjectItem, engineeringProjectModel);
        }

        private void GetDrives(DriveObjectComposition driveObjectComposition, TreeItem treeItem, ProjectItem engineeringProjectItem, EngineeringProjectModel engineeringProjectModel)
        {
            var guid = Guid.NewGuid();
            var subTreeItem = new TreeItem() { Header = "Drive units", Tag = guid };
            engineeringProjectItem.ProjectItems.Add(new ProjectItem() { Header = subTreeItem.Header, Tag = guid, DeviceItem = driveObjectComposition, TypeInfo = TreeTypeInformation.IsSoftwareUnitGroup });

            foreach (var drive in driveObjectComposition)
            {
                guid = Guid.NewGuid();
                var subsubTreeItem = new TreeItem() { Header = drive.GetType().Name, Tag = guid };
                engineeringProjectItem.ProjectItems.Add(new ProjectItem() { Header = subsubTreeItem.Header, Tag = guid, DeviceItem = drive, TypeInfo = TreeTypeInformation.IsPlcSystemTypeGroup });

                foreach (var parameter in drive.Parameters)
                {
                    guid = Guid.NewGuid();
                    subsubTreeItem.Items.Add(new TreeItem() { Header = parameter.Name, Tag = guid });
                    engineeringProjectItem.ProjectItems.Add(new ProjectItem() { Header = parameter.Name, Tag = guid, DeviceItem = parameter, TypeInfo = TreeTypeInformation.IsPlcSystemType });
                }
                subTreeItem.Items.Add(subsubTreeItem);
            }

            treeItem.Items.Add(subTreeItem);
        }

        private DriveObjectComposition CheckDriveSoftware(DeviceItem item)
        {
            var driveObjectContainer = item.GetService<DriveObjectContainer>();

            if (driveObjectContainer != null && driveObjectContainer?.DriveObjects != null)
            {
                Debug.WriteLine("Check Drive object container " + item.Name);
                return driveObjectContainer.DriveObjects;
            }

            return null;
        }

        #endregion // tree structure
    }
}
