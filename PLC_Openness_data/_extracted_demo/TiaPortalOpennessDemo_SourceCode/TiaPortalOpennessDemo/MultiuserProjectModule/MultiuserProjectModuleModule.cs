using MultiuserProjectModule.Views;
using Prism.Ioc;
using Prism.Modularity;
using Prism.Regions;
using TiaPortalOpennessInfrastructure.Constants;

namespace MultiuserProjectModule
{
    public class MultiuserProjectModuleModule : IModule
    {
        private readonly IRegionManager _regionManager;

        /// <summary>
        /// Default constructor with injection (late binding)
        /// </summary>
        /// <param name="regionManager">Injected region manager</param>
        public MultiuserProjectModuleModule(IRegionManager regionManager)
        {
            _regionManager = regionManager;
        }

        public void RegisterTypes(IContainerRegistry containerRegistry)
        {
            containerRegistry.RegisterForNavigation<MultiuserLogicalProjectTreeView>();
            containerRegistry.RegisterForNavigation<MultiuserPhysicalProjectTreeView>();
        }

        public void OnInitialized(IContainerProvider containerProvider)
        {
            _regionManager.RegisterViewWithRegion(RegionNames.ProjectTreeRegion, typeof(MultiuserLogicalProjectTreeView));
            _regionManager.RegisterViewWithRegion(RegionNames.ProjectTreeRegion, typeof(MultiuserPhysicalProjectTreeView));
        }
    }
}
