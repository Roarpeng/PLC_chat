using System.Collections.Generic;
using System.Threading.Tasks;
using TiaPortalOpennessInfrastructure.Contracts;

namespace TiaPortalOpennessAdapterContracts
{
    public interface ITiaPortalServiceProvider : IOpennessService
    {
        #region properties

        IOpennessDemoModel OpennessDemoModel
        {
            get;
            set;
        }

        #endregion // properties

        #region methods

        void Initialize(IOpennessDemoModel opennessDemoModel, ITraceLogService traceLogService);

        Task<int> OpenTiaPortalAsync();

        Task<string> CreateProjectAsync(IOpennessDemoModel opennessDemoModel);

        Task<bool> ConnectTiaPortalAsync(int processId);

        Task<int> DisconnectTiaPortalAsync();

        Task CloseTiaPortal();

        int GetCurrentProcessId();

        IList<string> GetTiaPortalProcesses();
        IList<string> GetTiaPortalProjectInformation();

        object GetProject();

        object GetOpennessEngineeringModel();

        object GetTiaPortal();

        #endregion // methods
    }
}
