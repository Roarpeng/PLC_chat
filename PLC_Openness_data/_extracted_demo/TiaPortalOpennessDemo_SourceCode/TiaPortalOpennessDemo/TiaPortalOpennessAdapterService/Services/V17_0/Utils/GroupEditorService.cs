extern alias V17_0;
using System;
using System.Collections.Generic;
using TiaPortalOpennessAdapterBase.Base;
using TiaPortalOpennessAdapterBase.Enums;
using TiaPortalOpennessInfrastructure.Contracts;
using TiaPortalOpennessInfrastructure.Exceptions;
using TiaPortalOpennessInfrastructure.Utils;
using V17_0::Siemens.Engineering;
using V17_0::Siemens.Engineering.HW;
using V17_0::Siemens.Engineering.SW.Blocks;
using V17_0::Siemens.Engineering.SW.ExternalSources;
using V17_0::Siemens.Engineering.SW.Tags;
using V17_0::Siemens.Engineering.SW.TechnologicalObjects;
using V17_0::Siemens.Engineering.SW.Types;
using V17_0::Siemens.Engineering.SW.WatchAndForceTables;
using Application = System.Windows.Application;

namespace TiaPortalOpennessAdapterService.Services.V17_0.Utils
{
    /// <summary>
    /// Implementation of group editor
    /// </summary>
    public class GroupEditorService : IDisposable
    {
        #region fields

        private readonly ITraceLogService                      _traceLogService;

        #endregion // fields

        #region ctor

        /// <summary>
        /// Constructor with initialization
        /// </summary>
        /// <param name="traceLogService"></param>
        public GroupEditorService(ITraceLogService traceLogService)
        {
            _traceLogService = traceLogService;
        }

        #endregion // ctor

        #region methods

        /// <summary>
        /// Create group
        /// </summary>
        /// <param name="projectItem"></param>
        /// <param name="groupName"></param>
        public void CreateGroup(ProjectItem projectItem, string groupName)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(GroupEditorService) + " - " + nameof(CreateGroup) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                if (projectItem.DeviceItem is DeviceUserGroup item)
                {
                    AddNewGroup(item, groupName);
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

        private void AddNewGroup(DeviceUserGroup typeGroup, string groupName)
        {
            var processInfo = new ProcessInfo() { ProcessMessageId = Guid.NewGuid(), ProcessMessage = nameof(GroupEditorService) + " - " + nameof(DeviceUserGroup) };
            WriteTraceLogProxy(processInfo.ProcessMessage);

            try
            {
                WriteTraceLogProxy(processInfo.ProcessMessage + " -> " + groupName);
                typeGroup.Groups.Create(groupName);
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
