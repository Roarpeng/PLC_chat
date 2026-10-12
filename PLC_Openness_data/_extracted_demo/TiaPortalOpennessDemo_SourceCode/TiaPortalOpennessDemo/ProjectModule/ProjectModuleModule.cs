using Prism.Ioc;
using Prism.Modularity;
using Prism.Regions;
using ProjectModule.Views;
using TiaPortalOpennessInfrastructure.Constants;

namespace ProjectModule
{
    /// <summary>
    /// The project module
    /// </summary>
    public class ProjectModuleModule : IModule
    {
        private readonly IRegionManager _regionManager;

        /// <summary>
        /// Default constructor with injection (late binding)
        /// </summary>
        /// <param name="regionManager">Injected region manager</param>
        public ProjectModuleModule(IRegionManager regionManager)
        {
            _regionManager = regionManager;
        }

        /// <summary>
        /// Registrations of a view for a target region, it composites the application
        /// </summary>
        /// <param name="containerRegistry">Container registry for registration certain types</param>
        public void RegisterTypes(IContainerRegistry containerRegistry)
        {
            containerRegistry.RegisterForNavigation<LogicalProjectTreeView>();
            containerRegistry.RegisterForNavigation<PhysicalProjectTreeView>();
            containerRegistry.RegisterForNavigation<EmptyProjectTreeView>();
            containerRegistry.Register(typeof(CreateNewTiaPortalProjectView));
        }

        /// <summary>
        /// Initialization of the module
        /// </summary>
        /// <param name="containerProvider">Container provider to resolve certain types</param>
        public void OnInitialized(IContainerProvider containerProvider)
        {
            _regionManager.RegisterViewWithRegion(RegionNames.ProjectTreeRegion, typeof(EmptyProjectTreeView));
            _regionManager.RegisterViewWithRegion(RegionNames.ProjectTreeRegion, typeof(LogicalProjectTreeView));
            _regionManager.RegisterViewWithRegion(RegionNames.ProjectTreeRegion, typeof(PhysicalProjectTreeView));
        }
    }
}
