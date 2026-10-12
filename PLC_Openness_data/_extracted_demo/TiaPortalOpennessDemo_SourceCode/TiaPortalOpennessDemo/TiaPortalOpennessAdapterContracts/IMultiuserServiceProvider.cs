using System;
using System.Threading.Tasks;
using TiaPortalOpennessAdapterBase.Base;
using TiaPortalOpennessInfrastructure.Contracts;

namespace TiaPortalOpennessAdapterContracts
{
    public interface IMultiuserServiceProvider : IOpennessService
    {
        void Initialize(IOpennessDemoModel opennessDemoModel, ITraceLogService traceLogService, ITiaPortalServiceProvider tiaPortalServiceProvider, IProjectServiceProvider projectServiceProvider);

        Task<string> OpenLocalSessionAsync(string projectPath);

        Task<bool> SaveLocalSessionAsync();

        Task<Tree> LoadLocalSessionTreeStructureAsync(bool loadLogicalFirst);

        Task<bool> CloseLocalSessionAsync();

        object GetCurrentSession();

        #region editor

        void ShowEditor(string viewName);

        void OpenEditor(string header, Guid tag, bool logical);

        #endregion // editor

    }
}
