using System;
using System.Runtime.Serialization;

namespace TiaPortalOpennessInfrastructure.Exceptions
{
    /// <summary>
    /// Implementation of custom exception to decouple the tia portal demo application from the siemens api
    /// </summary>
    [Serializable]
    public class OpennessApiException : Exception
    {
        /// <summary>
        /// default constructor
        /// </summary>
        public OpennessApiException()
        {

        }

        /// <summary>
        /// Constructor with parameter
        /// </summary>
        /// <param name="message">exception message as string</param>
        public OpennessApiException(string message)
            : base(message)
        {

        }

        /// <summary>
        /// Constructor with parameter
        /// </summary>
        /// <param name="format">a composite format string</param>
        /// <param name="args">object array that contains the objects to format</param>
        public OpennessApiException(string format, params object[] args)
            : base(string.Format(format, args))
        {

        }

        /// <summary>
        /// Constructor with parameter
        /// </summary>
        /// <param name="message">exception message as string</param>
        /// <param name="innerException">the exception that is cause of the current exception or null</param>
        public OpennessApiException(string message, Exception innerException)
            : base(message, innerException)
        {

        }

        /// <summary>
        /// Constructor with parameter
        /// </summary>
        /// <param name="format">a composite format string</param>
        /// <param name="innerException">the exception that is cause of the current exception or null</param>
        /// <param name="args">object array that contains the objects to format</param>
        public OpennessApiException(string format, Exception innerException, params object[] args)
            : base(string.Format(format, args), innerException)
        {

        }

        /// <summary>
        /// Constructor with parameter
        /// </summary>
        /// <param name="info">the serialization info that holds the serialization object data</param>
        /// <param name="context">the streaming context that holds contextual information about the source or destination</param>
        public OpennessApiException(SerializationInfo info, StreamingContext context)
            : base(info, context)
        {

        }
    }
}
