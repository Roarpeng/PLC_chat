using System;
using System.Collections.Generic;
using System.IO;
using System.Threading.Tasks;
using TiaPortalOpennessAdapterBase.Base;
using TiaPortalOpennessAdapterBase.Enums;
using TiaPortalOpennessAdapterBase.Models;
using TiaPortalOpennessInfrastructure.Contracts;

namespace TiaPortalOpennessAdapterContracts
{
    public interface ILibraryServiceProvider : IOpennessService
    {

        void Initialize(IOpennessDemoModel opennessDemoModel, ITraceLogService traceLogService,
            ITiaPortalServiceProvider tiaPortalServiceProvider, IProjectServiceProvider projectServiceProvider,
            IMultiuserServiceProvider multiuserServiceProvider,
            IPlcSoftwareService plcSoftwareService, IHmiSoftwareService hmiSoftwareService, IHmiTargetService hmiTargetService, IStartdriveService startdriveService);

        IList<LibraryInfo> GlobalLibraryInfos { get; set; }

        Task<int> OpenLibraryAsync(bool globalLibrary);

        Task<bool> OpenGlobalLibraryAsync(FileInfo path, bool userLibrary);

        Task<bool> CreateNewGlobalLibraryAsync(DirectoryInfo targetInfo, string libraryName);

        Task<bool> SaveGlobalLibraryAsync(string header, Guid tag, bool global);

        Task<bool> UpdateProjectLibraryAsync(string header, Guid tag);

        Task<bool> CloseGlobalLibraryAsync(string header, Guid tag, bool global);

        Tree GetProjectLibraryTree();

        Tree GetGlobalLibraryTree();

        IList<LibraryInfo> GetGlobalLibraryInfos();

        TreeTypeInformation GetTypeInformation(string header, Guid tag, bool global);

        LibraryItem GetLibraryItem(string header, Guid tag, bool global);

        void EditGroup(string groupName, string parentGroup, Guid tag, bool global, bool createNewGroup);

        bool LibraryHasBeenChanged(string header, Guid tag, bool global);

        bool ExportVersion(string header, Guid tag, bool global, FileInfo path, int options);

        bool CopyLibraryVersionToProject(object targetObject, string header, Guid tag, bool global);

        bool CopySourceIsKnownType(string header, Guid tag, bool global);

        void CreateCopyFromMasterCopy(object targetObject, string header, Guid tag, bool global);
    }
}
