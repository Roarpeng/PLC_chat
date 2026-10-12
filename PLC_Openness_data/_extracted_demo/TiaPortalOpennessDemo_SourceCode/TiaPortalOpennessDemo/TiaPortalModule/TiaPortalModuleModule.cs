using Prism.Ioc;
using Prism.Modularity;
using Prism.Regions;
using TiaPortalModule.Views;
using TiaPortalOpennessInfrastructure.Constants;

namespace TiaPortalModule
{
    /// <summary>
    /// The TIA Portal module 
    /// </summary>
    public class TiaPortalModuleModule : IModule
    {
        private readonly IRegionManager _regionManager;

        /// <summary>
        /// Default constructor with injection (late binding)
        /// </summary>
        /// <param name="regionManager">Injected region manager</param>
        public TiaPortalModuleModule(IRegionManager regionManager)
        {
            _regionManager = regionManager;
        }

        /// <summary>
        /// Registrations of a view for a target region, it composites the application
        /// </summary>
        /// <param name="containerRegistry">Container registry for registration certain types</param>
        public void RegisterTypes(IContainerRegistry containerRegistry)
        {
            containerRegistry.Register(typeof(SettingsEditorView));
        }

        /// <summary>
        /// Initialization of the module
        /// </summary>
        /// <param name="containerProvider">Container provider to resolve certain types</param>
        public void OnInitialized(IContainerProvider containerProvider)
        {
            _regionManager.RegisterViewWithRegion(RegionNames.TiaPortalRegion, typeof(TiaPortalView));
        }
    }
}
