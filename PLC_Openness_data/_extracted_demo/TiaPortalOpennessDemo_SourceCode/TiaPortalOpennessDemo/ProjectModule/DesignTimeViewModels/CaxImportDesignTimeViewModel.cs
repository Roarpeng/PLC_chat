using ProjectModule.ViewModels;
using System.Collections.ObjectModel;
using System.ComponentModel;
using TiaPortalOpennessAdapterBase.Enums;
using TiaPortalOpennessAdapterBase.Models;

namespace ProjectModule.DesignTimeViewModels
{
    /// <summary>
    /// SettingsEditorDesignTimeViewModel for design time only.
    /// </summary>
    [DesignOnly(true)]
    public class CaxImportDesignTimeViewModel : CaxImportViewModel
    {
        /// <summary>
        /// Constructor for design time only.
        /// </summary>
        [DesignOnly(true)]
        public CaxImportDesignTimeViewModel()
            : base(@"C:\..\xy\..",
                new ObservableCollection<CaxImportOptionInfo>() { new CaxImportOptionInfo() { OptionType = CaxImportOption.MoveToParkingLot, OptionName = "Move xyz" }, new CaxImportOptionInfo() { OptionType = CaxImportOption.OverwriteTiaDevice, OptionName = "Move d" } },
                new CaxImportOptionInfo() { OptionType = CaxImportOption.OverwriteTiaDevice, OptionName = "Move d" })
        {
        }
    }
}
