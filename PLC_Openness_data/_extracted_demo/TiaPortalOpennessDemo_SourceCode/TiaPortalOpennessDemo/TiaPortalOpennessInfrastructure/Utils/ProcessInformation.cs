using System.Collections.Generic;

namespace TiaPortalOpennessInfrastructure.Utils
{
    /// <summary>
    /// Container für process infos
    /// </summary>
    public class ProcessInformation
    {
        #region fields

        private IList<ProcessInfo> _processInfos;

        #endregion // fields

        #region ctor

        /// <summary>
        /// default constructor
        /// </summary>
        public ProcessInformation()
        {
            ProcessInfos = new List<ProcessInfo>();
        }

        #endregion // ctor

        #region properties

        /// <summary>
        /// List of process infos
        /// </summary>
        public IList<ProcessInfo> ProcessInfos
        {
            get => _processInfos;
            set => _processInfos = value;
        }

        #endregion // properties

        #region methods

        /// <summary>
        /// Add process info to the list of process infos
        /// </summary>
        /// <param name="processInfo"></param>
        public void Add(ProcessInfo processInfo)
        {
            ProcessInfos.Add(processInfo);
        }

        #endregion // methods
    }
}
