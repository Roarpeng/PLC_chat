using System.Collections.Generic;
using TiaPortalOpennessAdapterBase.Enums;
using TiaPortalOpennessAdapterBase.Models;

namespace TiaPortalOpennessAdapterContracts
{
    public interface IOpennessDemoModel
    {
        #region properties

        TreeTypeInformation SelectedTreeType { get; set; }

        ITiaPortalServiceProvider TiaPortalServiceProvider { get; set; }

        ProjectModel ProjectModel { get; set; }

        TiaPortalStartMode TiaPortalStartMode { get; set; }

        int CountLocalSessions { get; set; }

        int CountProjectServer { get; set; }

        int CountProjects { get; set; }

        int CountGlobalLibraries { get; set; }

        int CountSettingsFolders { get; set; }

        bool TiaPortalDisposed { get; set; }

        bool PortalOpened { get; set; }

        bool CanConnect { get; set; }

        bool LocalSessionOpened { get; set; }

        bool DisplayLogicalTreeView { get; set; }

        bool PortalAvailable { get; set; }

        bool IsCompilable { get; set; }

        bool CanImportElement { get; set; }

        bool CanImportStructure { get; set; }

        bool CanExportExecute { get; set; }

        bool CanAddExternalSource { get; set; }

        bool CanGenerateBlockFromSource { get; set; }

        bool CanGenerateSourceFromBlock { get; set; }

        int CurrentProcessId { get; set; }

        int SelectedProcessIndex { get; set; }

        IList<string> TiaPortalProcesses { get; set; }

        IList<string> ProjectInformation { get; set; }

        string SelectedProcessId { get; set; }

        #endregion // properties

        #region methods

        void GetTiaPortalProcesses();

        void SetCurrentProcessId(int processId);

        int GetSelectedProcessId();

        ProjectModel GetProject();

        #endregion // methods
    }
}
