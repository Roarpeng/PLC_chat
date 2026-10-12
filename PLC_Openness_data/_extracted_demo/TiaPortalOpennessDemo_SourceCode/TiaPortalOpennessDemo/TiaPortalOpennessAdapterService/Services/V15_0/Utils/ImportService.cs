extern alias V15_0;
using System;
using System.IO;
using System.Windows;
using TiaPortalOpennessAdapter.Services;
using TiaPortalOpennessAdapterBase.Enums;
using TiaPortalOpennessInfrastructure.Contracts;
using TiaPortalOpennessInfrastructure.Exceptions;
using TiaPortalOpennessInfrastructure.Utils;
using V15_0::Siemens.Engineering;
using V15_0::Siemens.Engineering.Cax;

namespace TiaPortalOpennessAdapterService.Services.V15_0.Utils
{
    /// <summary>
    /// Implementation of import service
    /// </summary>
    public class ImportService : IDisposable
    {
        #region fields

        private readonly ITraceLogService _traceLogService;

        #endregion // fields

        #region ctor

        /// <summary>
        /// Constructor with initialization
        /// </summary>
        /// <param name="traceLogService"></param>
        public ImportService(ITraceLogService traceLogService)
        {
            _traceLogService = traceLogService;
        }

        #endregion // ctor

        #region methods

        /// <summary>
        /// Import caxImportFile to current project with CAx Import options
        /// </summary>
        /// <param name="project">current project</param>
        /// <param name="caxImportFileInfo">CAx import file</param>
        /// <param name="importOption">CAx import option</param>
        /// <returns></returns>
        public bool CaxImport(Project project, FileInfo caxImportFileInfo, CaxImportOption importOption)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ImportService) + " - " + nameof(CaxImport) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                if (project == null)
                {
                    throw new ArgumentNullException(nameof(project), @"The project parameter for the import is null!");
                }

                var importProvider = project.GetService<CaxProvider>();

                if (importProvider == null)
                {
                    throw new ArgumentNullException(nameof(importProvider), @"The import provider is null!");
                }

                var caxImportOption = EnumService.GetEnumValue<CaxImportOptions>(importOption.ToString());
                if (caxImportFileInfo.Directory == null)
                {
                    throw new ArgumentNullException(nameof(caxImportFileInfo), @"The cax import file info is null!");
                }

                var importPath = caxImportFileInfo.Directory.FullName;
                var logFileInfo = new FileInfo(Path.Combine(importPath, "Import.log"));

                var result = importProvider.Import(caxImportFileInfo, logFileInfo, caxImportOption);

                if (!result)
                {
                    WriteTraceLogProxy(processInfo.ProcessMessage + " CAx import from " + caxImportFileInfo.Name + " complete!");
                    ReadLogInfos("CAx import log info: ", logFileInfo);
                    return false;
                }

                WriteTraceLogProxy(processInfo.ProcessMessage + " CAx import from " + caxImportFileInfo.Name + " succeed!");
                return true;

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

        private void ReadLogInfos(string caxInfoType, FileInfo logFileInfo)
        {
            using (var streamReader = new StreamReader(logFileInfo.FullName))
            {
                string logInfo;

                while ((logInfo = streamReader.ReadLine()) != null)
                {
                    if (logInfo.Contains("ERROR") || logInfo.Contains("WARN") || logInfo.Contains("completed"))
                    {
                        WriteTraceLogProxy(caxInfoType + logInfo);
                    }
                }

                streamReader.Close();
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
