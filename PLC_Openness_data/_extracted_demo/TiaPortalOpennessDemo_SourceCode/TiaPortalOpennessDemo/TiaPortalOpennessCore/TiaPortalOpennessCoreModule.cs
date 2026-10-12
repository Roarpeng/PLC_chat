using Prism.Ioc;
using Prism.Modularity;
using Prism.Regions;
using TiaPortalOpennessCore.Views;
using TiaPortalOpennessInfrastructure.Constants;

namespace TiaPortalOpennessCore
{
    /// <summary>
    /// The core module for the application
    /// </summary>
    public class TiaPortalOpennessCoreModule : IModule
    {
        private readonly IRegionManager _regionManager;

        /// <summary>
        /// Default constructor with injection (late binding)
        /// </summary>
        /// <param name="regionManager">Injected region manager</param>
        public TiaPortalOpennessCoreModule(IRegionManager regionManager)
        {
            _regionManager = regionManager;
        }

        /// <summary>
        /// Registrations of a view for a target region, it composites the application
        /// </summary>
        /// <param name="containerRegistry">Container registry for registration certain types</param>
        public void RegisterTypes(IContainerRegistry containerRegistry)
        {
            containerRegistry.Register(typeof(AboutInfoView));
        }

        /// <summary>
        /// Initialization of the module
        /// </summary>
        /// <param name="containerProvider">Container provider to resolve certain types</param>
        public void OnInitialized(IContainerProvider containerProvider)
        {
            _regionManager.RegisterViewWithRegion(RegionNames.MenuRegion, typeof(MenuView));
            _regionManager.RegisterViewWithRegion(RegionNames.ToolBarRegion, typeof(ToolBarView));
        }
    }
}
