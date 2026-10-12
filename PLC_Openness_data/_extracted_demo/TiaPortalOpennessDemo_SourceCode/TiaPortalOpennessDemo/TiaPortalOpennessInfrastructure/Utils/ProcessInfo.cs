using System;

namespace TiaPortalOpennessInfrastructure.Utils
{
    /// <summary>
    /// Implementation of process info object
    /// </summary>
    public class ProcessInfo
    {
        #region fields

        private Guid _processMessageId;
        private string _processMessage;

        #endregion // fields

        #region ctor
        #endregion // ctor

        #region properties

        /// <summary>
        /// Id of a long run process
        /// </summary>
        public Guid ProcessMessageId
        {
            get => _processMessageId;
            set => _processMessageId = value;
        }

        /// <summary>
        /// process description for display to the user
        /// </summary>
        public string ProcessMessage
        {
            get => _processMessage;
            set => _processMessage = value;
        }

        #endregion // properties

    }
}
