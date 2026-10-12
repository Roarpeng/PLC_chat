extern alias V17_0;
using System.Collections.Generic;
using System.Diagnostics;
using TiaPortalOpennessAdapterBase.Models;
using V17_0::Siemens.Engineering.Hmi;
using V17_0::Siemens.Engineering.HW;
using V17_0::Siemens.Engineering.HW.Features;
using V17_0::Siemens.Engineering.SW;
using V17_0::Siemens.Engineering.SW.Blocks;
using V17_0::Siemens.Engineering.SW.ExternalSources;
using V17_0::Siemens.Engineering.SW.Tags;
using V17_0::Siemens.Engineering.SW.TechnologicalObjects;
using V17_0::Siemens.Engineering.SW.Types;
using V17_0::Siemens.Engineering.SW.Units;
using V17_0::Siemens.Engineering.SW.WatchAndForceTables;

namespace TiaPortalOpennessAdapter.Models.V17_0
{
    /// <summary>
    /// Engineering project model definition
    /// </summary>
    public class EngineeringProjectModel : ObservableObject
    {
        #region fields

        #endregion // fields

        #region methods

        #region plc software

        /// <summary>
        /// Check for plc software
        /// </summary>
        /// <param name="item"></param>
        /// <returns></returns>
        public PlcSoftware CheckPlcSoftware(DeviceItem item)
        {
            var softwareContainer = item.GetService<SoftwareContainer>();

            if (softwareContainer != null && softwareContainer.Software != null && softwareContainer.Software is PlcSoftware)
            {
                Debug.WriteLine("Check Plc Software " + item.Name);
                return softwareContainer.Software as PlcSoftware;
            }
            return null;
        }

        /// <summary>
        /// Retrieve plc units system group from plc software
        /// </summary>
        /// <param name="plcSoftware"></param>
        /// <returns></returns>
        public PlcUnitSystemGroup GetPlcSoftwareUnitsGroup(PlcSoftware plcSoftware)
        {
            PlcUnitSystemGroup plcSoftwareUnitsGroup = null;

            var unitProvider = plcSoftware.GetService<PlcUnitProvider>();
            if (unitProvider != null)
            {
                plcSoftwareUnitsGroup = unitProvider.UnitGroup;
            }

            return plcSoftwareUnitsGroup;
        }

        /// <summary>
        /// Retrieve plc software units form plc software
        /// </summary>
        /// <param name="plcSoftware"></param>
        /// <returns></returns>
        public IList<PlcUnit> GetPlcSoftwareUnits(PlcSoftware plcSoftware)
        {
            IList<PlcUnit> plcUnits = new List<PlcUnit>();

            var unitProvider = plcSoftware.GetService<PlcUnitProvider>();
            if (unitProvider != null)
            {
                foreach (var unit in unitProvider.UnitGroup.Units)
                {
                    plcUnits.Add(unit);
                }
            }

            return plcUnits;
        }

        /// <summary>
        /// Retrieve the block group from plc software
        /// </summary>
        /// <param name="plcSoftware"></param>
        /// <returns></returns>
        public PlcBlockSystemGroup GetPlcBlockGroup(PlcSoftware plcSoftware)
        {
            return plcSoftware.BlockGroup;
        }

        /// <summary>
        /// Retrieve the blocks from plc block composition
        /// </summary>
        /// <param name="plcBlockComposition"></param>
        /// <returns></returns>
        public IList<PlcBlock> GetPlcBlocks(PlcBlockComposition plcBlockComposition)
        {
            IList<PlcBlock> blocks = new List<PlcBlock>();

            foreach (var block in plcBlockComposition)
            {
                blocks.Add(block);
            }

            return blocks;
        }

        /// <summary>
        /// Retrieve the technological instance DB from technological instance DB composition
        /// </summary>
        /// <param name="plcSoftware"></param>
        /// <returns></returns>
        public TechnologicalInstanceDBGroup GetTechnologicalObjectGroup(PlcSoftware plcSoftware)
        {
            return plcSoftware.TechnologicalObjectGroup;
        }

        /// <summary>
        /// Retrieve a list of technological instance DB objects
        /// </summary>
        /// <param name="technologicalInstanceDbComposition"></param>
        /// <returns></returns>
        public IList<TechnologicalInstanceDB> GetTechnologicalObjects(TechnologicalInstanceDBComposition technologicalInstanceDbComposition)
        {
            IList<TechnologicalInstanceDB> technologicalObjectNames = new List<TechnologicalInstanceDB>();

            foreach (var technologicalObject in technologicalInstanceDbComposition)
            {
                technologicalObjectNames.Add(technologicalObject);
            }

            return technologicalObjectNames;
        }

        /// <summary>
        /// Retrieve the external source group from plc software
        /// </summary>
        /// <param name="plcSoftware"></param>
        /// <returns></returns>
        public PlcExternalSourceGroup GetPlcExternalSourceGroup(PlcSoftware plcSoftware)
        {
            return plcSoftware.ExternalSourceGroup;
        }

