using System;
using System.Collections.Generic;
using System.IO;
using System.Threading.Tasks;
using TiaPortalOpennessAdapterBase.Base;
using TiaPortalOpennessAdapterBase.Enums;
using TiaPortalOpennessInfrastructure.Contracts;

namespace TiaPortalOpennessAdapterContracts
{
    public interface IProjectServiceProvider : IOpennessService
    {
        #region properties

        #endregion // properties

        #region methods

        void Initialize(IOpennessDemoModel opennessDemoModel, ITraceLogService traceLogService,
            ISettingsService serviceService, ITiaPortalServiceProvider tiaPortalServiceProvider,
            IPlcSoftwareService plcSoftwareService, IHmiSoftwareService hmiSoftwareService, IHmiTargetService hmiTargetService, IStartdriveService sinamicsService);

        #region project

        Task<string> CreateNewProjectAsync(IOpennessDemoModel opennessDemoModel);

        Task<string> OpenProjectAsync(string projectPath);

        Task<string> LoadProjectAsync();

        Task<bool> SaveProjectAsync();

        Task<int> CloseProjectAsync();

        string GetCurrentProjectName();

        DirectoryInfo GetCurrentProjectPath();

        object GetCurrentProject();

        void CreateNewGroup(string groupName, string parentGroup, Guid tag, bool logicalTree);

        #endregion // project

        #region import/export

        Task<bool> CaxImportAsync(FileInfo importFileInfo, CaxImportOption importOption);

        Task<bool> CaxExportAsync();

        Task<bool> ImportElementAsync(IList<FileInfo> importFileInfos, bool importWithOverride, string header, Guid tag, bool logical);

        Task<bool> ImportStructureAsync(string importFolderPath, string header, Guid tag, bool logical);

        Task<bool> ExportStructureAsync(string header, Guid tag, bool logical);

        bool CheckIfCanImportElement(string header, Guid tag, bool logical);

        bool CheckIfCanImportStructure(string header, Guid tag, bool logical);

        bool CheckIfCanExportExecute(string header, Guid tag, bool logical);

        object GetExportableObject(ProjectItem projectItem);

        #endregion // import/export

        #region plc

        Task<bool> AddExternalSourceAsync(IList<FileInfo> sourceFileInfos, string header, Guid tag, bool logical);

        Task<bool> GenerateBlockFromSourceAsync(string header, Guid tag, bool logical);

        Task<bool> GenerateSourceFromBlockAsync(FileInfo destinationFileInfo, string header, Guid tag, bool logical);

        bool CheckIfCanAddExternalSource(string header, Guid tag, bool logical);

        bool CheckIfCanGenerateBlockFromSource(string header, Guid tag, bool logical);

        bool CheckIfCanGenerateSourceFromBlock(string header, Guid tag, bool logical);

        #endregion // plc

        #region editor

        void ShowEditor(string viewName);

        void OpenEditor(string header, Guid tag, bool logical);

        #endregion // editor

        #region compiler

        void DoCompile(string header, Guid tag, bool logical);

        bool CheckIfCompilable(string header, Guid tag, bool logical);

        #endregion // compiler

        #region content

        Dictionary<string, string> ReadProperties(string header, Guid tag);

        #endregion // content

        #region tree structure

        Tree GetProjectTree();

        Task<Tree> LoadTreeStructureAsync(bool loadLogicalFirst);

        Task<Tree> LoadLocalSessionTreeStructureAsync(bool loadLogicalFirst);

        Tree GetLogicalTree();

        Tree GetPhysicalTree();

        TreeTypeInformation GetTypeInformation(string header, Guid tag, bool logical);

        object GetTreeItemObject(string header, Guid tag, bool logical);

        IList<ProjectItem> GetTreeTypeItems(object itemType, bool logical);

        #endregion // tree structure

        #endregion // methods
    }
}
