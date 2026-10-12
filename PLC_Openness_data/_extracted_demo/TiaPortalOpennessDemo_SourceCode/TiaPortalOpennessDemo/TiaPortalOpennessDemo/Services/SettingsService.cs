using TiaPortalOpennessDemo.Properties;
using TiaPortalOpennessInfrastructure.Contracts;

namespace TiaPortalOpennessDemo.Services
{
    /// <summary>
    /// The SettingsService for centralized access to the application settings.
    /// </summary>
    public class SettingsService : ISettingsService
    {
        #region methods

        #region read

        public object GetSettingByName(string settingName)
        {
            return Settings.Default[settingName];
        }

        /// <summary>
        /// Read the hide pre selection assembly version setting
        /// </summary>
        /// <returns>setting value</returns>
        public bool GetHidePreSelectionAssemblyVersion()
        {
            return Settings.Default.HidePreSelectionAssemblyVersion;
        }

        /// <summary>
        /// Read the config whether the sinamics startdrive module should be load
        /// </summary>
        /// <returns></returns>
        public bool GetLoadSinamicsStartdriveModule()
        {
            return Settings.Default.LoadSinamicsStartdriveModule;
        }

        /// <summary>
        /// Read the config whether the step7 module should be load
        /// </summary>
        /// <returns></returns>
        public bool GetLoadStep7Module()
        {
            return Settings.Default.LoadStep7Module;
        }

        /// <summary>
        /// Read the config whether the winCC professional module should be load
        /// </summary>
        /// <returns></returns>
        public bool GetLoadWinCcProfessionalModule()
        {
            return Settings.Default.LoadWinCcProfessionalModule;
        }

        /// <summary>
        /// Read the config whether the winCC unified module should be load
        /// </summary>
        /// <returns></returns>
        public bool GetLoadWinCcUnifiedModule()
        {
            return Settings.Default.LoadWinCcUnifiedModule;
        }

        /// <summary>
        /// Read the hide export with defaults setting
        /// </summary>
        /// <returns>setting value</returns>
        public bool GetExportWithDefaults()
        {
            return Settings.Default.ExportWithDefaults;
        }

        /// <summary>
        /// Read the hide export read only setting
        /// </summary>
        /// <returns>setting value</returns>
        public bool GetExportReadOnly()
        {
            return Settings.Default.ExportReadOnly;
        }

        /// <summary>
        /// Read the hide tree expand level setting
        /// </summary>
        /// <returns>setting value</returns>
        public int GetTreeExpendLevel()
        {
            return Settings.Default.TreeExpendLevel;
        }

        /// <summary>
        /// Read the hide export path setting
        /// </summary>
        /// <returns>setting value</returns>
        public string GetExportPath()
        {
            return Settings.Default.DefaultExportPath;
        }

        /// <summary>
        /// Read the hide selected engineering version setting
        /// </summary>
        /// <returns>setting value</returns>
        public string GetSelectedEngineeringVersion()
        {
            return Settings.Default.SelectedEngineeringVersion;
        }

        /// <summary>
        /// Read the hide tia portal mode setting
        /// </summary>
        /// <returns>setting value</returns>
        public string GetTiaPortalMode()
        {
            return Settings.Default.TiaPortalMode;
        }

        /// <summary>
        /// Read the hide module path setting
        /// </summary>
        /// <returns>setting value</returns>
        public string GetModulePath()
        {
            return Settings.Default.ModulePath;
        }

        /// <summary>
        /// Read the hide project path setting
        /// </summary>
        /// <returns>setting value</returns>
        public string GetProjectPath()
        {
            return Settings.Default.ProjectPath;
        }

        /// <summary>
        /// Read the hide global user library path setting
        /// </summary>
        /// <returns>setting value</returns>
        public string GetGlobalUserLibraryPath()
        {
            return Settings.Default.GlobalUserLibraryPath;
        }

        /// <summary>
        /// Read the hide local session path setting
        /// </summary>
        /// <returns>setting value</returns>
        public string GetLocalSessionPath()
        {
            return Settings.Default.LocalSessionPath;
        }

        /// <summary>
        /// Read the hide selected openness api version setting
        /// </summary>
        /// <returns>setting value</returns>
        public string GetSelectedOpennessApiVersion()
        {
            return Settings.Default.SelectedOpennessApiVersion;
        }

        #endregion // read

        #region write

