using System.Collections.ObjectModel;
using System.Text;

namespace TiaPortalOpennessInfrastructure.Contracts
{
    /// <summary>
    /// Trace log service contract
    /// </summary>
    public interface ITraceLogService
    {
        /// <summary>
        /// Observable list of trace log entries
        /// </summary>
        ObservableCollection<string> List { get; set; }

        /// <summary>
        /// Encoding type
        /// </summary>
        Encoding Encoding { get; }

        /// <summary>
        /// Writes an entry to the trace log list
        /// </summary>
        /// <param name="value"></param>
        void Write(string value);
    }
}