        /// <summary>
        /// Retrieve a list of external source objects from external source composition
        /// </summary>
        /// <param name="plcExternalSourceComposition"></param>
        /// <returns></returns>
        public IList<PlcExternalSource> GetPlcExternalSources(PlcExternalSourceComposition plcExternalSourceComposition)
        {
            IList<PlcExternalSource> externalSourceNames = new List<PlcExternalSource>();

            foreach (var externalSource in plcExternalSourceComposition)
            {
                externalSourceNames.Add(externalSource);
            }

            return externalSourceNames;
        }

        /// <summary>
        /// Retrieve the tag table system group from plc software
        /// </summary>
        /// <param name="plcSoftware"></param>
        /// <returns></returns>
        public PlcTagTableSystemGroup GetPlcTagTableSystemGroup(PlcSoftware plcSoftware)
        {
            return plcSoftware.TagTableGroup;
        }

        /// <summary>
        /// Retrieve a list of plc tag tables from tag table composition
        /// </summary>
        /// <param name="plcTagTableComposition"></param>
        /// <returns></returns>
        public IList<PlcTagTable> GetPlcTagTables(PlcTagTableComposition plcTagTableComposition)
        {
            IList<PlcTagTable> tagTableNames = new List<PlcTagTable>();

            foreach (var plcTagTable in plcTagTableComposition)
            {
                tagTableNames.Add(plcTagTable);
            }

            return tagTableNames;
        }

        /// <summary>
        /// Retrieve the type system group from plc software
        /// </summary>
        /// <param name="plcSoftware"></param>
        /// <returns></returns>
        public PlcTypeSystemGroup GetPlcTypeGroup(PlcSoftware plcSoftware)
        {
            return plcSoftware.TypeGroup;
        }

        /// <summary>
        /// Retrieve a list of system type groups from plc system type group composition
        /// </summary>
        /// <param name="plcSystemTypeGroupComposition"></param>
        /// <returns></returns>
        public IList<PlcSystemTypeGroup> GetPlcSystemTypeGroups(PlcSystemTypeGroupComposition plcSystemTypeGroupComposition)
        {
            IList<PlcSystemTypeGroup> plcSystemTypeGroupNames = new List<PlcSystemTypeGroup>();

            foreach (var plcSystemTypeGroup in plcSystemTypeGroupComposition)
            {
                plcSystemTypeGroupNames.Add(plcSystemTypeGroup);
            }

            return plcSystemTypeGroupNames;
        }

        /// <summary>
        /// Retrieve a list of plc types from plc type composition
        /// </summary>
        /// <param name="plcTypeComposition"></param>
        /// <returns></returns>
        public IList<PlcType> GetPlcTypes(PlcTypeComposition plcTypeComposition)
        {
            IList<PlcType> plcTypeNames = new List<PlcType>();

            foreach (var plcType in plcTypeComposition)
            {
                plcTypeNames.Add(plcType);
            }

            return plcTypeNames;
        }

        /// <summary>
        /// Retrieve a list of plc type user groups from plc type user group composition
        /// </summary>
        /// <param name="plcTypeUserGroupComposition"></param>
        /// <returns></returns>
        public IList<PlcTypeUserGroup> GetPlcTypeUserGroups(PlcTypeUserGroupComposition plcTypeUserGroupComposition)
        {
            IList<PlcTypeUserGroup> plcTypeUserGroupNames = new List<PlcTypeUserGroup>();

            foreach (var plcTypeUserGroup in plcTypeUserGroupComposition)
            {
                plcTypeUserGroupNames.Add(plcTypeUserGroup);
            }

            return plcTypeUserGroupNames;
        }

        /// <summary>
        /// Retrieve watch and force table system group from plc software
        /// </summary>
        /// <param name="plcSoftware"></param>
        /// <returns></returns>
        public PlcWatchAndForceTableSystemGroup GetWatchAndForceTableGroup(PlcSoftware plcSoftware)
        {
            return plcSoftware.WatchAndForceTableGroup;
        }

        /// <summary>
        /// Retrieve a list of plc force tables from force table composition
        /// </summary>
        /// <param name="plcForceTableComposition"></param>
        /// <returns></returns>
        public IList<PlcForceTable> GetWatchAndForceTables(PlcForceTableComposition plcForceTableComposition)
        {
            IList<PlcForceTable> watchAndForceTableNames = new List<PlcForceTable>();

            foreach (var watchAndForceTable in plcForceTableComposition)
            {
                watchAndForceTableNames.Add(watchAndForceTable);
            }

            return watchAndForceTableNames;
        }

        #endregion // plc software

        #region hmi target

        /// <summary>
        /// Check for hmi target
        /// </summary>
        /// <param name="item"></param>
        /// <returns></returns>
        public HmiTarget CheckHmiTarget(DeviceItem item)
        {
            var softwareContainer = item.GetService<SoftwareContainer>();

            if (softwareContainer != null && softwareContainer.Software != null && softwareContainer.Software is HmiTarget)
            {
                return softwareContainer.Software as HmiTarget;
            }
            return null;
        }

        /// <summary>
        /// Retrieve hmi target name
        /// </summary>
        /// <param name="hmiTarget"></param>
        /// <returns></returns>
        public string GetHmiTargetName(HmiTarget hmiTarget)
        {
            return hmiTarget.Name;
        }

        #endregion // hmi target

        #endregion // methods
    }
}
