using System.Collections.Generic;
using System.ComponentModel;
using TiaPortalModule.ViewModels;
using TiaPortalOpennessAdapter.Models;
using TiaPortalOpennessAdapterBase.Enums;

namespace TiaPortalModule.DesignTimeViewModels
{
    /// <summary>
    /// TiaPortalDesignTimeViewModel for design time only.
    /// </summary>
    [DesignOnly(true)]
    public class TiaPortalDesignTimeViewModel : TiaPortalViewModel
    {
        /// <summary>
        /// Constructor for design time only.
        /// </summary>
        [DesignOnly(true)]
        public TiaPortalDesignTimeViewModel()
        : base(TiaPortalStartMode.WithUserInterface, "ID 1234 xyz", new OpennessDemoModel() { TiaPortalProcesses = new List<string> { "ID 1234 xyz", "ID 2345 xyz" }, SelectedProcessId = "ID 2345 xyz", ProjectInformation = new List<string>() { "ID 1234 project xyz", "ID 2345 project xyz" } })
        {

        }
    }
}
