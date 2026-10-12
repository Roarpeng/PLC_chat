using System;

namespace TiaPortalOpennessInfrastructure.Exceptions
{
    /// <summary>
    /// Implementation of custom exception handler to wrap api exceptions
    /// </summary>
    public static class OpennessApiExceptionHandler
    {
        /// <summary>
        /// Method to wrap a siemens engineering exception
        /// </summary>
        /// <param name="exception"></param>
        /// <returns></returns>
        public static OpennessApiException CatchedEngineeringException(Exception exception)
        {
            var description = "An error occurred when accessing the openness api interface, but the last valid state is recoverable! \n\nSee the trace log for more information.";

            return new OpennessApiException(description, exception);
        }

        /// <summary>
        /// Method to wrap a siemens non recoverable exception
        /// </summary>
        /// <param name="exception"></param>
        /// <returns></returns>
        public static OpennessApiException CatchedNonRecoverableException(Exception exception)
        {
            var description = "An error occurred when accessing the openness api interface and the last valid state is not recoverable! \n\nSee the trace log for more information.";

            return new OpennessApiException(description, exception);
        }

        /// <summary>
        /// Method to wrap a system exception
        /// </summary>
        /// <param name="exception"></param>
        /// <returns></returns>
        public static OpennessApiException CatchedException(Exception exception)
        {
            var description = "An error occurred during processing! \n\nSee the trace log for more information.";

            return new OpennessApiException(description, exception);
        }
    }
}
