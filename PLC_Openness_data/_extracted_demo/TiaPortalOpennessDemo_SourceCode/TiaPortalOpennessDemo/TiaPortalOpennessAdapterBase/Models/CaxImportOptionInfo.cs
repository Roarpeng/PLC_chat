using TiaPortalOpennessAdapterBase.Enums;

namespace TiaPortalOpennessAdapterBase.Models
{
    /// <summary>
    /// Definition of CAx import option info
    /// </summary>
    public class CaxImportOptionInfo : ObservableObject
    {
        private string          _optionName;
        private CaxImportOption _optionType;

        /// <summary>
        /// Import option name
        /// </summary>
        public string OptionName
        {
            get => _optionName;
            set => SetProperty(ref _optionName, value);
        }

        /// <summary>
        /// The CAx import option enum value
        /// </summary>
        public CaxImportOption OptionType
        {
            get => _optionType;
            set => SetProperty(ref _optionType, value);
        }
    }
}