        /// <summary>
        /// Write the pre selection assembly Version setting
        /// </summary>
        /// <param name="value">value to be set</param>
        public void SetHidePreSelectionAssemblyVersion(bool value)
        {
            Settings.Default.HidePreSelectionAssemblyVersion = value;
            Settings.Default.Save();
        }

        /// <summary>
        /// Set the value for the setting LoadSinamicsStartdriveModule
        /// </summary>
        /// <param name="value"></param>
        public void SetLoadSinamicsStartdriveModule(bool value)
        {
            Settings.Default.LoadSinamicsStartdriveModule = value;
            Settings.Default.Save();
        }

        /// <summary>
        /// Set the value for the setting tLoadStep7Module
        /// </summary>
        /// <param name="value"></param>
        public void SetLoadStep7Module(bool value)
        {
            Settings.Default.LoadStep7Module = value;
            Settings.Default.Save();
        }

        /// <summary>
        /// Set the value for the setting LoadWinCcProfessionalModule
        /// </summary>
        /// <param name="value"></param>
        public void SetLoadWinCcProfessionalModule(bool value)
        {
            Settings.Default.LoadWinCcProfessionalModule = value;
            Settings.Default.Save();
        }

        /// <summary>
        /// Set the value for the setting LoadWinCcUnifiedModule
        /// </summary>
        /// <param name="value"></param>
        public void SetLoadWinCcUnifiedModule(bool value)
        {
            Settings.Default.LoadWinCcUnifiedModule = value;
            Settings.Default.Save();
        }


        /// <summary>
        /// Write the export with default setting
        /// </summary>
        /// <param name="value">value to be set</param>
        public void SetExportWithDefaults(bool value)
        {
            Settings.Default.ExportWithDefaults = value;
            Settings.Default.Save();
        }

        /// <summary>
        /// Write the export read only setting
        /// </summary>
        /// <param name="value">value to be set</param>
        public void SetExportReadOnly(bool value)
        {
            Settings.Default.ExportReadOnly = value;
            Settings.Default.Save();
        }

        /// <summary>
        /// Write the tree expand level setting
        /// </summary>
        /// <param name="value">value to be set</param>
        public void SetTreeExpendLevel(int value)
        {
            Settings.Default.TreeExpendLevel = value;
            Settings.Default.Save();
        }

        /// <summary>
        /// Write the default export path setting
        /// </summary>
        /// <param name="value">value to be set</param>
        public void SetDefaultExportPath(string value)
        {
            Settings.Default.DefaultExportPath = value;
            Settings.Default.Save();
        }

        /// <summary>
        /// Write the selected engineering version setting
        /// </summary>
        /// <param name="value">value to be set</param>
        public void SetSelectedEngineeringVersion(string value)
        {
            Settings.Default.SelectedEngineeringVersion = value;
            Settings.Default.Save();
        }

        /// <summary>
        /// Write the tia portal mode setting
        /// </summary>
        /// <param name="value">value to be set</param>
        public void SetTiaPortalMode(string value)
        {
            Settings.Default.TiaPortalMode = value;
            Settings.Default.Save();
        }

        /// <summary>
        /// Write the module path setting
        /// </summary>
        /// <param name="value">value to be set</param>
        public void SetModulePath(string value)
        {
            Settings.Default.ModulePath = value;
            Settings.Default.Save();
        }

        /// <summary>
        /// Write the project path setting
        /// </summary>
        /// <param name="value">value to be set</param>
        public void SetProjectPath(string value)
        {
            Settings.Default.ProjectPath = value;
            Settings.Default.Save();
        }

        /// <summary>
        /// Write the global user library path setting
        /// </summary>
        /// <param name="value">value to be set</param>
        public void SetGlobalUserLibraryPath(string value)
        {
            Settings.Default.GlobalUserLibraryPath = value;
            Settings.Default.Save();
        }

        /// <summary>
        /// Write the local session path setting
        /// </summary>
        /// <param name="value">value to be set</param>
        public void SetLocalSessionPath(string value)
        {
            Settings.Default.LocalSessionPath = value;
            Settings.Default.Save();
        }

        /// <summary>
        /// Write the selected openness api version setting
        /// </summary>
        /// <param name="value">value to be set</param>
        public void SetSelectedOpennessApiVersion(string value)
        {
            Settings.Default.SelectedOpennessApiVersion = value;
            Settings.Default.Save();
        }

        #endregion // write

        #endregion // methods
    }
}
