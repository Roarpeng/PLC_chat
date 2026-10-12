extern alias V15_1;
using System;
using System.IO;
using System.Windows;
using TiaPortalOpennessInfrastructure.Contracts;
using TiaPortalOpennessInfrastructure.Exceptions;
using TiaPortalOpennessInfrastructure.Utils;
using V15_1::Siemens.Engineering;
using V15_1::Siemens.Engineering.Cax;

namespace TiaPortalOpennessAdapterService.Services.V15_1.Utils
{
    /// <summary>
    /// Implementation of export service
    /// </summary>
    public class ExportService : IDisposable
    {
        #region fields

        private readonly ITraceLogService _traceLogService;
        private readonly ISettingsService _settingsService;

        #endregion // fields

        #region ctor

        /// <summary>
        /// Constructor with initialization
        /// </summary>
        /// <param name="traceLogService"></param>
        public ExportService(ITraceLogService traceLogService)
        {
            _traceLogService = traceLogService;
        }

        /// <summary>
        /// Constructor with initialization
        /// </summary>
        /// <param name="traceLogService"></param>
        /// <param name="settingsService"></param>
        public ExportService(ITraceLogService traceLogService, ISettingsService settingsService)
        {
            _traceLogService = traceLogService;
            _settingsService = settingsService;
        }

        #endregion // ctor

        #region methods

        /// <summary>
        /// Execute CAx Export for current project
        /// </summary>
        /// <param name="project">current project</param>
        /// <returns></returns>
        public bool CaxExport(Project project)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ExportService) + " - " + nameof(CaxExport) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                if (project == null)
                {
                    throw new ArgumentNullException(nameof(project), "The project parameter for the export is null!");
                }

                var exportPath = _settingsService.GetExportPath();
                if (string.IsNullOrEmpty(exportPath))
                {
                    throw new ArgumentNullException(nameof(exportPath), "The setting value for default export path is null or empty!");
                }

                var exportProvider = project.GetService<CaxProvider>();

                if (exportProvider == null)
                {
                    throw new ArgumentNullException(nameof(project), "The export provider is null!");
                }

                var caxExportFileInfo = new FileInfo(Path.Combine(exportPath, project.Path.Name, project.Name + ".aml"));
                var logFileInfo = new FileInfo(Path.Combine(exportPath, project.Path.Name, "Export.log"));

                var result = exportProvider.Export(project, caxExportFileInfo, logFileInfo);

                if (!result)
                {
                    WriteTraceLogProxy(processInfo.ProcessMessage + " CAx export from " + caxExportFileInfo.Name + " complete!");
                    ReadLogInfos("CAx export log info: ", logFileInfo);
                    return false;
                }

                WriteTraceLogProxy(processInfo.ProcessMessage + " CAx export from " + caxExportFileInfo.Name + " succeed!");
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
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(ExportService) + " - " + nameof(ReadLogInfos) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
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
