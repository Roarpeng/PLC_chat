extern alias V16_0;
using System;
using System.IO;
using System.Windows;
using TiaPortalOpennessInfrastructure.Contracts;
using TiaPortalOpennessInfrastructure.Exceptions;
using TiaPortalOpennessInfrastructure.Utils;
using V16_0::Siemens.Engineering;
using V16_0::Siemens.Engineering.SW;
using V16_0::Siemens.Engineering.SW.Blocks;
using V16_0::Siemens.Engineering.SW.ExternalSources;
using V16_0::Siemens.Engineering.SW.Types;

namespace TiaPortalOpennessAdapterService.Services.V16_0.Utils
{
    /// <summary>
    /// Implementation of plc service
    /// </summary>
    public class PlcService : IDisposable
    {
        #region fields

        private readonly ITraceLogService _traceLogService;

        #endregion // fields

        #region ctor

        /// <summary>
        /// Constructor with initialization
        /// </summary>
        /// <param name="traceLogService"></param>
        public PlcService(ITraceLogService traceLogService)
        {
            _traceLogService = traceLogService;
        }

        #endregion // ctor

        #region methods

        /// <summary>
        /// Add external source 
        /// </summary>
        /// <param name="plcExternalSourceGroup"></param>
        /// <param name="externalSourceFileInfo"></param>
        public void AddExternalSource(PlcExternalSourceGroup plcExternalSourceGroup, FileInfo externalSourceFileInfo)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(PlcService) + " - " + nameof(AddExternalSource) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                var temp = plcExternalSourceGroup.ExternalSources.Find(Path.GetFileName(externalSourceFileInfo.FullName));

                temp?.Delete();

                plcExternalSourceGroup.ExternalSources.CreateFromFile(Path.GetFileName(externalSourceFileInfo.FullName), externalSourceFileInfo.FullName);
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
        /// Generate block from source
        /// </summary>
        /// <param name="plcExternalSource"></param>
        public void GenerateBlockFromSource(PlcExternalSource plcExternalSource)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(PlcService) + " - " + nameof(GenerateBlockFromSource) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                plcExternalSource.GenerateBlocksFromSource(GenerateBlockOption.KeepOnError);
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
        /// Generate source from block
        /// </summary>
        /// <param name="plcSoftware"></param>
        /// <param name="blockAsSource"></param>
        /// <param name="destinationFileInfo"></param>
        /// <param name="withDependencies"></param>
        public void GenerateSourceFromBlock(PlcSoftware plcSoftware, IEngineeringInstance blockAsSource, FileInfo destinationFileInfo, bool withDependencies)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(PlcService) + " - " + nameof(GenerateSourceFromBlock) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                if (blockAsSource is PlcBlock plcBlock)
                {
                    if (withDependencies)
                    {
                        plcSoftware.ExternalSourceGroup.GenerateSource(new[] { plcBlock }, destinationFileInfo, GenerateOptions.WithDependencies);
                    }
                    else
                    {
                        plcSoftware.ExternalSourceGroup.GenerateSource(new[] { plcBlock }, destinationFileInfo, GenerateOptions.None);
                    }
                }

                if (blockAsSource is PlcType plcType)
                {
                    plcSoftware.ExternalSourceGroup.GenerateSource(new[] { plcType }, destinationFileInfo);
                }
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

        #region IDisposable

        /// <summary>
        /// Dispose
        /// </summary>
        public void Dispose()
        {
            Dispose(true);
            GC.SuppressFinalize(this);
        }

        /// <summary>
        /// If needed, free up managed and native source.
        /// </summary>
        /// <param name="disposing"></param>
        protected virtual void Dispose(bool disposing)
        {
            if (disposing)
            {
                // free up managed source
            }

            //free up native source
        }

        #endregion // IDisposable
    }
}
