extern alias V16_0;
using System;
using System.Windows;
using TiaPortalOpennessAdapterContracts;
using TiaPortalOpennessInfrastructure.Contracts;
using TiaPortalOpennessInfrastructure.Exceptions;
using V16_0::Siemens.Engineering;


namespace WinCcUnified.Services.V16_0
{
    /// <summary>
    /// Implementation of WinCC unified service
    /// </summary>
    public class WinCcUnifiedService : IHmiSoftwareService
    {
        #region fields

        private const string ExceptionMessage = "This kind of master copy is not supported.";
        private ITraceLogService _traceLogService;

        #endregion // fields

        #region ctor

        public WinCcUnifiedService(ITraceLogService traceLogService)
        {
            _traceLogService = traceLogService;
        }

        #endregion // ctor

        #region methods

        #region common

        /// <summary>
        /// Retrieve whether item is known
        /// </summary>
        /// <param name="item"></param>
        /// <returns></returns>
        public bool IsKnownObject(Type item)
        {
            // not supported
            return false;
        }

        /// <summary>
        /// Retrieve whether item is hmi software
        /// </summary>
        /// <param name="item"></param>
        /// <returns></returns>
        public bool IsHmiSoftware(object item)
        {
            // not supported
            return false;
        }

        #endregion // common

        #region hmi software structure

        /// <summary>
        /// Retrieve structure as generic method definition
        /// </summary>
        /// <typeparam name="T1">generic type</typeparam>
        /// <typeparam name="T2">generic type</typeparam>
        /// <typeparam name="T3">generic type</typeparam>
        /// <typeparam name="T4">generic type</typeparam>
        /// <param name="deviceItem"></param>
        /// <param name="treeItem"></param>
        /// <param name="engineeringProjectItem"></param>
        /// <param name="engineeringProjectModel"></param>
        public void GetStructure<T1, T2, T3, T4>(T1 deviceItem, T2 treeItem, T3 engineeringProjectItem, T4 engineeringProjectModel)
        {
            // not available in version 16.0
        }

        #endregion // hmi software structure

        #region mastercopy

        /// <summary>
        /// Create a copy to project from master copy, not available in version 16.0 
        /// </summary>
        /// <param name="copyDestination"></param>
        /// <param name="copySource"></param>
        public void CreateCopyFromMasterCopy(object copyDestination, object copySource)
        {
            try
            {
                throw new InvalidOperationException(ExceptionMessage);
            }
            catch (EngineeringException engineeringException)
            {
                throw OpennessApiExceptionHandler.CatchedEngineeringException(engineeringException);
            }
            catch (NonRecoverableException nonRecoverableException)
            {
                throw OpennessApiExceptionHandler.CatchedNonRecoverableException(nonRecoverableException);
            }
            catch (OpennessApiException)
            {
                throw;
            }
            catch (Exception exception)
            {
                throw OpennessApiExceptionHandler.CatchedException(exception);
            }
        }

        /// <summary>
        /// Retrieve hmi software from item, not available in version 16.0
        /// </summary>
        /// <param name="item"></param>
        /// <returns></returns>
        public object GetHmiSoftware(object item)
        {
            return null;
        }

        #endregion // mastercopy

        #endregion // methods

        #region trace

        /// <summary>
        /// Execute writing trace log in different thread.
        /// </summary>
        /// <param name="traceLog"></param>
        private void WriteTraceLogProxy(string traceLog)
        {
            Application.Current.Dispatcher.Invoke(delegate
            {
                _traceLogService.Write(traceLog);
            });
        }

        #endregion // trace
    }
}
