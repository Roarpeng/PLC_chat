namespace TiaPortalOpennessInfrastructure.Contracts
{
    /// <summary>
    /// The ISettingsService interface defines the contract for access to the application settings for all modules and services.
    /// </summary>
    public interface ISettingsService
    {
        #region read

        object GetSettingByName(string settingName);

        /// <summary>
        /// Determines the value for the setting HidePreSelectionAssemblyVersion
        /// </summary>
        /// <returns>the value</returns>
        bool GetHidePreSelectionAssemblyVersion();

        /// <summary>
        /// Read the config whether the sinamics startdrive module should be load
        /// </summary>
        /// <returns></returns>
        bool GetLoadSinamicsStartdriveModule();

        /// <summary>
        /// Read the config whether the step7 module should be load
        /// </summary>
        /// <returns></returns>
        bool GetLoadStep7Module();

        /// <summary>
        /// Read the config whether the winCC professional module should be load
        /// </summary>
        /// <returns></returns>
        bool GetLoadWinCcProfessionalModule();

        /// <summary>
        /// Read the config whether the winCC unified module should be load
        /// </summary>
        /// <returns></returns>
        bool GetLoadWinCcUnifiedModule();

        /// <summary>
        /// Determines the value for the setting ExportWithDefaults
        /// </summary>
        /// <returns>the value</returns>
        bool GetExportWithDefaults();

        /// <summary>
        /// Determines the value for the setting ExportReadOnly
        /// </summary>
        /// <returns>the value</returns>
        bool GetExportReadOnly();

        /// <summary>
        /// Determines the value for the setting TreeExpendLevel
        /// </summary>
        /// <returns>the value</returns>
        int GetTreeExpendLevel();

        /// <summary>
        /// Determines the value for the setting DefaultExportPath
        /// </summary>
        /// <returns>the value</returns>
        string GetExportPath();

        /// <summary>
        /// Determines the value for the setting SelectedEngineeringVersion
        /// </summary>
        /// <returns>the value</returns>
        string GetSelectedEngineeringVersion();

        /// <summary>
        /// Determines the value for the setting TiaPortalMode
        /// </summary>
        /// <returns>the value</returns>
        string GetTiaPortalMode();

        /// <summary>
        /// Determines the value for the setting ModulePath
        /// </summary>
        /// <returns>the value</returns>
        string GetModulePath();

        /// <summary>
        /// Determines the value for the setting ProjectPath
        /// </summary>
        /// <returns>the value</returns>
        string GetProjectPath();

        /// <summary>
        /// Determines the value for the setting GlobalUserLibraryPath
        /// </summary>
        /// <returns>the value</returns>
        string GetGlobalUserLibraryPath();

        /// <summary>
        /// Determines the value for the setting LocalSessionPath
        /// </summary>
        /// <returns>the value</returns>
        string GetLocalSessionPath();

        /// <summary>
        /// Determines the value for the setting SelectedOpennessApiVersion
        /// </summary>
        /// <returns>the value</returns>
        string GetSelectedOpennessApiVersion();

        #endregion // read

        #region write

        /// <summary>
        /// Set the value for the setting HidePreSelectionAssemblyVersion
        /// </summary>
        /// <param name="value"></param>
        void SetHidePreSelectionAssemblyVersion(bool value);

        /// <summary>
        /// Set the value for the setting LoadSinamicsStartdriveModule
        /// </summary>
        /// <param name="value"></param>
        void SetLoadSinamicsStartdriveModule(bool value);

        /// <summary>
        /// Set the value for the setting tLoadStep7Module
        /// </summary>
        /// <param name="value"></param>
        void SetLoadStep7Module(bool value);

        /// <summary>
        /// Set the value for the setting LoadWinCcProfessionalModule
        /// </summary>
        /// <param name="value"></param>
        void SetLoadWinCcProfessionalModule(bool value);

        /// <summary>
        /// Set the value for the setting LoadWinCcUnifiedModule
        /// </summary>
        /// <param name="value"></param>
        void SetLoadWinCcUnifiedModule(bool value);

        /// <summary>
        /// Set the value for the setting ExportWithDefaults
        /// </summary>
        /// <param name="value"></param>
        void SetExportWithDefaults(bool value);

        /// <summary>
        /// Set the value for the setting ExportReadOnly
        /// </summary>
        /// <param name="value"></param>
        void SetExportReadOnly(bool value);

        /// <summary>
        /// Set the value for the setting TreeExpendLevel
        /// </summary>
        /// <param name="value"></param>
        void SetTreeExpendLevel(int value);

        /// <summary>
        /// Set the value for the setting DefaultExportPath
        /// </summary>
        /// <param name="value"></param>
        void SetDefaultExportPath(string value);

        /// <summary>
        /// Set the value for the setting SelectedEngineeringVersion
        /// </summary>
        /// <param name="value"></param>
        void SetSelectedEngineeringVersion(string value);

        /// <summary>
        /// Set the value for the setting TiaPortalMode
        /// </summary>
        /// <param name="value"></param>
        void SetTiaPortalMode(string value);

        /// <summary>
        /// Set the value for the setting ModulePath
        /// </summary>
        /// <param name="value"></param>
        void SetModulePath(string value);

        /// <summary>
        /// Set the value for the setting ProjectPath
        /// </summary>
        /// <param name="value"></param>
        void SetProjectPath(string value);

        /// <summary>
        /// Set the value for the setting GlobalUserLibraryPath
        /// </summary>
        /// <param name="value"></param>
        void SetGlobalUserLibraryPath(string value);

        /// <summary>
        /// Set the value for the setting LocalSessionPath
        /// </summary>
        /// <param name="value"></param>
        void SetLocalSessionPath(string value);

        /// <summary>
        /// Set the value for the setting SelectedOpennessApiVersion
        /// </summary>
        /// <param name="value"></param>
        void SetSelectedOpennessApiVersion(string value);

        #endregion // write
    }
}
